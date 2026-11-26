"""Compare calendar self-report source transactions against the Python command in two migrated test schemas."""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import psycopg
from sqlalchemy.engine import make_url

from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema

NOW = datetime(2026, 3, 9, 3, 30, tzinfo=UTC)  # March 8 in the athlete's zone, after the DST change.


def uid(n):
    return str(UUID(int=n))


def seed(env):
    with psycopg.connect(env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"]) as db:
        name, schema = db.execute("SELECT current_database(), current_schema()").fetchone()
        if name != "garmin_test" or not re.fullmatch(r"go_parity_[0-9a-f]{32}", schema):
            raise ValueError("expected the runner's migrated test schema")
        for version in (1, 2):
            db.execute("INSERT INTO calendar_versions(id,number,kind,actor) VALUES(gen_random_uuid(),%s,'manual_edit','user')", (version,))
        db.execute("UPDATE app_state SET data_revision=10,calendar_head_version=1 WHERE id=1")
        # Newer revisions above the head are invisible to completion.
        for n, version, day, kind, deleted in [
            (1, 1, 8, "run", False), (1, 2, 9, "rest", True), (2, 1, 8, "strength", False),
            (3, 1, 8, "rest", False), (4, 1, 9, "run", False), (5, 1, 8, "run", True),
            (6, 1, 8, "run", False), (7, 1, 8, "run", False),
        ]:
            db.execute("""INSERT INTO calendar_session_revisions
                (id, session_uid, revision, calendar_version_number, deleted, local_date, kind, intent, certainty)
                VALUES(gen_random_uuid(),%s,%s,%s,%s,make_date(2026,3,%s),%s,'fixture','committed')""",
                       (uid(n), version, version, deleted, day, kind))
        db.execute("""INSERT INTO activities (id,start_at,original_start,local_date,sport,canonical_revision,resolution_state,field_provenance)
            VALUES (%s,'2026-03-08 03:30Z','2026-03-08T03:30Z','2026-03-08','running',1,'resolved','{}')""", (uid(80),))
        db.execute("""INSERT INTO session_completions(id,session_uid,activity_id,status,match_method,input_version,version,updated_at)
            VALUES(gen_random_uuid(),%s,%s,'moved','confirmed_move',3,5,now())""", (uid(6), uid(80)))


def reference():
    from app.db import SessionLocal
    from app.errors import AppError
    from app.services import calendar, derived
    from app.services.timezone import athlete_today
    from sqlalchemy import text

    derived.install()
    checks = [
        ("today after DST transition", 1, 0, "completed_as_planned", {}),
        ("unchanged retry at current version", 1, 1, "completed_as_planned", {}),
        ("stale undo", 1, 0, "unknown", {}),
        ("changed disclosure", 1, 1, "completed_as_planned", {"modification_reason": "schedule", "reason_note": "Late start"}),
        ("undo", 1, 2, "unknown", {}),
        ("skip", 2, 0, "skipped", {}),
        ("undo skipped", 2, 1, "unknown", {}),
        ("rest day", 3, 0, "completed_as_planned", {}),
        ("tomorrow in athlete timezone", 4, 0, "completed_as_planned", {}),
        ("deleted workout", 5, 0, "completed_as_planned", {}),
        ("unknown session", 90, 0, "completed_as_planned", {}),
        ("protected recording", 6, 5, "completed_as_planned", {}),
        ("clear prior recording", 6, 5, "skipped", {"reason_note": "Corrected entry"}),
        ("rollback refresh failure", 7, 0, "completed_as_planned", {}),
        ("retry after rollback", 7, 0, "completed_as_planned", {}),
        ("unknown without preexisting completion", 91, 0, "unknown", {}),
        ("invalid reason", 1, 0, "skipped", {"modification_reason": "unspecified"}),
    ]
    result = []
    for name, n, version, status, extra in checks:
        body = {"expected_version": version, "status": status, **extra}
        fail = name == "rollback refresh failure"
        code = ""
        try:
            with (patch.object(calendar, "calendar_today", lambda s: athlete_today(s, NOW)),
                  patch.object(derived, "REFRESH_ENABLED", fail),
                  patch.object(derived, "refresh_scopes", side_effect=RuntimeError("injected refresh failure")),
                  SessionLocal.begin() as session):
                calendar.put_completion(session, UUID(int=n), body, assess=_unexpected_assessment)
        except AppError as exc:
            code = exc.code
        except RuntimeError as exc:
            if not fail or str(exc) != "injected refresh failure":
                raise
            code = "refresh_failure"
        with SessionLocal() as session:
            stored = session.execute(text("""SELECT to_jsonb(c) - 'id' - 'updated_at'
                FROM session_completions c WHERE session_uid=:uid"""), {"uid": UUID(int=n)}).scalar()
            revision, head = session.execute(text("SELECT data_revision,calendar_head_version FROM app_state WHERE id=1")).one()
        result.append(dict(name=name, uid=uid(n), body=body, fail=fail, error=code, stored=stored, revision=revision, head=head))
    return result


def _unexpected_assessment(*args):
    raise AssertionError("self-report called linked-recording assessor")


def main():
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if (os.environ.get("APP_MODE") != "test" or url.database != "garmin_test"
            or url.host not in {"127.0.0.1", "localhost"} or str(url.port) != os.environ.get("TEST_DATABASE_PORT")
            or url.query or os.environ.get("DATABASE_URL") != os.environ["TEST_DATABASE_URL"]):
        raise SystemExit("use the isolated PostgreSQL test runner")
    pg_url = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(pg_url, autocommit=True) as db, tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp:
        directory = Path(tmp)
        with (migrated_schema(db, url, directory / "reference", "5173") as ref,
              migrated_schema(db, url, directory / "go", "5173") as go):
            seed(ref)
            seed(go)
            corpus = directory / "cases.json"
            subprocess.run([sys.executable, __file__, "reference", str(corpus)], check=True, cwd=BACKEND,
                           env={**ref, "PYTHONPATH": str(BACKEND)})
            subprocess.run(["go", "test", "-race", "-count=1", "-v", "./internal/calendar"], cwd=MODULE,
                           env={**go, "COMPLETION_CASES": str(corpus)}, check=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["reference"]:
        Path(sys.argv[2]).write_text(json.dumps(reference()))
    else:
        main()
