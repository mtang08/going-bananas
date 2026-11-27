"""Compare native recovery history with Python on two independently migrated test schemas."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
from check_self_reports import uid
from sqlalchemy.engine import make_url
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema

KEYS = [
    "night:2026-01-01",
    "night:2026-03-03",
    "night:2026-03-19",
    "night:2026-03-30",
    "w7:2026-03-30",
    "w7:2026-01-02",
]
CHANGE = "UPDATE checkins_v2 SET version=2,fatigue=2 WHERE idempotency_key='night'; UPDATE recovery_observations SET source_revision='corrected',value=8.5 WHERE metric='hrv' AND source_date='2026-03-30'"
STATE = """SELECT jsonb_build_object('rows',coalesce((SELECT jsonb_agg(to_jsonb(m)-'id'-'calculated_at' ORDER BY subject_key,dependency_hash) FROM metric_results m),'[]'),'config',(SELECT jsonb_agg(to_jsonb(c)-'id'-'created_at') FROM metric_configs c WHERE metric_id='recovery_multisignal_summary'))"""


def seed(env):
    with psycopg.connect(
        env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"]
    ) as db:
        db.execute(
            "INSERT INTO source_accounts(id,provider,account_scope) VALUES(%s,'garmin','fixture')",
            (uid(101),),
        )
        db.execute(
            "INSERT INTO raw_objects(id,sha256,relative_path,media_type,byte_size) VALUES(%s,'abc','fixture','application/json',5)",
            (uid(102),),
        )
        db.execute(
            """INSERT INTO source_records(id,source_account_id,raw_object_id,source_identity,payload_hash,fetched_at,parser_version,source_kind,fields)
          VALUES(%s,%s,%s,'fixture','abc',now(),'1','recovery','{}')""",
            (uid(103), uid(101), uid(102)),
        )
        for d in range(30):
            for i, (metric, stat, base) in enumerate(
                [
                    ("sleep", "main_sleep_duration", 22000),
                    ("hrv", "last_night_average", 48),
                    ("resting_hr", "daily_resting", 55),
                ]
            ):
                value = base + (d % 6 if i != 2 else 0)
                if d == 29 and i == 1:
                    value = 20
                if d == 17 and i == 0:
                    value = -1
                db.execute(
                    """INSERT INTO recovery_observations(id,source_account_id,source_record_id,metric,source_date,time_semantics,value,unit,statistic,source_revision)
                VALUES(%s,%s,%s,%s,date '2026-03-01'+%s,'source_night',%s,'test',%s,'r1')""",
                    (
                        uid(1000 + d * 3 + i),
                        uid(101),
                        uid(103) if d != 2 else None,
                        metric,
                        d,
                        value,
                        stat,
                    ),
                )
        db.execute(
            """INSERT INTO checkins_v2(id,idempotency_key,kind,observed_at,fatigue,illness)
           VALUES(%s,'night','exception','2026-03-31 01:15:10.120Z',8,'present')""",
            (uid(105),),
        )


def reference():
    from app.db import SessionLocal
    from app.metrics import engine, recovery
    from sqlalchemy import text

    result = []
    for change in ["", "", CHANGE]:
        with SessionLocal.begin() as s:
            engine.ensure_configs(s)
            for sql in filter(None, change.split(";")):
                s.execute(text(sql))
            for key in KEYS:
                engine.upsert_results(s, recovery.compute(s, key))
            s.flush()
            result.append(
                {
                    "sql": change,
                    "keys": KEYS,
                    "state": s.execute(text(STATE)).scalar_one(),
                }
            )
    return result


def compare(script, populate, package, fixture_env):
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if not (
        os.getenv("APP_MODE") == "test"
        and url.database == "garmin_test"
        and url.host in {"localhost", "127.0.0.1"}
        and str(url.port) == os.getenv("TEST_DATABASE_PORT")
        and not url.query
        and os.environ["TEST_DATABASE_URL"] == os.getenv("DATABASE_URL")
    ):
        raise SystemExit("requires isolated test database")
    with (
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
    ):
        d = Path(tmp)
        with (
            migrated_schema(db, url, d / "reference", "5173") as py,
            migrated_schema(db, url, d / "go", "5173") as go,
        ):
            for env in [py, go]:
                populate(env)
            data = d / "cases.json"
            subprocess.run(
                [sys.executable, script, "reference", str(data)],
                cwd=BACKEND,
                env={**py, "PYTHONPATH": str(BACKEND)},
                check=True,
            )
            subprocess.run(
                [
                    "go",
                    "test",
                    "-race",
                    "-count=1",
                    "-v",
                    package,
                ],
                cwd=MODULE,
                env={**go, fixture_env: str(data)},
                check=True,
            )


if __name__ == "__main__":
    if sys.argv[1:2] == ["reference"]:
        Path(sys.argv[2]).write_text(json.dumps({"cases": reference(), "query": STATE}))
    else:
        compare(__file__, seed, "./internal/metrics/recovery", "RECOVERY_CASES")
