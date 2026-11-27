"""Check native prompt and RPE responses and their persisted effects."""

import json
import os
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

from training_fixture import conn, id, seed_assessment as seed
from check_completion_http import NOW
from test_proposal_slice import MODULE, ROOT, migrated_schema


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
        with migrated_schema(db, url, directory / "go", "5173") as go:
            seed_feedback(go)
            corpus = MODULE / "internal/feedbackhttp/testdata/feedback.json"
            subprocess.run(
                ["go", "test", "-race", "-count=1", "./internal/feedbackhttp"],
                cwd=MODULE,
                env=dict(go, FEEDBACK_HTTP_CASES=str(corpus)),
                check=True,
            )
            actual = json.loads(json.dumps(state(go), default=str))
            assert actual == json.loads(corpus.with_suffix(".state.json").read_text())
            print(
                "PASS prompt ordering and dismissal, activity and strength RPE, retries, revisions, metrics, prompts and exception findings"
            )


if __name__ == "__main__":
    main()
