"""Transactional matching regressions in a disposable synthetic PostgreSQL schema."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.config import settings
from app.models import Activity, AppState
from app.services.matching import rematch_dates


def _guard_url() -> str:
    url = os.environ.get("MIGRATION_TEST_DATABASE_URL", "")
    parsed = make_url(url)
    assert settings.app_mode == "test"
    assert parsed.drivername in ("postgresql+psycopg", "postgresql")
    assert parsed.host in ("localhost", "127.0.0.1")
    assert parsed.port == 55439 and parsed.database == "mvp1_migration_test"
    return url


@pytest.fixture
def db(monkeypatch):
    # This service-seam suite invokes matching/its injected assessor explicitly.
    # Real transactional refresh is covered by test_metrics_flow.
    from app.metrics import engine as metric_engine
    monkeypatch.setattr(metric_engine, '_refresh_scopes', lambda session, scopes: [])
    engine = create_engine(_guard_url())
    schema = "mvp025_" + uuid.uuid4().hex
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


def _activity(day: int, hour: int = 12, *, state: str = "resolved") -> Activity:
    start = datetime(2026, 11, day, hour, tzinfo=UTC)
    return Activity(start_at=start, original_start=start.isoformat(), local_date=date(2026, 11, day),
                    sport="running", timer_s=1800, distance_m=5000, resolution_state=state)


def _plan(day: int) -> CalendarSessionRevision:
    return CalendarSessionRevision(session_uid=uuid.uuid4(), revision=1, calendar_version_number=1,
                                   local_date=date(2026, 11, day), kind="run", slot=0,
                                   intent="synthetic", certainty="committed")


def _seed(session) -> None:
    state = session.get(AppState, 1)
    assert state is not None
    state.calendar_head_version = 1
    state.planning_authority = "calendar"
    session.add(CalendarVersion(number=1, kind="bootstrap", actor="system"))
    session.flush()


@pytest.mark.integration
def test_rematch_scope_preserves_far_auto_and_extra(db) -> None:
    with db() as session:
        _seed(session)
        near_plan, far_plan = _plan(19), _plan(27)
        near_run, far_run, far_extra = _activity(19), _activity(27), _activity(28)
        session.add_all([near_plan, far_plan, near_run, far_run, far_extra])
        session.flush()
        far_auto = SessionCompletion(session_uid=far_plan.session_uid, activity_id=far_run.id,
                                     status="completed_as_planned", match_method="auto_same_day",
                                     updated_at=datetime(2026, 11, 19, tzinfo=UTC))
        extra_uid = uuid.uuid4()
        extra = SessionCompletion(session_uid=extra_uid, activity_id=far_extra.id,
                                  status="extra", match_method="none",
                                  updated_at=datetime(2026, 11, 19, tzinfo=UTC))
        session.add_all([far_auto, extra])
        session.commit()
        affected = rematch_dates(session, {date(2026, 11, 19)})
        assert near_plan.session_uid in affected
        assert far_plan.session_uid not in affected and extra_uid not in affected
        assert session.scalar(select(SessionCompletion).where(
            SessionCompletion.session_uid == far_plan.session_uid)).activity_id == far_run.id
        assert session.scalar(select(SessionCompletion).where(
            SessionCompletion.session_uid == extra_uid)).status == "extra"
        session.rollback()
        assert session.scalar(select(SessionCompletion).where(
            SessionCompletion.session_uid == near_plan.session_uid)) is None


@pytest.mark.integration
def test_stale_auto_relinks_and_excluded_raw_subject_deletes(db) -> None:
    with db() as session:
        _seed(session)
        plan = _plan(19)
        old_run, new_run = _activity(20), _activity(19)
        session.add_all([plan, old_run, new_run])
        session.flush()
        session.add(SessionCompletion(session_uid=plan.session_uid, activity_id=old_run.id,
                                      status="completed_modified", match_method="auto_same_day",
                                      updated_at=datetime(2026, 11, 19, tzinfo=UTC)))
        session.commit()
        affected = rematch_dates(session, {date(2026, 11, 19)})
        assert plan.session_uid in affected
        linked = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == plan.session_uid))
        assert linked is not None and linked.activity_id == new_run.id
        session.commit()
        new_run.resolution_state = "pending"
        session.flush()
        affected = rematch_dates(session, {date(2026, 11, 19)})
        assert plan.session_uid in affected
        assert session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == plan.session_uid)) is None
        session.rollback()


@pytest.mark.integration
def test_extra_to_plan_fills_unknown_row_after_unique_release(db) -> None:
    with db() as session:
        _seed(session)
        plan, run = _plan(19), _activity(19)
        session.add_all([plan, run])
        session.flush()
        extra_uid = uuid.uuid4()
        session.add_all([
            SessionCompletion(session_uid=plan.session_uid, status="unknown", match_method="none",
                              updated_at=datetime(2026, 11, 19, tzinfo=UTC)),
            SessionCompletion(session_uid=extra_uid, activity_id=run.id, status="extra", match_method="none",
                              updated_at=datetime(2026, 11, 19, tzinfo=UTC)),
        ])
        session.commit()
        affected = rematch_dates(session, {date(2026, 11, 19)})
        assert affected == {plan.session_uid, extra_uid}
        filled = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == plan.session_uid))
        assert filled is not None and filled.activity_id == run.id
        assert filled.match_method == "auto_same_day" and filled.input_version == 2
        assert session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == extra_uid)) is None
        session.rollback()


@pytest.mark.integration
def test_noncontiguous_dates_preserve_middle_auto_and_extra(db) -> None:
    with db() as session:
        _seed(session)
        edge_a, middle, edge_b = _plan(19), _plan(23), _plan(27)
        middle_run, middle_extra = _activity(23), _activity(24)
        session.add_all([edge_a, middle, edge_b, middle_run, middle_extra])
        session.flush()
        extra_uid = uuid.uuid4()
        session.add_all([
            SessionCompletion(session_uid=middle.session_uid, activity_id=middle_run.id,
                              status="completed_as_planned", match_method="auto_same_day",
                              updated_at=datetime(2026, 11, 19, tzinfo=UTC)),
            SessionCompletion(session_uid=extra_uid, activity_id=middle_extra.id,
                              status="extra", match_method="none",
                              updated_at=datetime(2026, 11, 19, tzinfo=UTC)),
        ])
        session.commit()
        affected = rematch_dates(session, {date(2026, 11, 19), date(2026, 11, 27)})
        assert middle.session_uid not in affected and extra_uid not in affected
        assert session.scalar(select(SessionCompletion).where(
            SessionCompletion.session_uid == middle.session_uid)).activity_id == middle_run.id
        assert session.scalar(select(SessionCompletion).where(
            SessionCompletion.session_uid == extra_uid)).activity_id == middle_extra.id
        session.rollback()


@pytest.mark.integration
def test_historical_revision_before_bootstrap_origin_auto_links(db) -> None:
    with db() as session:
        _seed(session)
        state = session.get(AppState, 1)
        assert state is not None
        state.calendar_head_version = 2
        session.add(CalendarVersion(number=2, parent_number=1, kind="manual_edit", actor="system"))
        session.flush()
        future = _plan(19)
        historical = CalendarSessionRevision(session_uid=uuid.uuid4(), revision=1,
            calendar_version_number=2, local_date=date(2026, 11, 6), kind="run", slot=0,
            intent="historical synthetic run", certainty="committed")
        actual = _activity(6)
        session.add_all([future, historical, actual])
        session.flush()
        affected = rematch_dates(session, {date(2026, 11, 6)})
        assert historical.session_uid in affected
        linked = session.scalar(select(SessionCompletion).where(
            SessionCompletion.session_uid == historical.session_uid))
        assert linked is not None and linked.activity_id == actual.id
        assert linked.match_method == "auto_same_day"
        session.rollback()
