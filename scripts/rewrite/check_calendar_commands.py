"""Replay synthetic calendar commands against the Go API in a disposable schema."""

import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url
from test_proposal_slice import MODULE, ROOT, migrated_schema

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


# Request/response and resulting state captured with synthetic inputs at e5e565d.
CORPUS = MODULE / "internal/calendarhttp/testdata/commands.json"
STATE_QUERIES = {
    "session_revisions": """
        SELECT revision,calendar_version_number,deleted,local_date,slot,kind,recipe_id,custom,locked,
               legacy_unstructured,legacy_payload,placeholder,intent,certainty,planned_duration_s,
               planned_distance_m,structure,strength_slot_id,notes,brief
        FROM calendar_session_revisions
        ORDER BY calendar_version_number,local_date,slot,intent,revision
    """,
    "app_state": "SELECT data_revision,calendar_head_version FROM app_state",
    "calendar_versions": """
        SELECT number,parent_number,kind,reason,restored_from_number,actor
        FROM calendar_versions ORDER BY number
    """,
    "anchors": """
        SELECT kind,anchor_key,supersedes_key,value_low,valid_from,review_after
        FROM intensity_anchors ORDER BY anchor_key
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
                "^TestReferenceCalendarCommands$",
                "./internal/calendarhttp",
            ],
            cwd=MODULE,
            env={**env, "CALENDAR_COMMAND_CASES": str(CORPUS)},
            check=True,
        )
        subprocess.run(
            ["go", "test", "-count=1", "./api/calendarwire"],
            cwd=MODULE,
            env={
                **env,
                "CALENDAR_WIRE_CASES": str(
                    MODULE / "api/calendarwire/testdata/command_responses.json"
                ),
            },
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
    print(f"Matched {len(fixture['cases'])} calendar HTTP commands and stored state.")


if __name__ == "__main__":
    main()
