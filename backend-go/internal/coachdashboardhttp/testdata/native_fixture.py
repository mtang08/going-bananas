"""Keep a separately migrated synthetic schema alive while the HTTP test uses it."""

import os
import re
import sys
import tempfile
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

repo = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(repo / "scripts/rewrite"))
from test_proposal_slice import migrated_schema


def seed(conn, today):
    """A future 30-minute run plus the athlete's confirmed weekly strength days."""
    monday = today - timedelta(days=today.weekday())
    run = today + timedelta(days=2)
    while run.weekday() in (0, 4):
        run += timedelta(days=1)
    effective = datetime.combine(today - timedelta(days=1), time.min, UTC)
    conn.execute(
        """INSERT INTO profile_versions
               (id, version, effective_at, timezone, cycle_anchor, anchor_confirmed,
                strength_days_confirmed, scheduled_strength_days, facts, preferences, unknowns)
           VALUES (gen_random_uuid(), 1, %s, 'America/New_York', %s, true, true,
                   '[0,4]', '{}', '{}', '[]')""",
        (effective, monday),
    )
    conn.execute(
        """INSERT INTO calendar_versions (id, number, kind, actor, reason)
           VALUES (gen_random_uuid(), 1, 'manual_edit', 'user', 'Synthetic dashboard fixture')"""
    )
    upcoming = [monday + timedelta(days=n) for n in (0, 4, 7, 11, 14, 18)]
    days = [(day, "strength") for day in upcoming if day >= today][:4] + [(run, "run")]
    for day, kind in days:
        recipe, duration = ("REC001", 1800) if kind == "run" else (None, None)
        conn.execute(
            """INSERT INTO calendar_session_revisions
                   (id, session_uid, revision, calendar_version_number, local_date,
                    kind, intent, certainty, recipe_id, planned_duration_s)
               VALUES (gen_random_uuid(), gen_random_uuid(), 1, 1, %s, %s, 'Train',
                       'committed', %s, %s)""",
            (day, kind, recipe, duration),
        )
    conn.execute(
        "UPDATE app_state SET calendar_head_version=1, data_revision=1 WHERE id=1"
    )
    (schema,) = conn.execute("SELECT current_schema()").fetchone()
    return schema


def main():
    url = make_url(os.environ["DASHBOARD_TEST_DATABASE_URL"])
    assert (
        os.environ.get("APP_MODE") == "test"
        and url.database == "garmin_test"
        and url.host in {"127.0.0.1", "localhost"}
    )
    assert re.fullmatch(r"go_parity_[a-f0-9]{32}", url.query["search_path"])
    url = url.difference_update_query(["search_path"])
    with (
        psycopg.connect(
            url.render_as_string(hide_password=False), autocommit=True
        ) as db,
        tempfile.TemporaryDirectory(dir=repo / "private") as tmp,
        migrated_schema(
            db, url.set(drivername="postgresql+psycopg"), Path(tmp) / "app", "0"
        ) as env,
    ):
        with psycopg.connect(
            env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"]
        ) as fixture:
            schema = seed(fixture, date(2026, 11, 16))
        print(f"READY {schema}", flush=True)
        sys.stdin.read()


if __name__ == "__main__":
    main()
