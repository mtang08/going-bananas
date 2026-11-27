"""Replay synthetic planning commands against the Go API in a disposable schema."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url
from test_proposal_slice import MODULE, ROOT, migrated_schema

BLOCK = "00000000-0000-4000-8000-000000000001"
RUN = "00000000-0000-4000-8000-000000000002"
EVENT = "00000000-0000-4000-8000-000000000003"
MISSING = "00000000-0000-4000-8000-000000000004"


def seed(env):
    import re

    with psycopg.connect(
        env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"]
    ) as conn:
        db, schema = conn.execute(
            "select current_database(),current_schema()"
        ).fetchone()
        assert db == "garmin_test" and re.fullmatch(r"go_parity_[0-9a-f]{32}", schema)
        conn.execute(
            "insert into events(id,name,event_date,status,purpose) values(%s,'Old race','2020-01-01','completed','benchmark')",
            (EVENT,),
        )
        conn.execute("insert into blocks(id,block_uid) values(%s,%s)", (BLOCK, BLOCK))
        conn.execute(
            """insert into block_versions(id,block_uid,version,status,objective,progression_dimension,constraints,start_date,review_date,objective_status,created_at,target_event_id,benchmark)
            values(%s,%s,1,'active','Test pace','duration','{}','2026-10-01','2026-11-20','unresolved','2026-10-01T10:00:00.123450Z',%s,%s::jsonb)""",
            (
                BLOCK,
                BLOCK,
                EVENT,
                json.dumps(
                    {
                        "kind": "time_trial",
                        "protocol": "Test trial",
                        "planned_date": "2026-11-17",
                        "distance_m": 5000,
                    }
                ),
            ),
        )
        conn.execute(
            """insert into activities(id,start_at,end_at,original_start,local_date,sport,canonical_revision,resolution_state,field_provenance,timer_s,distance_m)
            values(%s,'2026-11-15T04:30Z','2026-11-15T05:10Z','fixture','2026-11-15','running',1,'resolved','{}',2400.5,5000.5)""",
            (RUN,),
        )
        conn.execute(
            """insert into block_benchmarks(id,block_uid,block_version,match_method,protocol,outcome) values(%s,%s,1,'auto','Test trial','progress')""",
            (RUN, BLOCK),
        )
        conn.execute(
            "insert into source_accounts(id,provider,account_scope) values(%s,'synthetic','fixture')",
            (BLOCK,),
        )
        conn.execute(
            "insert into raw_objects(id,sha256,relative_path,byte_size,media_type) values(%s,%s,'fixture',1,'application/json')",
            (BLOCK, "a" * 64),
        )
        conn.execute(
            """insert into source_records(id,source_account_id,raw_object_id,source_identity,payload_hash,fetched_at,parser_version,source_kind,fields) values(%s,%s,%s,'fixture',%s,now(),'1','synthetic','{}')""",
            (BLOCK, BLOCK, BLOCK, "b" * 64),
        )
        conn.execute(
            """insert into strong_workouts(id,source_account_id,source_identity,source_record_id,raw_object_id,payload_hash,local_date,local_start,workout_name,duration_s,sets,row_count)
        values(%s,%s,'fixture',%s,%s,%s,'2026-11-11','2026-11-11 10:00:00',' Week A ',1950,'[{"Exercise Name":"Deadlift"},{"Exercise Name":"deadlift"},{"Exercise Name":"Curl"}]',3)""",
            (BLOCK, BLOCK, BLOCK, BLOCK, "c" * 64),
        )


# Request/response and resulting state captured with synthetic inputs at e5e565d.
CORPUS = MODULE / "internal/planninghttp/testdata/commands.json"
STATE_QUERIES = {
    "events": """
        SELECT name,event_date,distance_m,purpose,status,goal_time_s,result_s,rank,version
        FROM events ORDER BY name
    """,
    "app_state": "SELECT data_revision,calendar_head_version FROM app_state",
    "metrics": """
        SELECT metric_id,subject_key,status,value,
               CASE WHEN subject_type='window' AND metric_id IN (
                   'aerobic_efficiency','long_run_exposure','intensity_time_distribution'
               ) THEN NULL ELSE dependency_hash END,config_hash,timezone
        FROM metric_results WHERE is_current ORDER BY metric_id,subject_key
    """,
    "profile_versions": """
        SELECT to_jsonb(p)-'id'-'effective_at'-'recorded_at' FROM profile_versions p ORDER BY version
    """,
    "strength_slots": """
        SELECT label,version,default_weekday,active,main_lower_body_lifts
        FROM strength_routine_slots ORDER BY version,label
    """,
    "block_benchmarks": """
        SELECT block_uid,block_version,activity_id,event_id,outcome,protocol,distance_m,result_s,
               local_date,match_method
        FROM block_benchmarks
    """,
}


def main():
    url = make_url(os.environ["DATABASE_URL"])
    if url.password is None and os.environ.get("PGPASSWORD"):
        url = url.set(password=os.environ["PGPASSWORD"])
    if (
        os.environ.get("APP_MODE") != "test"
        or url.database != "garmin_test"
        or url.host not in {"localhost", "127.0.0.1"}
    ):
        raise ValueError("requires synthetic test runner")
    fixture = json.loads(CORPUS.read_text())
    with (
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as db,
        migrated_schema(db, url, Path(tmp) / "go", "5173") as env,
    ):
        seed(env)
        subprocess.run(
            [
                "go",
                "test",
                "-count=1",
                "-run",
                "^TestReferencePlanningCommands$",
                "./internal/planninghttp",
            ],
            cwd=MODULE,
            env={**env, "PLANNING_COMMAND_CASES": str(CORPUS)},
            check=True,
        )
        with psycopg.connect(
            env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"]
        ) as conn:
            assert fixture["state"].keys() == STATE_QUERIES.keys()
            for table, query in STATE_QUERIES.items():
                # Keep SQL dates and UUIDs in the same string form as the synthetic capture.
                rows = json.loads(
                    json.dumps(conn.execute(query).fetchall(), default=str)
                )
                expected = fixture["state"][table]
                assert rows == expected, (
                    table,
                    [row for row in expected if row not in rows][:1],
                    [row for row in rows if row not in expected][:1],
                )
    print(f"Matched {len(fixture['cases'])} planning HTTP commands and stored state.")


if __name__ == "__main__":
    main()
