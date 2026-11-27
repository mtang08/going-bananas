"""Compare manual calendar and anchor HTTP commands on independently migrated test schemas."""

import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import psycopg
from sqlalchemy.engine import make_url
from test_proposal_slice import ROOT, MODULE, migrated_schema

NOW = datetime(2026, 11, 16, 15, tzinfo=UTC)


def seed(env):
    with psycopg.connect(
        env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"]
    ) as conn:
        name, schema = conn.execute(
            "SELECT current_database(),current_schema()"
        ).fetchone()
        if name != "garmin_test" or not schema.startswith("go_parity_"):
            raise ValueError("requires isolated schema")
        conn.execute("""INSERT INTO profile_versions(id,version,effective_at,timezone,cycle_anchor,anchor_confirmed,strength_days_confirmed,scheduled_strength_days,strength_schedule_mode,strength_week_a_start,strength_week_a_days,strength_week_b_days,mobility_week_a_days,mobility_week_b_days,mobility_optional_days,facts,preferences,unknowns)
            VALUES(gen_random_uuid(),1,'2026-03-01','America/New_York','2026-11-16',true,true,'[1,4]','alternating','2026-11-16','[1,4]','[0,3]','[3]','[1]','[6]','{}','{}','[]')""")
        for i, duration in enumerate([1200, 1800, 1800, 2100, 3000, 1800, 3600]):
            instant = NOW - timedelta(days=21 - 2 * i)
            conn.execute(
                """INSERT INTO activities(id,start_at,end_at,original_start,local_date,sport,canonical_revision,resolution_state,field_provenance,timer_s)
                    VALUES(gen_random_uuid(),%s,%s,'fixture',%s,'running',1,'resolved','{}',%s)""",
                (
                    instant,
                    instant + timedelta(seconds=duration),
                    instant.date(),
                    duration,
                ),
            )


def comparable(path, body):
    if "error" in body:
        body["error"].pop("request_id", None)
        return
    data = body["data"]
    if path == "/anchors":
        for r in data.get("items", [data]):
            r.pop("id", None)
    elif "preserved_session_uids" in data:
        data["preserved_session_uids"] = ["protected"] * len(
            data["preserved_session_uids"]
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
                    "^TestReferenceCalendarCommands$",
                    "./internal/calendarhttp",
                ],
                cwd=MODULE,
                env={**go, "CALENDAR_COMMAND_CASES": str(corpus)},
                check=True,
            )
            subprocess.run(["go","test","-count=1","./api/calendarwire"],cwd=MODULE,env={**go,"CALENDAR_WIRE_CASES":str(p/"wire.json")},check=True)
            query = """SELECT revision,calendar_version_number,deleted,local_date,slot,kind,recipe_id,custom,locked,legacy_unstructured,legacy_payload,placeholder,intent,certainty,planned_duration_s,planned_distance_m,structure,strength_slot_id,notes,brief FROM calendar_session_revisions ORDER BY calendar_version_number,local_date,slot,intent,revision"""

            def state(env):
                with psycopg.connect(
                    env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"]
                ) as conn:
                    return [
                        conn.execute(q).fetchall()
                        for q in [
                            query,
                            "SELECT data_revision,calendar_head_version FROM app_state",
                            "SELECT number,parent_number,kind,reason,restored_from_number,actor FROM calendar_versions ORDER BY number",
                            "SELECT kind,anchor_key,supersedes_key,value_low,valid_from,review_after FROM intensity_anchors ORDER BY anchor_key",
                        ]
                    ]

            assert state(ref) == state(go)
            print(
                f"Matched {len(json.loads(corpus.read_text()))} HTTP commands, revisions, head, dataset revision and anchor lineage."
            )


