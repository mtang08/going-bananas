"""Synthetic API preservation checks; all writes roll back beneath one outer transaction."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.planning import router
from app.config import settings
from app.db import engine, get_session
from app.main import handle_http, handle_validation
from app.models import AppState, ProfileVersion
from app.planning_models import Block, BlockVersion, Event, Goal, StrengthRoutineSlot
from app.services.strength_routine import confirmed_schedule, routine_occurrences


@pytest.fixture
def planning_fixture():
    parsed = urlsplit(settings.database_url)
    assert settings.app_mode == 'test'
    assert parsed.hostname in {'127.0.0.1', 'localhost'} and parsed.port == 55439
    assert parsed.path == '/garmin_test'
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
                session.execute(delete(StrengthRoutineSlot))
                session.execute(delete(Goal))
                session.execute(delete(Event))
                session.execute(delete(BlockVersion))
                session.execute(delete(Block))
                state = session.get(AppState, 1)
                state.planning_authority = 'calendar'
                version = (session.scalar(select(func.max(ProfileVersion.version))) or 0) + 1
                profile = ProfileVersion(version=version,
                    effective_at=datetime(2026, 11, 1, tzinfo=UTC), timezone='America/New_York',
                    cycle_anchor=date(2026, 11, 2), anchor_confirmed=True,
                    strength_days_confirmed=True, scheduled_strength_days=[],
                    strength_schedule_mode='alternating', strength_week_a_start=date(2026, 11, 2),
                    strength_week_a_days=[0, 4], strength_week_b_days=[1, 5],
                    mobility_week_a_days=[2], mobility_week_b_days=[3], mobility_optional_days=[6],
                    facts={}, preferences={}, unknowns=[])
                session.add(profile)
                session.commit()
            api = FastAPI()
            api.include_router(router, prefix='/api/v1')
            api.add_exception_handler(HTTPException, handle_http)
            api.add_exception_handler(RequestValidationError, handle_validation)
            def override():
                with Session(bind=connection, join_transaction_mode='create_savepoint',
                             expire_on_commit=False) as session:
                    yield session
            api.dependency_overrides[get_session] = override
            yield TestClient(api), connection
        finally:
            transaction.rollback()


def test_routine_preserves_confirmed_schedule_and_versions(planning_fixture):
    client, connection = planning_fixture
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        schedule_before = confirmed_schedule(session)
        dates_before = [(row['date'], row['kind'], row['optional']) for row in
            routine_occurrences(session, date(2026, 11, 2), date(2026, 11, 15))]
    empty = client.get('/api/v1/strength-routine').json()['data']
    assert empty['version'] == 0 and empty['suggested'] is True
    slots = [
        {'label': 'A', 'default_weekday': 0, 'lower_body_cost': 'moderate',
         'typical_duration_s': 3600, 'main_lower_body_lifts': ['Squat']},
        {'label': 'B', 'default_weekday': 4, 'lower_body_cost': 'high',
         'typical_duration_s': 3300, 'main_lower_body_lifts': ['Deadlift']},
    ]
    created = client.put('/api/v1/strength-routine', json={'expected_version': 0, 'slots': slots})
    assert created.status_code == 200, created.text
    assert created.json()['data']['version'] == 1
    assert created.json()['data']['schedule'] == empty['schedule']
    assert client.put('/api/v1/strength-routine', json={'expected_version': 0, 'slots': slots}).status_code == 409
    slots[0]['label'] = 'A revised'
    revised = client.put('/api/v1/strength-routine', json={'expected_version': 1, 'slots': slots})
    assert revised.status_code == 200 and revised.json()['data']['version'] == 2
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        assert confirmed_schedule(session) == schedule_before
        assert [(row['date'], row['kind'], row['optional']) for row in
            routine_occurrences(session, date(2026, 11, 2), date(2026, 11, 15))] == dates_before
        assert session.scalar(select(func.count()).select_from(StrengthRoutineSlot).where(
            StrengthRoutineSlot.version == 1)) == 2
        assert session.scalar(select(func.count()).select_from(StrengthRoutineSlot).where(
            StrengthRoutineSlot.version == 2)) == 2
        assert session.scalar(select(func.count()).select_from(StrengthRoutineSlot).where(
            StrengthRoutineSlot.version == 1, StrengthRoutineSlot.active.is_(True))) == 2


def test_goal_event_block_routes_and_authority(planning_fixture):
    client, connection = planning_fixture
    assert client.get('/api/v1/blocks/active').json()['data'] is None
    assert client.get('/api/v1/goals').json()['data']['items'] == []
    created = client.post('/api/v1/goals', json={'text': 'Complete a 5K',
        'horizon': 'season', 'priority': 1})
    assert created.status_code == 201
    goal = created.json()['data']
    assert goal['status'] == 'active' and goal['version'] == 1
    assert client.patch(f"/api/v1/goals/{goal['id']}", json={'expected_version': 0,
        'status': 'paused'}).status_code == 422
    revised = client.patch(f"/api/v1/goals/{goal['id']}", json={'expected_version': 1,
        'status': 'paused'})
    assert revised.status_code == 200 and revised.json()['data']['version'] == 2
    assert client.patch(f"/api/v1/goals/{goal['id']}", json={'expected_version': 1,
        'status': 'done'}).status_code == 409
    event = client.post('/api/v1/events', json={'name': 'Fixture race',
        'event_date': '2026-12-06', 'distance_m': 5000, 'priority': 'target'})
    assert event.status_code == 201
    event_id = event.json()['data']['id']
    assert client.patch(f'/api/v1/events/{event_id}', json={'expected_version': 1,
        'status': 'registered'}).status_code == 200
    assert client.get('/api/v1/events').json()['data']['items'][0]['status'] == 'registered'
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        state = session.get(AppState, 1)
        state.planning_authority = 'legacy'
        session.commit()
    assert client.get('/api/v1/goals').status_code == 200
    assert client.post('/api/v1/goals', json={'text': 'Blocked', 'horizon': 'season',
        'priority': 1}).status_code == 409
    assert client.put('/api/v1/strength-routine', json={'expected_version': 2,
        'slots': [{'label': 'A', 'default_weekday': 0, 'lower_body_cost': 'low'}]}).status_code == 409


def test_block_active_uses_latest_version_and_history_is_ordered(planning_fixture):
    client, connection = planning_fixture
    block_uid = uuid.uuid4()
    def add_version(session, uid, version, status):
        session.add(BlockVersion(block_uid=uid, version=version, status=status,
            objective='Synthetic objective', rationale='Synthetic rationale',
            maintained_qualities=[], non_goals=[], eligible_recipe_ids=[],
            progression_dimension='none', constraints={}, start_date=date(2026, 11, 2),
            review_date=date(2026, 12, 2), completion_indicators=[], early_review_triggers=[],
            objective_status='unresolved'))
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        session.add(Block(block_uid=block_uid))
        session.flush()
        add_version(session, block_uid, 1, 'active')
        add_version(session, block_uid, 2, 'ended')
        session.commit()
    assert client.get('/api/v1/blocks/active').json()['data'] is None
    history = client.get(f'/api/v1/blocks/{block_uid}/history')
    assert history.status_code == 200
    assert [item['version'] for item in history.json()['data']['items']] == [1, 2]
    active_uid = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        session.add(Block(block_uid=active_uid))
        session.flush()
        add_version(session, active_uid, 1, 'active')
        session.commit()
    assert client.get('/api/v1/blocks/active').json()['data']['block_uid'] == str(active_uid)
