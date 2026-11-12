"""Calendar lineage and completion behavior on the guarded synthetic test database."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.api.calendar import get_completion_assessor, router
from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.coach_v2_models import CoachProposal, CoachSnapshot
from app.config import settings
from app.db import engine, get_session
from app.main import handle_http, handle_validation
from app.models import Activity, AppState, ProfileVersion
from app.services import calendar


def _headers():
    return {'X-Local-Request': '1', 'Origin': 'http://testserver'}


@pytest.fixture
def calendar_fixture(monkeypatch):
    # This service-seam suite invokes matching/its injected assessor explicitly.
    # Real transactional refresh is covered by test_metrics_flow.
    from app.metrics import engine as metric_engine
    monkeypatch.setattr(metric_engine, '_refresh_scopes', lambda session, scopes: [])
    parsed = urlsplit(settings.database_url)
    assert settings.app_mode == 'test'
    assert parsed.hostname in {'127.0.0.1', 'localhost'} and parsed.port == 55439
    assert parsed.path == '/garmin_test'
    monkeypatch.setattr(calendar, '_today', lambda session, now=None: date(2026, 11, 16))
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
                session.execute(delete(SessionCompletion))
                session.execute(delete(CalendarSessionRevision))
                session.execute(delete(CalendarVersion))
                state = session.get(AppState, 1)
                state.calendar_head_version = 0
                state.planning_authority = 'calendar'
                version = (session.scalar(select(func.max(ProfileVersion.version))) or 0) + 1
                session.add(ProfileVersion(version=version, effective_at=datetime(2026, 11, 1, tzinfo=UTC),
                    timezone='America/New_York', cycle_anchor=date(2026, 11, 2),
                    anchor_confirmed=True, strength_days_confirmed=True,
                    scheduled_strength_days=[0, 4], strength_schedule_mode='weekly',
                    facts={}, preferences={}, unknowns=[]))
                session.commit()
            api = FastAPI()
            api.include_router(router, prefix='/api/v1')
            api.add_exception_handler(HTTPException, handle_http)
            api.add_exception_handler(RequestValidationError, handle_validation)
            def override_session():
                with Session(bind=connection, join_transaction_mode='create_savepoint',
                             expire_on_commit=False) as session:
                    yield session
            def assessor():
                def assess(session, uid):
                    row = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == uid))
                    row.status = 'completed_modified'
                    row.version += 1
                return assess
            api.dependency_overrides[get_session] = override_session
            api.dependency_overrides[get_completion_assessor] = assessor
            yield TestClient(api), connection, api
        finally:
            outer.rollback()


def _bootstrap(client):
    response = client.post('/api/v1/calendar/bootstrap', json={
        'anchor_date': '2026-11-02', 'start_date': '2026-11-16',
        'pattern': {'quality': 1, 'long': 1}}, headers=_headers())
    assert response.status_code == 201, response.text
    return response.json()['data']


def test_bootstrap_move_old_view_stale_head_and_diff(calendar_fixture):
    client, connection, _ = calendar_fixture
    empty = client.get('/api/v1/calendar?start=2026-11-16&end=2026-11-29').json()['data']
    assert empty['head'] == 0 and empty['sessions'] == [] and empty['last_planned_date'] is None
    assert _bootstrap(client)['version'] == 1
    first = client.get('/api/v1/calendar?start=2026-11-16&end=2026-11-29').json()['data']
    runs = [item for item in first['sessions'] if item['kind'] == 'run']
    assert [item['local_date'] for item in runs] == [f'2026-11-{day}' for day in (16, 18, 20, 22, 24, 26, 28)]
    uid = runs[1]['session_uid']
    move = client.post('/api/v1/calendar/edits', json={'expected_head': 1,
        'edits': [{'op': 'move', 'session_uid': uid, 'fields': {'local_date': '2026-11-19'}}]},
        headers=_headers())
    assert move.status_code == 201, move.text
    assert move.json()['data']['version'] == 2
    old = client.get('/api/v1/calendar?start=2026-11-16&end=2026-11-29&version=1').json()['data']
    new = client.get('/api/v1/calendar?start=2026-11-16&end=2026-11-29').json()['data']
    assert next(item for item in old['sessions'] if item['session_uid'] == uid)['local_date'] == '2026-11-18'
    assert next(item for item in new['sessions'] if item['session_uid'] == uid)['local_date'] == '2026-11-19'
    assert new['last_planned_date'] == '2026-11-28'
    assert client.get('/api/v1/calendar?start=2026-11-16&end=2026-11-16').json()['data']['last_planned_date'] == '2026-11-28'
    changes = client.get('/api/v1/calendar/diff?from=1&to=2').json()['data']['changes']
    assert len(changes) == 1 and changes[0]['op'] == 'move' and changes[0]['session_uid'] == uid
    stale = client.post('/api/v1/calendar/edits', json={'expected_head': 1,
        'edits': [{'op': 'move', 'session_uid': uid, 'fields': {'local_date': '2026-11-20'}}]},
        headers=_headers())
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'calendar_head_moved'
    noop = client.post('/api/v1/calendar/edits', json={'expected_head': 2,
        'edits': [{'op': 'move', 'session_uid': uid, 'fields': {'local_date': '2026-11-19'}}]},
        headers=_headers())
    assert noop.status_code == 422 and noop.json()['error']['code'] == 'edit_no_change'
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        rows = session.scalars(select(CalendarSessionRevision).where(
            CalendarSessionRevision.session_uid == uuid.UUID(uid)).order_by(CalendarSessionRevision.revision)).all()
        assert len(rows) == 2 and rows[0].id != rows[1].id


def test_advisory_lock_refreshes_cached_head(calendar_fixture):
    _, connection, _ = calendar_fixture
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        cached = session.get(AppState, 1)
        assert cached.calendar_head_version == 0
        connection.execute(text('UPDATE app_state SET calendar_head_version=1 WHERE id=1'))
        with pytest.raises(HTTPException) as error:
            calendar._lock(session, expected_head=0)
        assert error.value.detail['code'] == 'calendar_head_moved'


def test_completion_assessed_after_flush_and_rollback_protects_link(calendar_fixture):
    client, connection, _ = calendar_fixture
    _bootstrap(client)
    first = client.get('/api/v1/calendar?start=2026-11-16&end=2026-11-29').json()['data']
    runs = [item for item in first['sessions'] if item['kind'] == 'run']
    linked_uid = runs[0]['session_uid']
    future_uid = runs[1]['session_uid']
    activity_id = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        session.add(Activity(id=activity_id, start_at=datetime(2026, 11, 16, 13, tzinfo=UTC),
            original_start='2026-11-16T13:00:00Z', local_date=date(2026, 11, 16),
            sport='running', canonical_revision=1, resolution_state='resolved', field_provenance={}))
        session.commit()
    linked = client.put(f'/api/v1/calendar/completions/{linked_uid}',
        json={'activity_id': str(activity_id)}, headers=_headers())
    assert linked.status_code == 200, linked.text
    assert linked.json()['data']['status'] == 'completed_modified'
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        stored = session.scalar(select(SessionCompletion).where(
            SessionCompletion.session_uid == uuid.UUID(linked_uid)))
        assert (stored.status, stored.version) == (linked.json()['data']['status'], linked.json()['data']['version'])
    assert client.put(f'/api/v1/calendar/completions/{future_uid}',
        json={'activity_id': str(activity_id)}, headers=_headers()).status_code == 409
    assert client.put(f'/api/v1/calendar/completions/{future_uid}',
        json={'status': 'completed_as_planned'}, headers=_headers()).status_code == 422
    assert client.put(f'/api/v1/calendar/completions/{future_uid}',
        json={'status': 'skipped'}, headers=_headers()).status_code == 200
    # A mixed rollback restores an unprotected future edit and preserves the linked run.
    move = client.post('/api/v1/calendar/edits', json={'expected_head': 1,
        'edits': [{'op': 'move', 'session_uid': runs[2]['session_uid'],
                   'fields': {'local_date': '2026-11-21'}}]}, headers=_headers())
    assert move.status_code == 201
    restored = client.post('/api/v1/calendar/rollback', json={'expected_head': 2,
        'to_version': 1, 'reason': 'restore synthetic fixture'}, headers=_headers())
    assert restored.status_code == 201, restored.text
    assert restored.json()['data']['version'] == 3
    assert client.get('/api/v1/calendar?start=2026-11-16&end=2026-11-29').json()['data']['head'] == 3


def test_demo_history_uuid_and_legacy_authority_guard(calendar_fixture):
    client, connection, _ = calendar_fixture
    past = client.post('/api/v1/calendar/bootstrap', json={'anchor_date': '2026-11-02',
        'start_date': '2026-11-15', 'pattern': {'quality': 1, 'long': 1}}, headers=_headers())
    assert past.status_code == 422 and past.json()['error']['code'] == 'protected_session'
    explicit = uuid.UUID('00000000-0000-4000-8000-000000000042')
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        result = calendar.seed_demo_calendar(session, anchor_date=date(2026, 11, 2),
            start_date=date(2026, 11, 16), now=datetime(2026, 11, 16, 17, tzinfo=UTC),
            history_edits=[{'op': 'add', 'session_uid': explicit, 'fields': {
                'local_date': date(2026, 11, 14), 'kind': 'run', 'recipe_id': 'REC003',
                'intent': 'Intervals', 'planned_duration_s': 60,
                'structure': [{'type': 'work', 'duration_type': 'time',
                               'duration_value': 60, 'target': None}]}}])
        assert result['version'] == 2
        assert explicit not in {item['session_uid'] for item in calendar.state_at(session, 1)}
        assert explicit in {item['session_uid'] for item in calendar.state_at(session, 2)}
        session.rollback()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        result = calendar.seed_demo_calendar(session, anchor_date=date(2026, 11, 2),
            start_date=date(2026, 11, 16), now=datetime(2026, 11, 16, 17, tzinfo=UTC),
            history_edits=[])
        assert result['version'] == 1
        assert session.scalar(select(func.count()).select_from(CalendarVersion)) == 1
        session.rollback()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        state = session.get(AppState, 1)
        state.planning_authority = 'legacy'
        session.flush()
        with pytest.raises(HTTPException) as error:
            calendar.write_bootstrap(session, date(2026, 11, 2), date(2026, 11, 16))
        assert error.value.status_code == 409
        session.rollback()


def test_rollback_keeps_deleted_historical_target_absent_and_restores_future(calendar_fixture):
    client, connection, _ = calendar_fixture
    historical_uid = uuid.UUID('00000000-0000-4000-8000-000000000042')
    with Session(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
        calendar.seed_demo_calendar(session, anchor_date=date(2026, 11, 2),
            start_date=date(2026, 11, 16), now=datetime(2026, 11, 16, 17, tzinfo=UTC),
            history_edits=[{'op': 'add', 'session_uid': historical_uid, 'fields': {
                'local_date': date(2026, 11, 14), 'kind': 'run', 'recipe_id': 'REC003',
                'intent': 'Historical fixture', 'planned_duration_s': 60}}])
        head2 = calendar._latest(session, 2)
        future = next(row for row in head2.values() if row.local_date == date(2026, 11, 18)
                      and row.kind == 'run')
        state = session.get(AppState, 1)
        state.calendar_head_version = 3
        session.add(CalendarVersion(number=3, parent_number=2, kind='manual_edit', actor='system'))
        session.flush()
        historical = head2[historical_uid]
        session.add(CalendarSessionRevision(session_uid=historical_uid, revision=2,
            calendar_version_number=3, deleted=True, certainty='committed',
            **calendar._fields(historical)))
        session.add(CalendarSessionRevision(session_uid=future.session_uid, revision=2,
            calendar_version_number=3, deleted=False, certainty='committed',
            **{**calendar._fields(future), 'local_date': date(2026, 11, 19)}))
        session.commit()
    restored = client.post('/api/v1/calendar/rollback', json={'expected_head': 3,
        'to_version': 2, 'reason': 'preserve historical deletion'}, headers=_headers())
    assert restored.status_code == 201, restored.text
    assert restored.json()['data']['preserved_session_uids'] == [str(historical_uid)]
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        current = {item['session_uid']: item for item in calendar.state_at(session, 4)}
        assert historical_uid not in current
        assert current[future.session_uid]['local_date'] == date(2026, 11, 18)
    protected_only = client.post('/api/v1/calendar/rollback', json={'expected_head': 4,
        'to_version': 2, 'reason': 'still historical'}, headers=_headers())
    assert protected_only.status_code == 422
    assert protected_only.json()['error']['code'] == 'rollback_no_change'


def test_assessor_unknown_is_valid_and_failed_commit_has_no_success(calendar_fixture, monkeypatch):
    client, connection, api = calendar_fixture
    _bootstrap(client)
    uid = next(item['session_uid'] for item in
        client.get('/api/v1/calendar?start=2026-11-16&end=2026-11-29').json()['data']['sessions']
        if item['kind'] == 'run')
    activity_id = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        session.add(Activity(id=activity_id, start_at=datetime(2026, 11, 16, 13, tzinfo=UTC),
            original_start='2026-11-16T13:00:00Z', local_date=date(2026, 11, 16),
            sport='running', canonical_revision=1, resolution_state='resolved', field_provenance={}))
        session.commit()
    def unknown_assessor():
        def assess(session, session_uid):
            row = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == session_uid))
            row.status = 'unknown'
        return assess
    api.dependency_overrides[get_completion_assessor] = unknown_assessor
    response = client.put(f'/api/v1/calendar/completions/{uid}',
        json={'activity_id': str(activity_id)}, headers=_headers())
    assert response.status_code == 200 and response.json()['data']['status'] == 'unknown'
    uid2 = next(item['session_uid'] for item in
        client.get('/api/v1/calendar?start=2026-11-16&end=2026-11-29').json()['data']['sessions']
        if item['kind'] == 'run' and item['session_uid'] != uid)
    original_commit = Session.commit
    def fail_commit(self):
        raise RuntimeError('synthetic commit failure')
    monkeypatch.setattr(Session, 'commit', fail_commit)
    try:
        with TestClient(api, raise_server_exceptions=False) as quiet_client:
            failed = quiet_client.put(f'/api/v1/calendar/completions/{uid2}',
                json={'status': 'skipped'}, headers=_headers())
        assert failed.status_code == 500
        assert 'session_uid' not in failed.text
    finally:
        monkeypatch.setattr(Session, 'commit', original_commit)
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        assert session.scalar(select(SessionCompletion).where(
            SessionCompletion.session_uid == uuid.UUID(uid2))) is None


def test_calendar_change_marks_pending_proposal_stale(calendar_fixture):
    client, connection, _ = calendar_fixture
    _bootstrap(client)
    proposal_id = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        snapshot = CoachSnapshot(operation='review_rolling_plan', as_of=date(2026, 11, 16),
            generated_at=datetime(2026, 11, 16, tzinfo=UTC), calendar_version_number=1,
            data_revision=0, payload={}, source_fingerprint='a'*64, source_versions={},
            kb_digest='b'*64, payload_sha256='c'*64, kb_package_version='fixture',
            kb_routes={}, approx_tokens=1)
        session.add(snapshot)
        session.flush()
        session.add(CoachProposal(id=proposal_id, operation='review_rolling_plan',
            snapshot_id=snapshot.id, base_calendar_version=1, status='pending',
            submitted_at=datetime(2026, 11, 16, tzinfo=UTC), summary='synthetic',
            rationale='synthetic', confidence={}, evidence_ids=[], policy_ids=[],
            recipe_ids=[], payload={}, skill_version='fixture', input_hash='d'*64))
        session.commit()
    uid = next(item['session_uid'] for item in
        client.get('/api/v1/calendar?start=2026-11-16&end=2026-11-29').json()['data']['sessions']
        if item['kind'] == 'run' and item['local_date'] == '2026-11-18')
    response = client.post('/api/v1/calendar/edits', json={'expected_head': 1,
        'edits': [{'op': 'move', 'session_uid': uid, 'fields': {'local_date': '2026-11-19'}}]},
        headers=_headers())
    assert response.status_code == 201
    assert response.json()['data']['stale_proposals'] == [str(proposal_id)]
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        assert session.get(CoachProposal, proposal_id).status == 'stale'
