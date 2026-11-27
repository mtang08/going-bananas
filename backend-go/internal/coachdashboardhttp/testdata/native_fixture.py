"""Keep a separately migrated synthetic schema alive while the HTTP test uses it."""

import os
import re
import sys
import tempfile
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

import psycopg
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

repo = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(repo / "backend"), str(repo / "scripts/rewrite")]
from app.models import ProfileVersion
from app.services import calendar
from test_proposal_slice import migrated_schema


def seed(engine, today):
    """A future 30-minute run plus the athlete's confirmed weekly strength days."""
    monday = today - timedelta(days=today.weekday())
    run = today + timedelta(days=2)
    while run.weekday() in (0, 4):
        run += timedelta(days=1)
    with (
        Session(engine) as session,
        patch.object(calendar, "calendar_today", lambda *_: today),
    ):
        session.add(
            ProfileVersion(
                version=1,
                effective_at=datetime.combine(today - timedelta(days=1), time.min, UTC),
                timezone="America/New_York",
                cycle_anchor=monday,
                anchor_confirmed=True,
                strength_days_confirmed=True,
                scheduled_strength_days=[0, 4],
                facts={},
                preferences={},
                unknowns=[],
            )
        )
        session.flush()
        upcoming = [monday + timedelta(days=n) for n in (0, 4, 7, 11, 14, 18)]
        days = [(day, "strength") for day in upcoming if day >= today][:4] + [
            (run, "run")
        ]
        changes = []
        for day, kind in days:
            fields = {"local_date": day, "kind": kind, "intent": "Train"}
            if kind == "run":
                fields.update(recipe_id="REC001", planned_duration_s=1800)
            changes.append({"op": "add", "fields": fields})
        calendar.apply_edits(session, 0, changes, "Synthetic dashboard fixture")
        schema = (
            session.connection().exec_driver_sql("select current_schema()").scalar_one()
        )
        session.commit()
        return schema


def main():
    url = make_url(os.environ["DASHBOARD_TEST_DATABASE_URL"])
    assert url.database == "garmin_test" and url.host in {"127.0.0.1", "localhost"}
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
        engine = create_engine(
            url.set(drivername="postgresql+psycopg"),
            connect_args={"options": env["PGOPTIONS"]},
        )
        schema = seed(engine, date(2026, 11, 16))
        engine.dispose()
        print(f"READY {schema}", flush=True)
        sys.stdin.read()


if __name__ == "__main__":
    main()
