"""Shared activities reads in a disposable synthetic PostgreSQL schema."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.metrics.engine import load_runs
from app.models import Activity, ActivityAnnotation
from app.read.activities import eligible_runs

pytestmark = pytest.mark.integration


def _guard_url() -> str:
    url = os.environ.get("MIGRATION_TEST_DATABASE_URL", "")
    parsed = make_url(url)
    assert settings.app_mode == "test"
    assert parsed.drivername in ("postgresql+psycopg", "postgresql")
    assert parsed.host in ("localhost", "127.0.0.1")
    assert (
        parsed.port == int(os.environ.get("TEST_DATABASE_PORT", "55439")) and parsed.database == "mvp1_migration_test"
    )
    return url


@pytest.fixture
def db(metrics_disabled):
    engine = create_engine(_guard_url())
    schema = "read_activity_" + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        with engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.commit()
            yield sessionmaker(bind=connection, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def _activity(day: int, hour: int = 12, *, state: str = "resolved", sport: str = "running") -> Activity:
    start = datetime(2026, 11, day, hour, tzinfo=UTC)
    return Activity(
        start_at=start,
        original_start=start.isoformat(),
        local_date=date(2026, 11, day),
        sport=sport,
        timer_s=1800,
        distance_m=5000,
        resolution_state=state,
    )


def _seed(session) -> tuple[Activity, Activity, Activity]:
    first = _activity(19)
    excluded = _activity(20)
    late_utc = _activity(21, 3)
    session.add_all([first, excluded, late_utc, _activity(19, state="conflicted"), _activity(19, sport="cycling")])
    session.flush()
    session.add_all(
        [
            ActivityAnnotation(activity_id=excluded.id, version=1, excluded=False),
            ActivityAnnotation(activity_id=excluded.id, version=2, excluded=True),
        ]
    )
    session.flush()
    return first, excluded, late_utc


def test_eligible_runs_drops_unresolved_excluded_and_non_run(db):
    with db() as session:
        first, _, late_utc = _seed(session)
        assert [run.activity.id for run in eligible_runs(session)] == [first.id, late_utc.id]


def test_eligible_runs_bounds_use_athlete_local_date(db):
    with db() as session:
        first, _, late_utc = _seed(session)
        day_19, day_20, day_21 = (date(2026, 11, day) for day in (19, 20, 21))

        assert [run.activity.id for run in eligible_runs(session, day_20, day_21)] == [late_utc.id]
        assert [run.activity.id for run in eligible_runs(session, day_19, day_20)] == [first.id]
        assert [run.activity.id for run in eligible_runs(session, day_20)] == [late_utc.id]
        assert [run.activity.id for run in eligible_runs(session, end_date_excl=day_20)] == [first.id]


def test_eligible_runs_uses_latest_annotation(db):
    with db() as session:
        _, excluded, _ = _seed(session)
        assert excluded.id not in {run.activity.id for run in eligible_runs(session)}

        annotation = ActivityAnnotation(activity_id=excluded.id, version=3, excluded=False)
        session.add(annotation)
        session.flush()

        run = next(run for run in eligible_runs(session) if run.activity.id == excluded.id)
        assert run.annotation is annotation


def test_load_runs_without_bounds_matches_eligible_runs(db):
    with db() as session:
        _seed(session)

        assert {fact.activity_id for fact in load_runs(session)} == {run.activity.id for run in eligible_runs(session)}
