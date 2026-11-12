"""Synthetic v2 check-in and guidance transactions under one outer rollback."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.checkins import router
from app.checkin_models import Checkin, CheckinRevision, SessionRpe, SymptomReport
from app.coach_v2_models import DailyGuidance
from app.config import settings
from app.db import engine, get_session
from app.main import handle_http, handle_validation
from app.metric_models import Prompt
from app.models import Activity, AppState, ProfileVersion


@pytest.fixture
def api_fixture():
    parsed = urlsplit(settings.database_url)
    assert settings.app_mode == 'test'
    assert parsed.hostname in {'127.0.0.1', 'localhost'} and parsed.port == 55439
    assert parsed.path == '/garmin_test'
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
                session.execute(delete(DailyGuidance))
                session.execute(delete(CheckinRevision))
                session.execute(delete(SymptomReport))
                session.execute(delete(Checkin))
                session.execute(delete(SessionRpe))
                session.execute(delete(Prompt))
                state = session.get(AppState, 1)
                state.planning_authority = 'calendar'
                version = (session.scalar(select(func.max(ProfileVersion.version))) or 0) + 1
                session.add(ProfileVersion(version=version, effective_at=datetime.now(UTC)-timedelta(days=365),
                    timezone='America/New_York', cycle_anchor=datetime.now(UTC).date(),
                    anchor_confirmed=True, strength_days_confirmed=True,
                    scheduled_strength_days=[0, 4], facts={}, preferences={}, unknowns=[]))
                session.commit()
            api = FastAPI()
            api.include_router(router, prefix='/api/v1')
            api.add_exception_handler(HTTPException, handle_http)
            api.add_exception_handler(RequestValidationError, handle_validation)
            def override():
                with Session(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
                    yield session
            api.dependency_overrides[get_session] = override
            yield TestClient(api), connection
        finally:
            outer.rollback()


def _observed():
    return datetime.now(UTC).astimezone(ZoneInfo('America/New_York')).replace(
        hour=9, minute=0, second=0, microsecond=0).isoformat()


def _body(**changes):
    value = {'idempotency_key': 'fixture-' + uuid.uuid4().hex,
        'kind': 'exception', 'observed_at': _observed(), 'fatigue': 7,
        'illness': None, 'gait_change': None, 'context_tags': [],
        'symptoms': [{'site': 'Achilles', 'side': 'left', 'severity': 3.0,
                      'timing': 'during'}], 'note': 'synthetic note'}
    value.update(changes)
    return value


def _activity(connection, sport='running'):
    activity_id = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        session.add(Activity(id=activity_id, start_at=datetime.now(UTC)-timedelta(hours=1),
            original_start=_observed(), local_date=datetime.now(UTC).astimezone(
            ZoneInfo('America/New_York')).date(), sport=sport,
            elapsed_s=1800, canonical_revision=1, resolution_state='resolved',
            field_provenance={}))
        session.commit()
    return activity_id


def test_create_replay_patch_snapshot_and_guidance_reload(api_fixture):
    client, connection = api_fixture
    assert client.get('/api/v1/coach/v2/daily').json()['data'] is None
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        assert session.scalar(select(func.count()).select_from(DailyGuidance)) == 0
    body = _body()
    created = client.post('/api/v1/v2/checkins', json=body)
    assert created.status_code == 201, created.text
    original = created.json()['data']
    assert original['daily_guidance']['decision'] == 'proceed'
    assert client.get('/api/v1/coach/v2/daily').json()['data']['id'] == original['daily_guidance']['id']
    replay = client.post('/api/v1/v2/checkins', json=body)
    assert replay.status_code == 200 and replay.json()['data']['id'] == original['id']
    changed = {**body, 'note': 'other synthetic note'}
    assert client.post('/api/v1/v2/checkins', json=changed).status_code == 409
    patch = client.patch(f"/api/v1/v2/checkins/{original['id']}", json={
        'expected_version': 1, 'note': None,
        'symptoms': [{'site': 'Achilles', 'side': 'left', 'severity': 3.1,
                      'timing': 'next_morning'}]})
    assert patch.status_code == 200, patch.text
    assert patch.json()['data']['version'] == 2
    assert patch.json()['data']['note'] is None
    assert client.patch(f"/api/v1/v2/checkins/{original['id']}", json={
        'expected_version': 1, 'fatigue': 6}).status_code == 409
    again = client.post('/api/v1/v2/checkins', json=body)
    assert again.status_code == 200 and again.json()['data'] == original
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        revision = session.scalar(select(CheckinRevision).where(CheckinRevision.checkin_id == uuid.UUID(original['id'])))
        assert revision.payload['symptoms'][0]['severity'] == 3.0
        assert revision.payload['note'] == 'synthetic note'
        assert session.scalar(select(func.count()).select_from(Checkin)) == 1


def test_expired_matching_prompt_answered_and_mismatch_rejected(api_fixture):
    client, connection = api_fixture
    activity_id = _activity(connection)
    other_id = _activity(connection)
    prompt_id = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        session.add(Prompt(id=prompt_id, kind='delayed_symptom', activity_id=activity_id,
            opens_at=datetime.now(UTC)-timedelta(days=2),
            closes_at=datetime.now(UTC)-timedelta(days=1), status='expired'))
        session.commit()
    body = _body(kind='delayed_followup', activity_id=str(other_id), prompt_id=str(prompt_id))
    mismatch = client.post('/api/v1/v2/checkins', json=body)
    assert mismatch.status_code == 422 and mismatch.json()['error']['code'] == 'prompt_subject_mismatch'
    cycling_id = _activity(connection, sport='cycling')
    assert client.post('/api/v1/v2/checkins', json=_body(kind='post_run',
        activity_id=str(cycling_id))).status_code == 422
    body['activity_id'] = str(activity_id)
    created = client.post('/api/v1/v2/checkins', json=body)
    assert created.status_code == 201, created.text
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        assert session.get(Prompt, prompt_id).status == 'answered'
    note_edit = client.patch(f"/api/v1/v2/checkins/{created.json()['data']['id']}",
        json={'expected_version': 1, 'note': 'updated'})
    assert note_edit.status_code == 200
    assert client.post(f'/api/v1/prompts/{prompt_id}/dismiss').status_code == 409
    rpe_prompt_id = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        session.add(Prompt(id=rpe_prompt_id, kind='rpe', activity_id=activity_id,
            opens_at=datetime.now(UTC)-timedelta(hours=1), status='open'))
        stale_open_id = uuid.uuid4()
        session.add(Prompt(id=stale_open_id, kind='missing_activity', session_uid=uuid.uuid4(),
            opens_at=datetime.now(UTC)-timedelta(days=2),
            closes_at=datetime.now(UTC)-timedelta(days=1), status='open'))
        session.commit()
    visible = client.get('/api/v1/prompts').json()['data']['items']
    assert str(rpe_prompt_id) in {item['id'] for item in visible}
    assert str(stale_open_id) not in {item['id'] for item in visible}
    post_run = _body(kind='post_run', activity_id=str(activity_id), prompt_id=str(rpe_prompt_id))
    assert client.post('/api/v1/v2/checkins', json=post_run).status_code == 422
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        assert session.get(Prompt, rpe_prompt_id).status == 'open'
        session.add(SessionRpe(activity_id=activity_id, rpe=7, source='manual',
            collected_at=datetime.now(UTC)))
        session.commit()
    assert client.post('/api/v1/v2/checkins', json=post_run).status_code == 201


def test_daily_request_is_idempotent_and_rpe_manual_wins(api_fixture):
    client, connection = api_fixture
    first = client.post('/api/v1/coach/v2/daily/request', json={})
    second = client.post('/api/v1/coach/v2/daily/request', json={})
    assert first.status_code == second.status_code == 200
    assert first.json()['data']['id'] == second.json()['data']['id']
    assert first.json()['data']['created_at'] == second.json()['data']['created_at']
    assert client.get('/api/v1/coach/v2/daily').json()['data']['id'] == first.json()['data']['id']
    activity_id = _activity(connection)
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        session.add(SessionRpe(activity_id=activity_id, rpe=6.5, source='garmin_fit',
            collected_at=datetime.now(UTC)))
        session.commit()
    manual = client.put(f'/api/v1/activities/{activity_id}/rpe', json={'rpe': 7})
    assert manual.status_code == 200 and manual.json()['data']['rpe'] == 7
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        rows = session.scalars(select(SessionRpe).where(SessionRpe.activity_id == activity_id)).all()
        assert {(row.source, row.rpe) for row in rows} == {('manual', 7), ('garmin_fit', 6.5)}
    assert client.put(f'/api/v1/activities/{activity_id}/rpe', json={'rpe': 7.11}).status_code == 422


def test_legacy_authority_blocks_new_writes_but_allows_reads(api_fixture):
    client, connection = api_fixture
    activity_id = _activity(connection)
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        session.get(AppState, 1).planning_authority = 'legacy'
        session.commit()
    assert client.get('/api/v1/v2/checkins').status_code == 200
    assert client.get('/api/v1/coach/v2/daily').status_code == 200
    assert client.post('/api/v1/v2/checkins', json=_body()).status_code == 409
    assert client.post('/api/v1/coach/v2/daily/request', json={}).status_code == 409
    assert client.put(f'/api/v1/activities/{activity_id}/rpe', json={'rpe': 7}).status_code == 409
