"""Compare every detector input against the Python reader in one disposable PostgreSQL schema."""

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

from check_assessment_db import conn, id, seed
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema


def reference(target):
    from app.db import SessionLocal
    from app.services.exceptions.inputs import collect_detection_inputs

    def encode(value):
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, frozenset):
            return sorted(value)
        raise TypeError(type(value).__name__)

    with SessionLocal() as session:
        cases = [
            asdict(collect_detection_inputs(session, datetime.fromisoformat(instant)))
            for instant in (
                "2026-10-20T23:30:00+00:00",
                "2026-11-02T03:30:00+00:00",
                "2026-11-12T13:00:00+00:00",
                "2026-11-22T12:00:00+00:00",
                "2027-02-03T15:00:00+00:00",
            )
        ]
        target.write_text(json.dumps(cases, default=encode))


def exercise(env, scratch):
    seed(env)
    with conn(env) as db:
        (schema,) = db.execute("SELECT current_schema()").fetchone()
        db.execute("""
            INSERT INTO checkins_v2(id,idempotency_key,kind,observed_at,recorded_at,context_tags)
            SELECT md5(n::text||'check')::uuid,CASE n WHEN 1 THEN 'phone-first-steps:fixture' ELSE 'fixture' END||n::text,
                   'exception','2026-11-11 15:00:00Z','2026-11-11 15:00:00Z',ARRAY['travel']
              FROM generate_series(1,2) n
        """)
        db.execute("""INSERT INTO symptom_reports(id,checkin_id,site,side,severity,timing)
            SELECT md5(id::text)::uuid,id,'calf','left',3,'next_morning' FROM checkins_v2""")
        db.execute(
            "UPDATE calendar_session_revisions SET intent='Easy recovery run' WHERE session_uid=%s",
            (id(1),),
        )
        db.execute(
            "UPDATE calendar_session_revisions SET recipe_id='REC005' WHERE session_uid=%s",
            (id(4),),
        )
        db.execute(
            """INSERT INTO metric_results(id,metric_id,method_version,subject_type,subject_key,status,value,
            source_refs,config_hash,calculated_at,dependency_hash,timezone)
            VALUES (md5('adverse')::uuid,'recovery_multisignal_summary','v1','night','night:2026-11-21',
            'available','{"hrv":{"adverse":true}}','[]','test',now(),'fixture-adverse','America/New_York'),
            (md5('assessment')::uuid,'planned_actual_session','v2','session',%s,'available',
            '{"components":[{"name":"target_coverage","status":"partial"}]}','[]','test',now(),'fixture-plan','America/New_York')
        """,
            (id(1),),
        )
        db.execute("""INSERT INTO profile_versions(id,version,effective_at,recorded_at,timezone,anchor_confirmed,
            strength_days_confirmed,scheduled_strength_days,facts,preferences,unknowns)
            SELECT md5(n::text||'profile')::uuid,100+n,'2026-10-01'::date+n,'2026-10-01'::date+n,
            'America/New_York',false,false,'[]',
            CASE n WHEN 1 THEN '{}' WHEN 2 THEN '{"clinician_restriction":"fixture restriction"}'
                   ELSE '{"clinical_restriction":"fixture restriction"}' END::jsonb,'{}','[]'
            FROM generate_series(1,3) n""")
    pg_url = make_url(env["PROPOSAL_TEST_DATABASE_URL"]).update_query_dict(
        {"search_path": schema}
    )
    env.update(
        DASHBOARD_TEST_DATABASE_URL=pg_url.render_as_string(hide_password=False),
        PYTHONPATH=str(BACKEND),
    )
    target = scratch / "facts.json"
    for phase in ("empty", "event", "trial"):
        if phase != "empty":
            subprocess.run(
                [
                    sys.executable,
                    MODULE
                    / "internal/coaching/snapshotreads/testdata/block_reference.py",
                    phase,
                ],
                env=env,
                check=True,
                stdout=subprocess.DEVNULL,
            )
        subprocess.run(
            [sys.executable, __file__, "reference", target], env=env, check=True
        )
        subprocess.run(
            [
                "go",
                "test",
                "-race",
                "-count=1",
                "-run",
                "TestPythonInputs",
                "./internal/exceptions",
            ],
            cwd=MODULE,
            env={**env, "DETECTOR_REFERENCE": str(target)},
            check=True,
        )


def main():
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if (
        os.environ.get("APP_MODE") != "test"
        or url.database != "garmin_test"
        or url.host not in {"localhost", "127.0.0.1"}
        or url.query
        or str(url.port) != os.environ.get("TEST_DATABASE_PORT")
        or os.environ.get("DATABASE_URL") != os.environ["TEST_DATABASE_URL"]
    ):
        raise SystemExit(
            "Use scripts/test-db.py exception-inputs on the isolated synthetic database."
        )
    with psycopg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False),
        autocommit=True,
    ) as db:
        with tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp:
            with migrated_schema(db, url, Path(tmp) / "inputs", "0") as env:
                exercise(env, Path(tmp))


if __name__ == "__main__":
    if sys.argv[1:2] == ["reference"]:
        reference(Path(sys.argv[2]))
    else:
        main()
