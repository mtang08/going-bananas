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

    with patch.object(planning, "athlete_today", return_value=NOW.date()):
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
    path.write_text(json.dumps(cases))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        reference(Path(sys.argv[2]))
    else:
        main()
