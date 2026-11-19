"""Shared fixtures for PostgreSQL integration tests on the guarded synthetic `garmin_test` database.

Importing `app.main` installs the metric session listeners for API tests.
Every test runs inside one outer transaction that is rolled back; sessions use savepoints.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.coach_v2_models import CoachDecisionKey, CoachProposal, CoachProposalChange, CoachSnapshot
from app.config import settings
from app.db import engine, get_session
from app.exception_models import ExceptionFinding, ExceptionPatch
from app.main import handle_http, handle_validation
from app.models import AppState, ProfileVersion
from app.planning_models import Block, BlockBenchmarkResult, BlockDecision, BlockVersion, IntensityAnchor
from app.services import calendar


@pytest.fixture
def db_connection() -> Iterator[Connection]:
    parsed = urlsplit(settings.database_url)
    assert settings.app_mode == "test"
    assert parsed.hostname in {"127.0.0.1", "localhost"}
    assert parsed.port == int(os.environ.get("TEST_DATABASE_PORT", "55439"))
    assert parsed.path == "/garmin_test"
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            yield connection
        finally:
            outer.rollback()


@pytest.fixture
def session_factory(db_connection: Connection) -> Callable[..., Session]:
    def make(**options: Any) -> Session:
        return Session(bind=db_connection, join_transaction_mode="create_savepoint", **options)

    return make


@pytest.fixture
def api_client(session_factory: Callable[..., Session]) -> Callable[..., TestClient]:
    def make(*routers: APIRouter, overrides: dict[Any, Any] | None = None) -> TestClient:
        api = FastAPI()
        for router in routers:
            api.include_router(router, prefix="/api/v1")
        api.add_exception_handler(HTTPException, handle_http)
        api.add_exception_handler(RequestValidationError, handle_validation)

        def override_session() -> Iterator[Session]:
            with session_factory(expire_on_commit=False) as session:
                yield session

        api.dependency_overrides[get_session] = override_session
        api.dependency_overrides.update(overrides or {})
        return TestClient(api)

    return make


@pytest.fixture
def profile_factory() -> Callable[..., ProfileVersion]:
    def make(session: Session, **overrides: Any) -> ProfileVersion:
        fields: dict[str, Any] = {
            "version": (session.scalar(select(func.max(ProfileVersion.version))) or 0) + 1,
            "effective_at": datetime(2026, 11, 1, tzinfo=UTC),
            "timezone": "America/New_York",
            "cycle_anchor": date(2026, 11, 2),
            "anchor_confirmed": True,
            "strength_days_confirmed": True,
            "scheduled_strength_days": [0, 4],
            "strength_schedule_mode": "weekly",
            "facts": {},
            "preferences": {},
            "unknowns": [],
        }
        fields.update(overrides)
        profile = ProfileVersion(**fields)
        session.add(profile)
        return profile

    return make


@pytest.fixture
def calendar_state() -> Callable[..., AppState]:
    def apply(session: Session, *, reset_head: bool = False) -> AppState:
        """Put AppState in the calendar state the suites expect."""
        state = session.get(AppState, 1, with_for_update=True)
        assert state is not None
        if reset_head:
            state.calendar_head_version = 0
        return state

    return apply


@pytest.fixture
def metrics_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip transactional metric refresh for suites that call matching or assessors explicitly."""
    from app.services import derived

    monkeypatch.setattr(derived, "REFRESH_ENABLED", False)


PROPOSAL_NOW = datetime(2026, 11, 16, 15, tzinfo=UTC)
PROPOSAL_TODAY = date(2026, 11, 16)
PROPOSAL_CALENDAR = [(16, "strength"), (20, "strength"), (23, "strength"), (27, "strength"), (18, "run")]


@pytest.fixture
def proposal_session(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: Callable[..., Session],
    profile_factory: Callable[..., ProfileVersion],
    calendar_state: Callable[..., AppState],
) -> Iterator[Session]:
    """Clean proposal and calendar tables, one profile, and a five-session calendar (one run on 2026-11-18)."""
    monkeypatch.setattr(calendar, "calendar_today", lambda session, now=None: PROPOSAL_TODAY)
    with session_factory(expire_on_commit=False) as session:
        session.info["metrics_now"] = PROPOSAL_NOW
        for model in (
            ExceptionFinding,
            ExceptionPatch,
            BlockBenchmarkResult,
            CoachDecisionKey,
            CoachProposalChange,
            CoachProposal,
            CoachSnapshot,
            SessionCompletion,
            CalendarSessionRevision,
            CalendarVersion,
            BlockDecision,
            BlockVersion,
            Block,
            IntensityAnchor,
        ):
            session.execute(delete(model))
        calendar_state(session, reset_head=True)
        profile_factory(session, effective_at=PROPOSAL_NOW - timedelta(days=1), cycle_anchor=PROPOSAL_TODAY)
        session.flush()
        edits = [
            {
                "op": "add",
                "fields": {
                    "local_date": date(2026, 11, day),
                    "kind": kind,
                    "intent": "Train",
                    **({"recipe_id": "REC001", "planned_duration_s": 1800} if kind == "run" else {}),
                },
            }
            for day, kind in PROPOSAL_CALENDAR
        ]
        calendar.apply_edits(session, 0, edits, "Fixture")
        session.flush()
        session.commit()
        yield session
