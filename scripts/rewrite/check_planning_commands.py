"""Compare planning HTTP commands on independently migrated test schemas."""

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
from test_proposal_slice import ROOT, MODULE, migrated_schema

NOW = datetime(2026, 11, 16, 15, tzinfo=UTC)


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
                    dict(
                        kind="time_trial",
                        protocol="Test trial",
                        planned_date="2026-11-17",
                        distance_m=5000,
                    )
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
    with (
        tempfile.TemporaryDirectory(dir=ROOT / "private") as d,
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as db,
    ):
        p = Path(d)
        with (
            migrated_schema(db, url, p / "ref", "5173") as ref,
            migrated_schema(db, url, p / "go", "5173") as go,
        ):
            for env in (ref, go):
                seed(env)
            corpus = p / "commands.json"
            subprocess.run(
                [sys.executable, __file__, "reference", str(corpus)],
                cwd=ROOT,
                env={**ref, "PYTHONPATH": str(ROOT / "backend")},
                check=True,
            )
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
                env={**go, "PLANNING_COMMAND_CASES": str(corpus)},
                check=True,
            )

            def state(env):
                with psycopg.connect(
                    env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"]
                ) as conn:
                    return [
                        conn.execute(query).fetchall()
                        for query in [
                            "select name,event_date,distance_m,purpose,status,goal_time_s,result_s,rank,version from events order by name",
                            "select data_revision,calendar_head_version from app_state",
                            "select label,version,default_weekday,active,main_lower_body_lifts from strength_routine_slots order by version,label",
                            "select block_uid,block_version,activity_id,event_id,outcome,protocol,distance_m,result_s,local_date,match_method from block_benchmarks",
                        ]
                    ]

            assert state(ref) == state(go)
            print(
                f"Matched {len(json.loads(corpus.read_text()))} planning commands and stored state."
            )


def reference(path):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import planning
    from app.services import strength_routine

    cases = []
    client = TestClient(app)

    def call(method, route, body=None):
        res = client.request(
            method, "/api/v1" + route, json=body, headers={"X-Local-Request": "1"}
        )
        data = res.json()
        if "error" in data:
            data["error"].pop("request_id", None)
        cases.append(
            dict(
                method=method,
                path=route,
                body=json.loads(json.dumps(body)),
                status=res.status_code,
                expected=data,
            )
        )
        return data.get("data", {})

    with (
        patch.object(planning, "athlete_today", return_value=NOW.date()),
        patch.object(strength_routine, "date_in_zone", return_value=NOW.date()),
    ):
        call("GET", "/events")
        call("PUT", "/events/order", {"items": []})
        payload = dict(
            name=" A ", event_date="2027-03-01", purpose="pr", distance_m=10000
        )
        a = call("POST", "/events", payload)["id"]
        b = call("POST", "/events", dict(payload, name="B", event_date="2027-01-01"))[
            "id"
        ]
        call("POST", "/events", dict(payload, name="  "))
        call("GET", "/events")
        order = [dict(id=b, expected_version=1), dict(id=a, expected_version=1)]
        call("PUT", "/events/order", {"items": order[:1]})
        call("PUT", "/events/order", {"items": order})
        call("PUT", "/events/order", {"items": order})
        for item in order:
            item["expected_version"] = 2
        call("PUT", "/events/order", {"items": order})
        for body in [
            dict(expected_version=1),
            dict(expected_version=2, purpose=None),
            dict(expected_version=2, status="completed", distance_m=None),
            dict(expected_version=3),
        ]:
            call("PATCH", "/events/" + b, body)
        call("GET", "/events")
        call("GET", "/blocks/active")
        call("GET", "/blocks/benchmarks")
        call("GET", f"/blocks/{BLOCK}/history")
        call("GET", f"/blocks/{MISSING}/history")
        call("GET", f"/events/{EVENT}/blocks")
        call("GET", f"/events/{MISSING}/blocks")
        call("PUT", f"/blocks/{MISSING}/benchmark-activity", {"activity_id": None})
        for activity in [MISSING, RUN, None, None]:
            call(
                "PUT", f"/blocks/{BLOCK}/benchmark-activity", {"activity_id": activity}
            )
            call("GET", "/blocks/active")
        call("GET", "/blocks/benchmarks")
        call("GET", "/strength-routine")
        slot = dict(
            label="  Main ",
            default_weekday=1,
            lower_body_cost="moderate",
            main_lower_body_lifts=[" Squat "],
        )
        for expected, slots in [
            (0, []),
            (2, [slot]),
            (0, [dict(slot, default_weekday=8)]),
            (0, [slot]),
            (1, [dict(slot, active=False)]),
        ]:
            call(
                "PUT", "/strength-routine", dict(expected_version=expected, slots=slots)
            )
        call("GET", "/strength-routine")
    path.write_text(json.dumps(cases))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        reference(Path(sys.argv[2]))
    else:
        main()
