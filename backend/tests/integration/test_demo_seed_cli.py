"""Calendar demo initialization on a freshly migrated synthetic schema."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import cli
from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.config import settings
from app.metric_models import MetricResult
from app.migrations_head import EXPECTED_HEAD
from app.models import Activity, AppState, ProfileVersion
from app.services import calendar
from app.services.calendar import state_at
from app.travel_models import GcalEvent, Trip


@pytest.fixture
def demo_cli(monkeypatch, tmp_path):
    url = os.environ["MIGRATION_TEST_DATABASE_URL"]
    parsed = make_url(url)
    assert settings.app_mode == "test"
    assert parsed.host in {"127.0.0.1", "localhost"}
    assert parsed.port == int(os.environ.get("TEST_DATABASE_PORT", "55439"))
    assert parsed.database == "mvp1_migration_test"
    engine = create_engine(url)
    schema = "demo_seed_" + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        with engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, EXPECTED_HEAD)
            connection.commit()
            sessions = sessionmaker(bind=connection, expire_on_commit=False)
            monkeypatch.setattr(cli, "SessionLocal", sessions)
            monkeypatch.setattr(cli, "settings", SimpleNamespace(app_mode="demo", private_dir=tmp_path))
            monkeypatch.setattr(cli, "_parse", lambda: argparse.Namespace(command="seed-demo"))
            yield sessions
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.mark.parametrize("weekday", range(7))
def test_calendar_preview_initializes_fresh_migrated_database(demo_cli, capsys, monkeypatch, weekday):
    today = date(2026, 11, 9) + timedelta(days=weekday)
    monkeypatch.setattr(cli, "date_in_zone", lambda instant, zone: today)
    monkeypatch.setattr(calendar, "calendar_today", lambda session, now=None: today)
    with demo_cli() as session:
        state = session.get(AppState, 1)
        assert (state.calendar_head_version, state.data_revision) == (0, 0)
    assert cli.main() == 0
    totals = json.loads(capsys.readouterr().out)
    assert totals["activities"] > 0 and totals["calendar_session_revisions"] > 0
    assert (totals["gcal_events"], totals["trips"], totals["trip_legs"]) == (7, 3, 4)
    with demo_cli() as session:
        state = session.get(AppState, 1)
        assert state.calendar_head_version > 0
        first = session.scalar(select(CalendarVersion).where(CalendarVersion.number == 1))
        assert first.kind == "bootstrap"
        assert session.scalar(select(func.count()).select_from(CalendarSessionRevision)) > 0
        rows = state_at(session, state.calendar_head_version)
        historical = next(
            row for row in rows if row["kind"] == "run" and row["local_date"] == today - timedelta(days=2)
        )
        assert historical["recipe_id"] == "REC002"
        activity = session.execute(
            select(Activity).where(Activity.local_date == today - timedelta(days=14))
        ).scalar_one()
        completion = session.execute(
            select(SessionCompletion).where(SessionCompletion.activity_id == activity.id)
        ).scalar_one()
        assert completion.status == "completed_as_planned"
        interval = session.execute(
            select(MetricResult).where(
                MetricResult.subject_key == str(activity.id),
                MetricResult.metric_id == "work_interval_execution",
                MetricResult.is_current.is_(True),
            )
        ).scalar_one()
        assert interval.value["n_completed"] == 4
        assert {"LAP_SPLIT_MERGED", "NONWORK_STEP_OMITTED"} <= set(interval.quality_flags)
        long_days = [row["local_date"] for row in rows if row["recipe_id"] == "REC002"]
        long_weeks = [day - timedelta(days=day.weekday()) for day in long_days]
        assert len(long_weeks) == len(set(long_weeks))
        current = next(row for row in rows if row["kind"] == "run" and row["local_date"] == today)
        if weekday in {5, 6}:
            assert current["recipe_id"] == "REC001"
        trips = {row.start_date: row for row in session.scalars(select(Trip))}
        upcoming = trips[today + timedelta(days=10)]
        assert (upcoming.status, upcoming.source, upcoming.end_date, upcoming.destination_tz, upcoming.confidence) == (
            "pending",
            "detected",
            today + timedelta(days=14),
            "America/Los_Angeles",
            "high",
        )
        past = trips[today - timedelta(days=20)]
        assert (past.status, past.end_date, past.destination_tz) == (
            "confirmed",
            today - timedelta(days=17),
            "America/Chicago",
        )
        manual = trips[today + timedelta(days=30)]
        assert (manual.source, manual.status, manual.confidence, manual.gym_access) == (
            "manual",
            "confirmed",
            None,
            "none",
        )
        assert manual.day_availability == [
            {"date": (today + timedelta(days=31)).isoformat(), "availability": "unavailable"}
        ]
        events = {row.google_event_id: row for row in session.scalars(select(GcalEvent))}
        assert {gid for gid, row in events.items() if row.category == "flight"} == {
            "demo-flight-past-out",
            "demo-flight-past-back",
            "demo-flight-out",
            "demo-flight-back",
        }
        assert events["demo-hotel"].category == "lodging"
        assert not events["demo-meeting"].busy and not events["demo-focus"].busy


@pytest.mark.parametrize("existing", ["profile", "activity"])
def test_calendar_preview_refuses_existing_legacy_data(demo_cli, capsys, existing):
    now = datetime.now(UTC)
    with demo_cli.begin() as session:
        if existing == "profile":
            session.add(ProfileVersion(version=1, effective_at=now, facts={"synthetic": True}))
        else:
            session.add(
                Activity(
                    start_at=now,
                    original_start=now.isoformat(),
                    local_date=now.date(),
                    sport="running",
                    field_provenance={},
                )
            )
    assert cli.main() == 2
    assert json.loads(capsys.readouterr().err)["error"] == "calendar_preview_requires_empty_database"
    with demo_cli() as session:
        state = session.get(AppState, 1)
        assert state.calendar_head_version == 0
        assert session.scalar(select(func.count()).select_from(ProfileVersion)) == (existing == "profile")
        assert session.scalar(select(func.count()).select_from(Activity)) == (existing == "activity")
        assert session.scalar(select(func.count()).select_from(CalendarVersion)) == 0
