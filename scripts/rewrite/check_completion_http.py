"""Compare PUT completion responses and stored findings on separate migrated schemas."""

import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import psycopg
from sqlalchemy.engine import make_url

from check_assessment_db import conn, id
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema

NOW = datetime(2026, 11, 22, 12, 0, 0, 123400, tzinfo=UTC)
PREFIX = "/api/v1/calendar/completions/"


def seed(env):
    with conn(env) as db:
        db.execute(
            "INSERT INTO calendar_versions(id,number,kind,actor) VALUES(%s,1,'bootstrap','system')",
            (id(100),),
        )
        db.execute("UPDATE app_state SET calendar_head_version=1 WHERE id=1")
        for n in (1, 2, 10):
            db.execute(
                """INSERT INTO calendar_session_revisions(id,session_uid,revision,calendar_version_number,local_date,kind,certainty,intent,planned_duration_s)
                VALUES(%s,%s,1,1,%s,'run','committed','fixture',1800)""",
                (id(110 + n), id(n), "2026-11-18" if n == 1 else "2026-11-21"),
            )
        db.execute(
            """INSERT INTO activities(id,start_at,end_at,original_start,local_date,sport,timer_s,canonical_revision,resolution_state,field_provenance)
            VALUES(%s,'2026-11-21 02:00Z','2026-11-21 02:30Z','2026-11-21T02:00Z','2026-11-21','running',1800,1,'resolved','{}')""",
            (id(25),),
        )
        db.execute(
            """INSERT INTO checkins_v2(id,idempotency_key,kind,observed_at,gait_change,pain_reported) VALUES(%s,'fixture','exception','2026-11-22 09:00Z','yes',true)""",
            (id(26),),
        )
        db.execute(
            "INSERT INTO symptom_reports(id,checkin_id,site,side,severity,timing) VALUES(%s,%s,'ankle','left',5.0,'later')",
            (id(27), id(26)),
        )


def reference():
    from fastapi.testclient import TestClient
    from app.api import calendar as route
    from app.main import app
    from app.metrics import refresh
    from app.services import calendar

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    cases = [
        ("bad", '{"status":"invalid","new":1,"expected_version":-1}'),
        ("bad", "{"),
        (id(1), "null"),
        (id(1), "[]"),
        (id(1), '{"expected_version":1.5,"manual_session_id":4,"reason_note":0}'),
        (id(1), '{"status":null}'),
        (id(1), "{}"),
        (id(1), '{"reason_note":"ignored","activity_id":null}'),
        (id(1), json.dumps({"activity_id": id(25), "status": None})),
        (id(1), json.dumps({"activity_id": id(25), "strong_workout_id": id(30)})),
        (id(1), json.dumps({"activity_id": id(999)})),
        (
            id(1),
            '{"expected_version":"0","status":"completed_as_planned","reason_note":"  noted  "}',
        ),
        (id(1), '{"expected_version":0,"status":"unknown"}'),
        (id(1), '{"expected_version":true,"status":"unknown"}'),
        (id(1), '{"status":"skipped","modification_reason":"weather"}'),
        (id(1), '{"expected_version":"1.0","status":"unknown"}'),
        (
            id(1),
            json.dumps(
                {
                    "activity_id": id(25).replace("-", ""),
                    "reason_note": "across local midnight",
                }
            ),
        ),
        (id(2), json.dumps({"activity_id": id(25)})),
        (id(1), '{"expected_version":null,"status":"unknown"}'),
    ]
    out = []
    with (
        patch.object(calendar, "datetime", Clock),
        patch.object(route, "datetime", Clock),
        patch.object(refresh, "clock", lambda _: NOW),
        TestClient(app) as client,
    ):
        for uid, body in cases:
            path = PREFIX + uid
            result = client.put(
                path,
                content=body,
                headers={"X-Local-Request": "1", "Content-Type": "application/json"},
            )
            value = result.json()
            if "error" in value:
                value["error"].pop("request_id", None)
            if isinstance(value.get("data"), dict):
                with conn(os.environ) as db:
                    assert (
                        str(
                            db.execute(
                                "SELECT id FROM session_completions WHERE session_uid=%s",
                                (uid,),
                            ).fetchone()[0]
                        )
                        == value["data"]["id"]
                    )
                value["data"]["id"] = "verified-database-id"
            out.append(
                dict(path=path, body=body, status=result.status_code, response=value)
            )
    return out


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
        ) as admin,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as temp,
    ):
        directory = Path(temp)
        for suffix, zone in [("offset", "Asia/Kathmandu"), ("utc", "UTC")]:
            with (
                migrated_schema(admin, url, directory / f"ref-{suffix}", "5173") as py,
                migrated_schema(admin, url, directory / f"go-{suffix}", "5173") as go,
            ):
                for env in (py, go):
                    env["PGOPTIONS"] = env["PGOPTIONS"].replace("Asia/Kathmandu", zone)
                    seed(env)
                corpus = directory / "cases.json"
                subprocess.run(
                    [sys.executable, __file__, "reference", str(corpus)],
                    env=dict(py, PYTHONPATH=str(BACKEND)),
                    cwd=BACKEND,
                    check=True,
                )
                subprocess.run(
                    ["go", "test", "-race", "-count=1", "./internal/completionhttp"],
                    cwd=MODULE,
                    env=dict(go, COMPLETION_HTTP_CASES=str(corpus)),
                    check=True,
                )
                # Force failures on either side of the post-commit detector boundary.
                for table, operation in [
                    ("metric_results", "metric-fail"),
                    ("exception_findings", "detect-fail"),
                ]:
                    with conn(go) as control:
                        control.execute("""CREATE OR REPLACE FUNCTION fail_completion_http() RETURNS trigger LANGUAGE plpgsql AS $$
                            BEGIN RAISE EXCEPTION 'synthetic completion failure'; END $$""")
                        control.execute(
                            f"CREATE TRIGGER fail_http BEFORE INSERT OR UPDATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION fail_completion_http()"
                        )
                    subprocess.run(
                        [
                            "go",
                            "test",
                            "-race",
                            "-count=1",
                            "./internal/completionhttp",
                        ],
                        cwd=MODULE,
                        env=dict(
                            go,
                            COMPLETION_HTTP_CASES=str(corpus),
                            COMPLETION_HTTP_FAILURE=operation,
                        ),
                        check=True,
                    )
                    with conn(go) as control:
                        control.execute(f"DROP TRIGGER fail_http ON {table}")
                result = []
                for env in (py, go):
                    with conn(env) as db:
                        result.append(
                            db.execute(
                                "SELECT rule_code,severity,status FROM exception_findings ORDER BY rule_code,severity,status"
                            ).fetchall()
                        )
                assert result[0] and result[0] == result[1], result
                print(
                    "PASS completion HTTP validation, local-date responses, post-write exception findings and concurrent version conflict"
                )


if __name__ == "__main__":
    if sys.argv[1:2] == ["reference"]:
        Path(sys.argv[2]).write_text(json.dumps(reference()))
    else:
        main()
