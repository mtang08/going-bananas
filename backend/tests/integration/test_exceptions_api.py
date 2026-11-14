"""Synthetic exception detector and API transactions under one outer rollback."""
from __future__ import annotations

import os
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.calendar import get_completion_assessor
from app.api.calendar import router as calendar_router
from app.api.checkins import router as checkins_router
from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.checkin_models import Checkin, CheckinRevision, SessionRpe, SymptomReport
from app.coach_v2_models import (
    CoachDecisionKey,
    CoachProposal,
    CoachProposalChange,
    CoachProposalRevision,
    CoachSnapshot,
    DailyGuidance,
)
from app.config import settings
from app.db import engine, get_session
from app.exception_models import ExceptionFinding, ExceptionPatch
from app.main import handle_http, handle_validation
from app.metric_models import Prompt
from app.models import AppState, ProfileVersion
from app.planning_models import Block, BlockBenchmarkResult, BlockDecision, BlockVersion, Event, IntensityAnchor
from app.services.exceptions.detector import run_detection
from app.services.exceptions.inputs import collect_detection_inputs
from app.services.exceptions.lifecycle import close_finding

NOW = datetime(2026, 11, 16, 17, tzinfo=UTC)
TODAY = date(2026, 11, 16)
DELETE_ORDER = (ExceptionFinding, ExceptionPatch, CoachDecisionKey, CoachProposalChange, CoachProposalRevision,
                CoachProposal, CoachSnapshot, DailyGuidance, CheckinRevision, SymptomReport, Checkin, SessionRpe, Prompt,
                SessionCompletion, CalendarSessionRevision, CalendarVersion, IntensityAnchor, BlockBenchmarkResult, Event,
                BlockDecision, BlockVersion, Block)


def local(days_ago, hour):
    return datetime.combine(TODAY - timedelta(days=days_ago), time(hour), ZoneInfo('America/New_York')).astimezone(UTC)


def checkin(observed_at, **fields):
    return Checkin(idempotency_key=uuid4().hex, kind='exception', observed_at=observed_at, context_tags=[], version=1,
                   schema_version=2, **fields)


def wire(result):
    return [r.to_wire() for r in result.review_recommended]


def findings(session, rule_code=None):
    query = select(ExceptionFinding).order_by(ExceptionFinding.first_seen_at, ExceptionFinding.id)
    if rule_code:
        query = query.where(ExceptionFinding.rule_code == rule_code)
    return session.scalars(query).all()