def reference(path):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import SessionLocal
    from app.services import calendar

    today = NOW.date()
    cases = []
    envelopes = []
    client = TestClient(app)
    roots = {
        "anchor_date": str(today),
        "start_date": str(today),
        "pattern": {"quality": 1, "long": 1},
    }

    def call(route, body=None, source=None):
        method = "GET" if body is None else "POST"
        res = client.request(
            method, "/api/v1" + route, json=body, headers={"X-Local-Request": "1"}
        )
        data = res.json()
        if route.startswith("/calendar/") and res.status_code == 201:
            envelopes.append({"path": route.removeprefix("/calendar"),"envelope":res.json()})
        comparable(route, data)
        if source:
            for edit in body["edits"]:
                if edit.get("session_uid") in source:
                    edit["session_uid"] = source[edit["session_uid"]]
        with SessionLocal() as session:
            undo = calendar.calendar_view(session, today, today)["undo"]
            if undo is not None:
                undo = {
                    **undo,
                    "protected_session_uids": ["protected"]
                    * len(undo["protected_session_uids"]),
                }
        cases.append(
            dict(
                path=route,
                body=body,
                method=method,
                status=res.status_code,
                expected=data,
                undo=undo,
            )
        )
        return res

    with patch.object(calendar, "calendar_today", return_value=today):
        assert (
            call(
                "/calendar/bootstrap", {**roots, "pattern": {"quality": 2}}
            ).status_code
            == 422
        )
        assert call("/calendar/bootstrap", roots).status_code == 201
        assert call("/calendar/bootstrap", roots).status_code == 409
        with psycopg.connect(
            os.environ["PROPOSAL_TEST_DATABASE_URL"], options=os.environ["PGOPTIONS"]
        ) as conn:
            uids = [
                str(row[0])
                for row in conn.execute(
                    "SELECT session_uid FROM calendar_session_revisions WHERE calendar_version_number=1 ORDER BY local_date,slot LIMIT 2"
                )
            ]
        labels = {u: f"slot:{i}" for i, u in enumerate(uids)}
        assert (
            call(
                "/calendar/edits",
                dict(
                    expected_head=1,
                    reason="Optional update",
                    edits=[
                        dict(
                            op="modify",
                            session_uid=uids[0],
                            fields={"intent": "Existing update", "locked": True},
                        ),
                        dict(
                            op="modify",
                            session_uid=uids[1],
                            fields={"intent": "Other update"},
                        ),
                    ],
                ),
                labels,
            ).status_code
            == 201
        )
        assert (
            call("/calendar/rollback", dict(expected_head=2, to_version=1)).status_code
            == 422
        )
        assert (
            call(
                "/calendar/rollback",
                dict(expected_head=2, to_version=1, reason="Restore eligible sessions"),
            ).status_code
            == 201
        )
        assert (
            call("/calendar/edits", dict(expected_head=1, edits=[])).status_code == 409
        )
        assert (
            call(
                "/calendar/edits",
                dict(expected_head=3, edits=[dict(op="delete", session_uid=uids[0])]),
                labels,
            ).status_code
            == 422
        )
        assert (
            call(
                "/calendar/edits",
                dict(
                    expected_head=3,
                    edits=[
                        dict(
                            op="add",
                            fields=dict(
                                local_date=str(today),
                                kind="rehab",
                                intent="Mobility",
                                planned_duration_s=1000,
                            ),
                        )
                    ],
                ),
            ).status_code
            == 422
        )
        assert (
            call(
                "/calendar/edits",
                dict(
                    expected_head=3,
                    edits=[
                        dict(
                            op="add",
                            fields=dict(
                                local_date=str(today), kind="rest", intent="Rest"
                            ),
                        )
                    ],
                ),
            ).status_code
            == 201
        )
        anchor = dict(
            kind="hr_threshold_lower",
            unit="bpm",
            protocol="manual",
            confidence="moderate",
            value_low=155,
            valid_from=str(today),
            calibrated_at=NOW.isoformat(),
        )
        assert call("/anchors", {**anchor, "value_low": 260}).status_code == 422
        assert call("/anchors", anchor).status_code == 200
        assert call("/anchors", anchor).status_code == 409
        assert (
            call(
                "/anchors",
                {
                    **anchor,
                    "value_low": 156,
                    "supersedes_key": "hr_threshold_lower-" + str(today),
                },
            ).status_code
            == 200
        )
        assert call("/anchors").status_code == 200
    Path(path).with_name("wire.json").write_text(json.dumps(envelopes))
    path.write_text(json.dumps(cases))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        reference(Path(sys.argv[2]))
    else:
        main()
