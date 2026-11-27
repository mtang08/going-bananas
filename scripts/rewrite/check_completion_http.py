"""Check native completion responses and stored findings against synthetic contract fixtures."""

import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

from check_assessment_db import conn, id
from test_proposal_slice import MODULE, ROOT, migrated_schema

NOW = datetime(2026, 11, 22, 12, 0, 0, 123400, tzinfo=UTC)


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
            with migrated_schema(admin, url, directory / suffix, "5173") as go:
                go["PGOPTIONS"] = go["PGOPTIONS"].replace("Asia/Kathmandu", zone)
                seed(go)
                corpus = MODULE / "internal/completionhttp/testdata" / f"completion-{suffix}.json"
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
                with conn(go) as db:
                    findings = db.execute(
                        "SELECT rule_code,severity,status FROM exception_findings ORDER BY rule_code,severity,status"
                    ).fetchall()
                assert findings == [("GAIT_CHANGE", "hold", "open"), ("SYM_NEW_SITE", "observe", "open")]
                print(
                    "PASS completion HTTP validation, local-date responses, post-write exception findings and concurrent version conflict"
                )


if __name__ == "__main__":
    main()