@pytest.fixture
def exc_fixture(monkeypatch):
    from app.metrics import engine as metric_engine
    monkeypatch.setattr(metric_engine, '_refresh_scopes', lambda session, scopes: [])
    parsed = urlsplit(settings.database_url)
    assert settings.app_mode == 'test'
    assert parsed.hostname in {'127.0.0.1', 'localhost'} and parsed.port == int(os.environ.get('TEST_DATABASE_PORT', '55439'))
    assert parsed.path == '/garmin_test'
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
                for model in DELETE_ORDER:
                    session.execute(delete(model))
                state = session.get(AppState, 1)
                state.planning_authority = 'calendar'
                state.calendar_head_version = 0
                version = (session.scalar(select(func.max(ProfileVersion.version))) or 0) + 1
                session.add(ProfileVersion(version=version, effective_at=datetime.now(UTC) - timedelta(days=365),
                    timezone='America/New_York', cycle_anchor=datetime.now(UTC).date(),
                    anchor_confirmed=True, strength_days_confirmed=True,
                    scheduled_strength_days=[0, 4], facts={}, preferences={}, unknowns=[]))
                session.commit()
            api = FastAPI()
            api.include_router(checkins_router, prefix='/api/v1')
            api.include_router(calendar_router, prefix='/api/v1')
            api.add_exception_handler(HTTPException, handle_http)
            api.add_exception_handler(RequestValidationError, handle_validation)
            def override():
                with Session(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
                    yield session
            api.dependency_overrides[get_session] = override
            api.dependency_overrides[get_completion_assessor] = lambda: (lambda session, uid: None)
            yield TestClient(api), connection
        finally:
            outer.rollback()


def test_detection_is_idempotent(exc_fixture):
    _, connection = exc_fixture
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        session.add(checkin(local(0, 8), fatigue=8.0))
        session.flush()
        first = run_detection(session, NOW)
        rows = findings(session)
        assert [(r.rule_code, r.entity_key, r.severity, r.status) for r in rows] == [
            ('FATIGUE_HIGH', 'fatigue', 'observe', 'open')]
        finding_id = rows[0].id
        assert first.new_finding_ids == (finding_id,)
        assert first.review_recommended == ()
        second = run_detection(session, NOW + timedelta(minutes=5))
        rows = findings(session)
        assert second.new_finding_ids == () and len(rows) == 1 and rows[0].id == finding_id
        assert rows[0].first_seen_at == NOW and rows[0].last_seen_at == NOW + timedelta(minutes=5)
        assert rows[0].version == 1


def test_severity_never_lowers(exc_fixture):
    _, connection = exc_fixture
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        row = checkin(local(0, 8))
        session.add(row)
        session.flush()
        symptom = SymptomReport(checkin_id=row.id, site='Achilles', side='left', severity=8.0, timing='during')
        session.add(symptom)
        session.flush()
        run_detection(session, NOW)
        finding = findings(session, 'SYM_NEW_SITE')[0]
        assert (finding.severity, finding.entity_key) == ('caution', 'site:achilles|left')
        symptom.severity = 2.0
        session.flush()
        run_detection(session, NOW + timedelta(minutes=1))
        assert finding.severity == 'caution' and finding.version == 1
        assert finding.summary == 'New symptom: Left achilles at 2/10.'


def test_terminal_blocks_old_evidence_only(exc_fixture):
    _, connection = exc_fixture
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        session.add(checkin(local(0, 8), fatigue=8.0))
        session.flush()
        run_detection(session, NOW)
        close_finding(findings(session, 'FATIGUE_HIGH')[0], 'dismissed', now=NOW)
        session.flush()
        assert run_detection(session, NOW + timedelta(minutes=1)).new_finding_ids == ()
        session.add(checkin(local(0, 13), fatigue=9.0))
        session.flush()
        result = run_detection(session, NOW + timedelta(hours=2))
        rows = findings(session, 'FATIGUE_HIGH')
        assert [r.status for r in rows] == ['dismissed', 'open']
        assert result.new_finding_ids == (rows[1].id,)


def test_collect_sessions_and_key_session_missed(exc_fixture):
    _, connection = exc_fixture
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        uid = uuid4()
        session.add(CalendarVersion(number=1, kind='bootstrap', actor='system', created_at=NOW - timedelta(days=10)))
        session.flush()
        session.add(CalendarSessionRevision(session_uid=uid, revision=1, calendar_version_number=1,
            local_date=TODAY - timedelta(days=2), kind='run', recipe_id='REC002', intent='Long aerobic run',
            certainty='committed'))
        session.get(AppState, 1).calendar_head_version = 1
        session.add(SessionCompletion(session_uid=uid, status='skipped', match_method='user_marked', updated_at=NOW))
        session.flush()
        inputs = collect_detection_inputs(session, NOW)
        assert inputs.today == TODAY and inputs.tz == 'America/New_York' and len(inputs.sessions) == 1
        row = inputs.sessions[0]
        assert (row.session_uid, row.session_class, row.expected_rpe, row.completion_status, row.certainty,
                row.planned_at, row.completion_updated_at) == (
            str(uid), 'long', (3.0, 5.0), 'skipped', 'committed', NOW - timedelta(days=10), NOW)
        run_detection(session, NOW)
        finding = findings(session, 'KEY_SESSION_MISSED')[0]
        assert finding.entity_key == f'session:{uid}' and finding.evidence_at == NOW
