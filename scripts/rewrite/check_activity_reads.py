"""Replay the captured activity read contract against a fresh synthetic schema."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import psycopg
from check_aerobic import seed as seed_runs
from check_recovery import seed as seed_recovery
from check_self_reports import uid
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url
from test_proposal_slice import MODULE, ROOT, migrated_schema


def seed(env):
    seed_runs(env)
    seed_recovery(env)

    with psycopg.connect(
        env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"]
    ) as db:
        value = {
            "n_planned": 2,
            "n_completed": 1,
            "step_completion_ratio": 0.5,
            "cv_speed": None,
            "last_first_change_pct": None,
            "target_coverage": 0.89,
            "reps": [
                {
                    "fully_completed": True,
                    "speed_status": "available",
                    "mean_speed_mps": 3.001,
                    "actual_timer_s": 200.0,
                    "hr_median_bpm": 151.5,
                }
            ],
        }
        db.execute(
            """INSERT INTO metric_results(id,metric_id,method_version,subject_type,subject_key,status,value,reason_codes,quality_flags,
                    source_refs,config_hash,dependency_hash,calculated_at,timezone) VALUES(%s,'work_interval_execution','v2','activity',%s,'partial',%s,
                    ARRAY['INCOMPLETE_WORK_STEPS'],'{}','{}','prior','fixture','2026-03-04','UTC')""",
            (uid(9950), uid(2000), Jsonb(value)),
        )

        db.execute(
            """INSERT INTO coverage_intervals(id,dataset,start_date,end_date,status,completed_at,fully_enumerated)
                    VALUES(%s,'activities','2026-03-01','2026-03-31','complete','2026-04-01T20:30:00.500Z',true)""",
            (uid(9949),),
        )
        db.execute("UPDATE session_completions SET updated_at='2026-03-04 13:00Z'")
        db.execute(
            "UPDATE activities SET end_at=start_at + interval '1 hour' WHERE id=%s",
            (uid(2000),),
        )
        db.execute(
            """INSERT INTO prompts(id,kind,activity_id,opens_at,closes_at,status)
           VALUES(%s,'delayed_symptom',%s,'2026-03-05','2026-03-06','open')""",
            (uid(9901), uid(2000)),
        )
        db.execute(
            """INSERT INTO checkins_v2(id,idempotency_key,kind,activity_id,prompt_id,observed_at,recorded_at,pain_reported)
           VALUES(%s,'response','delayed_followup',%s,%s,'2026-03-05T12:00Z','2026-03-05T13:00Z',true)""",
            (uid(9902), uid(2000), uid(9901)),
        )
        db.execute(
            """INSERT INTO symptom_reports(id,checkin_id,site,side,severity,timing)
           VALUES(%s,%s,'knee','left',2,'next_morning')""",
            (uid(9903), uid(9902)),
        )
        db.execute(
            """INSERT INTO session_rpe(id,activity_id,rpe,source,collected_at) VALUES(%s,%s,6,'manual','2026-03-06')""",
            (uid(9904), uid(2000)),
        )


def exercise(populate, name, state=None):
    expected = MODULE / "internal/activityhttp/testdata" / f"{name}.json"
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if not (
        os.environ.get("APP_MODE") == "test"
        and os.environ.get("DATABASE_URL") == os.environ["TEST_DATABASE_URL"]
        and url.database == "garmin_test"
        and url.host in {"127.0.0.1", "localhost"}
        and str(url.port) == os.environ.get("TEST_DATABASE_PORT")
        and not url.query
    ):
        raise SystemExit("requires isolated test database")
    with (
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
        migrated_schema(db, url, Path(tmp) / name, "5173") as env,
    ):
        populate(env)
        subprocess.run(
            ["go", "test", "-race", "-count=1", "-v", "./internal/activityhttp"],
            cwd=MODULE,
            env={**env, "ACTIVITY_HTTP_FIXTURE": str(expected)},
            check=True,
        )
        if state is not None:
            want = json.loads(expected.read_text())["state"]
            got = json.loads(json.dumps(state(env), default=str))
            assert got.keys() == want.keys()
            for table in want:
                if got[table] != want[table]:
                    raise AssertionError((table, got[table], want[table]))


if __name__ == "__main__":
    exercise(seed, "activity-reads")
