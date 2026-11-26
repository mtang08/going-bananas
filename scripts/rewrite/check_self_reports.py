"""Compare calendar recording links and self-report transactions against the Python command in two migrated test schemas."""

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

        db.execute("INSERT INTO manual_sessions(id,version,date,kind) VALUES (%s,1,'2026-03-08','strength')", (uid(81),))
        db.execute("INSERT INTO source_accounts(id,provider,account_scope) VALUES (%s,'strong','fixture')", (uid(82),))
        db.execute("""INSERT INTO raw_objects(id,sha256,relative_path,byte_size,media_type)
                    VALUES (%s,'fixture','fixture',0,'text/plain')""", (uid(83),))
        db.execute("""INSERT INTO source_records(id,source_account_id,raw_object_id,source_identity,payload_hash,
                  fetched_at,parser_version,source_kind,fields) VALUES (%s,%s,%s,'fixture','fixture',now(),'1','strong','{}')""",
                  (uid(84), uid(82), uid(83)))
        db.execute("""INSERT INTO strong_workouts(id,source_account_id,source_identity,source_record_id,raw_object_id,
                  payload_hash,local_date,local_start,workout_name,sets,row_count,resolution_state)
                  VALUES (%s,%s,'fixture',%s,%s,'fixture','2026-03-08','2026-03-08T10:00:00','Fixture','[]',0,'resolved')""",
                  (uid(85), uid(82), uid(84), uid(83)))
        for n, key, subject, status, method in [(8,"manual_session_id",81,"partial","auto_same_day"),
                                                (9,"strong_workout_id",85,"extra","none")]:
            db.execute(f"""INSERT INTO session_completions(id,session_uid,{key},status,match_method,version,input_version,updated_at)
                     VALUES(gen_random_uuid(),%s,%s,%s,%s,4,2,now())""", (uid(n),uid(subject),status,method))


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
        ("missing recording", 2, 0, None, {"activity_id": uid(99)}),
        ("displace automatic association", 2, 0, None, {"manual_session_id": uid(81)}),
        ("current retry preserves assessment", 2, 1, None, {"manual_session_id": uid(81)}),
        ("explicit holder conflict", 1, 0, None, {"manual_session_id": uid(81)}),
        ("stale linked edit", 2, 0, None, {"strong_workout_id": uid(85)}),
        ("rollback assessor after extra displacement", 2, 1, None, {"strong_workout_id": uid(85)}),
        ("rollback linked refresh", 2, 1, None, {"strong_workout_id": uid(85)}),
        ("displace extra and replace recording", 2, 1, None, {"strong_workout_id": uid(85)}),
        ("moved recording overrides assessment", 2, 2, None, {"activity_id": uid(80)}),
        ("confirmed move holder conflict", 1, 0, None, {"activity_id": uid(80)}),
    ]
    result = []
    for name, n, version, status, extra in checks:
        body = {"expected_version": version, **({"status": status} if status else {}), **extra}
        fail = name in {"rollback refresh failure", "rollback linked refresh"}
        code = ""
        try:
            with (patch.object(calendar, "calendar_today", lambda s: athlete_today(s, NOW)),
                  patch.object(derived, "REFRESH_ENABLED", fail),
                  patch.object(derived, "refresh_scopes", side_effect=RuntimeError("injected refresh failure")),
                  SessionLocal.begin() as session):
                def assess(s, session_uid):
                    from app.calendar_models import SessionCompletion
                    from sqlalchemy import select
                    if status:
                        _unexpected_assessment()
                    row = s.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == session_uid))
                    if name == "current retry preserves assessment":
                        assert row.status == "partial"
                    row.status = "partial"
                    if name == "rollback assessor after extra displacement":
                        raise RuntimeError("assessment_failure")
                calendar.put_completion(session, UUID(int=n), body, assess=assess)
        except AppError as exc:
            code = exc.code
        except RuntimeError as exc:
            if str(exc) == "assessment_failure":
                code = "assessment_failure"
            elif not fail or str(exc) != "injected refresh failure":
                raise
            else:
                code = "refresh_failure"
        with SessionLocal() as session:
            stored = session.execute(text("""SELECT to_jsonb(c) - 'id' - 'updated_at'
                FROM session_completions c WHERE session_uid=:uid"""), {"uid": UUID(int=n)}).scalar()
            revision, head = session.execute(text("SELECT data_revision,calendar_head_version FROM app_state WHERE id=1")).one()
            holders = session.execute(text("""SELECT coalesce(jsonb_object_agg(session_uid, to_jsonb(c)-'id'-'updated_at'), '{}')
                FROM session_completions c""")).scalar()
        result.append(dict(holders=holders,name=name, uid=uid(n), body=body, fail=fail, error=code, stored=stored, revision=revision, head=head))
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
