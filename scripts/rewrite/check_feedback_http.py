"""Compare prompt and RPE responses and database effects in two migrated schemas."""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import psycopg
from sqlalchemy.engine import make_url

from check_assessment_db import conn, id, seed
from check_completion_http import NOW
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema


def seed_feedback(env):
    seed(env)
    with conn(env) as db:
        for n, status, opens, closes in [
            (401, "open", -1, 1),
            (402, "open", -1, 1),
            (403, "open", 1, 2),
            (404, "open", -2, 0),
            (405, "answered", -1, None),
            (406, "expired", -2, -1),
        ]:
            db.execute(
                "INSERT INTO prompts(id,kind,session_uid,opens_at,closes_at,status) VALUES(%s,'unmatched_session',%s,%s,%s,%s)",
                (
                    id(n),
                    id(n + 20),
                    NOW + timedelta(days=opens),
                    None if closes is None else NOW + timedelta(days=closes),
                    status,
                ),
            )
        db.execute(
            """INSERT INTO checkins_v2(id,idempotency_key,kind,observed_at,illness) VALUES(%s,'feedback','exception','2026-11-22T10:00Z','present')""",
            (id(499),),
        )
        db.execute(
            """INSERT INTO activities(id,start_at,original_start,local_date,sport,canonical_revision,resolution_state,field_provenance) VALUES(%s,now(),'synthetic','2026-11-20','cycling',1,'resolved','{}')""",
            (id(498),),
        )


def reference():
    from fastapi.testclient import TestClient
    from app.api import checkins
    from app.main import app
    from app.metrics import refresh

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    run = f"/activities/{id(21)}/rpe"
    strength = f"/strength/history/{id(30)}/rpe"
    cases = [
        ("GET", "/prompts", ""),
        ("POST", "/prompts/bad/dismiss", ""),
        ("POST", f"/prompts/{id(800)}/dismiss", ""),
        ("POST", f"/prompts/{id(405)}/dismiss", ""),
        ("POST", f"/prompts/{id(402)}/dismiss", ""),
        ("POST", f"/prompts/{id(402)}/dismiss", ""),
        ("POST", f"/prompts/{id(406)}/dismiss", ""),
        ("GET", "/prompts", ""),
        ("PUT", "/activities/bad/rpe", '{"rpe":true,"extra":1}'),
        ("PUT", run, "{"),
        ("PUT", run, "null"),
        ("PUT", run, "{}"),
        ("PUT", run, '{"rpe":null}'),
        ("PUT", run, '{"rpe":"5.00"}'),
        ("PUT", run, '{"rpe":10.1}'),
        ("PUT", run, '{"rpe":"NaN"}'),
        ("PUT", f"/activities/{id(498)}/rpe", '{"rpe":4}'),
        ("PUT", f"/strength/history/{id(499)}/rpe", '{"rpe":3}'),
        ("PUT", run, '{"rpe":"45e-1"}'),
        ("PUT", run, '{"rpe":4.50}'),
        ("PUT", run, '{"rpe":0}'),
        ("PUT", strength, '{"rpe":8}'),
        ("PUT", strength, '{"rpe":"8"}'),
    ]
    results = []
    with (
        patch.object(checkins, "datetime", Clock),
        patch.object(refresh, "clock", lambda _: NOW),
        TestClient(app) as client,
    ):
        for method, path, body in cases:
            path = "/api/v1" + path
            response = client.request(
                method,
                path,
                content=body,
                headers={"Content-Type": "application/json", "X-Local-Request": "1"},
            )
            value = response.json()
            if "error" in value:
                value["error"].pop("request_id", None)
            results.append(
                dict(
                    method=method,
                    path=path,
                    body=body,
                    status=response.status_code,
                    response=value,
                )
            )
    return results


def state(env):
    with conn(env) as db:
        return (
            db.execute(
                "SELECT activity_id,strong_workout_id,rpe,collected_at,collection_delay_s FROM session_rpe ORDER BY activity_id,strong_workout_id"
            ).fetchall(),
            db.execute(
                "SELECT kind,activity_id,session_uid,status,opens_at,closes_at FROM prompts ORDER BY kind,activity_id,session_uid"
            ).fetchall(),
            db.execute(
                "SELECT rule_code,status,severity FROM exception_findings ORDER BY rule_code,status,severity"
            ).fetchall(),
            db.execute("SELECT data_revision FROM app_state WHERE id=1").fetchone(),
            db.execute(
                "SELECT metric_id,subject_key,status,value FROM metric_results WHERE is_current ORDER BY metric_id,subject_key"
            ).fetchall(),
        )


def main():
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if (
        os.environ.get("APP_MODE") != "test"
        or url.database != "garmin_test"
        or url.host not in {"127.0.0.1", "localhost"}
        or url.query
        or os.environ["DATABASE_URL"] != os.environ["TEST_DATABASE_URL"]
        or str(url.port) != os.environ["TEST_DATABASE_PORT"]
    ):
        raise SystemExit("requires isolated test runner")
    with (
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as temp,
    ):
        directory = Path(temp)
        with (
            migrated_schema(db, url, directory / "ref", "5173") as py,
            migrated_schema(db, url, directory / "go", "5173") as go,
        ):
            for env in (py, go):
                seed_feedback(env)
            corpus = directory / "cases.json"
            subprocess.run(
                [sys.executable, __file__, "reference", str(corpus)],
                env=dict(py, PYTHONPATH=str(BACKEND)),
                cwd=BACKEND,
                check=True,
            )
            subprocess.run(
                ["go", "test", "-race", "-count=1", "./internal/feedbackhttp"],
                cwd=MODULE,
                env=dict(go, FEEDBACK_HTTP_CASES=str(corpus)),
                check=True,
            )
            left, right = state(py), state(go)
            for n, (a, b) in enumerate(zip(left, right, strict=True)):
                if a != b:
                    if isinstance(a, list):
                        for x, y in zip(a, b):
                            if x != y:
                                raise AssertionError((n, x, y))
                    raise AssertionError((n, len(a), len(b)))
            print(
                "PASS prompt ordering and dismissal, activity and strength RPE, retries, revisions, metrics, prompts and exception findings"
            )


if __name__ == "__main__":
    if sys.argv[1:2] == ["reference"]:
        Path(sys.argv[2]).write_text(json.dumps(reference()))
    else:
        main()
