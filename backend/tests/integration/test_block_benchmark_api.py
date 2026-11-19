"""Benchmark status and manual matching on the guarded synthetic database."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.planning import router
from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.checkin_models import SessionRpe
from app.models import Activity, AppState
from app.planning_models import (
    Block,
    BlockBenchmarkResult,
    BlockDecision,
    BlockVersion,
    Event,
    Goal,
    IntensityAnchor,
    StrengthRoutineSlot,
)


@pytest.fixture
def bench_fixture(db_connection, metrics_disabled, session_factory, api_client, profile_factory, calendar_state):
    with session_factory() as session:
        for model in (BlockBenchmarkResult, SessionCompletion, CalendarSessionRevision, CalendarVersion,
                      SessionRpe, IntensityAnchor, StrengthRoutineSlot, Goal, Event, BlockDecision, BlockVersion, Block):
            session.execute(delete(model))
        calendar_state(session, reset_head=True)
        profile_factory(session, scheduled_strength_days=[], strength_schedule_mode='alternating',
                        strength_week_a_start=date(2026, 11, 2), strength_week_a_days=[0, 4],
                        strength_week_b_days=[1, 5], mobility_week_a_days=[2], mobility_week_b_days=[3],
                        mobility_optional_days=[6])
        session.commit()
    return api_client(router), db_connection


TZ = ZoneInfo('America/New_York')
H = {'X-Local-Request': '1', 'Origin': 'http://testserver'}


def today():
    return datetime.now(UTC).astimezone(TZ).date()


def tt(planned, distance=5000):
    return {'kind': 'time_trial', 'event_id': None, 'protocol': '5 km solo time trial', 'distance_m': distance,
            'planned_date': planned.isoformat(), 'progress_if': 'faster', 'consolidate_if': 'similar'}


def add_block(session, benchmark, review_date, block_uid=None):
    uid = block_uid or uuid.uuid4()
    session.add(Block(block_uid=uid))
    session.flush()
    session.add(BlockVersion(block_uid=uid, version=1, status='active', objective='Synthetic objective',
        rationale='Synthetic rationale', maintained_qualities=[], non_goals=[], eligible_recipe_ids=['REC009'],
        progression_dimension='none', constraints={}, start_date=review_date - timedelta(days=40),
        review_date=review_date, completion_indicators=[], early_review_triggers=[],
        objective_status='unresolved', benchmark=benchmark))
    session.flush()
    return uid


def add_rec009(session, uid, local_date, activity_id=None):
    if session.scalar(select(CalendarVersion).where(CalendarVersion.number == 1)) is None:
        session.add(CalendarVersion(number=1, kind='bootstrap', actor='system'))
        session.flush()
    session.add(CalendarSessionRevision(session_uid=uid, revision=1, calendar_version_number=1, local_date=local_date,
        kind='run', recipe_id='REC009', intent='5K time trial', certainty='committed'))
    session.get(AppState, 1).calendar_head_version = 1
    if activity_id is not None:
        session.add(SessionCompletion(session_uid=uid, activity_id=activity_id, status='completed_as_planned',
                                      match_method='explicit', updated_at=datetime.now(UTC)))
    session.flush()


def add_run(session, local_date, distance, timer, sport='running'):
    start = datetime.combine(local_date, time(8), TZ).astimezone(UTC)
    activity = Activity(id=uuid.uuid4(), start_at=start, end_at=start + timedelta(seconds=timer),
        original_start=start.isoformat(), local_date=local_date, sport=sport, elapsed_s=timer, timer_s=timer,
        distance_m=distance, canonical_revision=1, resolution_state='resolved', field_provenance={})
    session.add(activity)
    session.flush()
    return activity.id


def test_active_block_not_set_and_pending(bench_fixture):
    client, connection = bench_fixture
    d = today()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        add_block(session, None, d + timedelta(days=5))
        session.commit()
    data = client.get('/api/v1/blocks/active').json()['data']
    assert data['benchmark'] is None and data['benchmark_status']['status'] == 'not_set'
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        session.scalar(select(BlockVersion)).benchmark = tt(d + timedelta(days=3))
        add_rec009(session, uuid.uuid4(), d + timedelta(days=3))
        session.commit()
    status = client.get('/api/v1/blocks/active').json()['data']['benchmark_status']
    assert status['status'] == 'pending'
    assert status['scheduled_date'] == (d + timedelta(days=3)).isoformat()


def test_time_trial_auto_match_and_window(bench_fixture):
    client, connection = bench_fixture
    d = today()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        add_block(session, tt(d - timedelta(days=3)), d - timedelta(days=1))
        activity = add_run(session, d - timedelta(days=3), 5000.4, 1470.6)
        add_rec009(session, uuid.uuid4(), d - timedelta(days=3), activity)
        session.add(SessionRpe(activity_id=activity, source='manual', rpe=8, collected_at=datetime.now(UTC)))
        session.commit()
    status = client.get('/api/v1/blocks/active').json()['data']['benchmark_status']
    assert status['status'] == 'completed' and status['match_method'] == 'auto'
    assert status['activity_id'] == str(activity)
    assert status['distance_m'] == 5000 and status['result_s'] == 1471 and status['rpe'] == 8.0
    assert status['local_date'] == (d - timedelta(days=3)).isoformat()


def test_time_trial_outside_window_stays_pending(bench_fixture):
    client, connection = bench_fixture
    d = today()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        add_block(session, tt(d - timedelta(days=3)), d - timedelta(days=1))
        activity = add_run(session, d - timedelta(days=7), 5000, 1500)
        add_rec009(session, uuid.uuid4(), d - timedelta(days=7), activity)
        session.commit()
    assert client.get('/api/v1/blocks/active').json()['data']['benchmark_status']['status'] == 'pending'


def test_event_match_prefers_event_result_and_longest_run(bench_fixture):
    client, connection = bench_fixture
    d = today()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        event = Event(name='Synthetic 10K', event_date=d - timedelta(days=2), result_s=2400,
                      status='completed', priority='benchmark')
        session.add(event)
        session.flush()
        event_id = event.id
        spec = {'kind': 'event', 'event_id': str(event_id), 'protocol': 'Synthetic 10K race', 'distance_m': 10000,
                'planned_date': (d - timedelta(days=2)).isoformat(), 'progress_if': 'faster', 'consolidate_if': 'similar'}
        add_block(session, spec, d - timedelta(days=1))
        add_run(session, d - timedelta(days=2), 2000, 700)
        activity = add_run(session, d - timedelta(days=2), 10000, 2410)
        session.commit()
    status = client.get('/api/v1/blocks/active').json()['data']['benchmark_status']
    assert status['status'] == 'completed' and status['match_method'] == 'auto'
    assert status['activity_id'] == str(activity) and status['result_s'] == 2400
    assert status['event_id'] == str(event_id)


def test_missed_after_grace(bench_fixture):
    client, connection = bench_fixture
    d = today()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        add_block(session, tt(d - timedelta(days=4)), d - timedelta(days=3))
        session.commit()
    assert client.get('/api/v1/blocks/active').json()['data']['benchmark_status']['status'] == 'missed'
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        session.scalar(select(BlockVersion)).review_date = d - timedelta(days=2)
        session.commit()
    assert client.get('/api/v1/blocks/active').json()['data']['benchmark_status']['status'] == 'pending'


def test_manual_override_set_and_clear(bench_fixture):
    client, connection = bench_fixture
    d = today()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        uid = add_block(session, tt(d - timedelta(days=3)), d - timedelta(days=1))
        activity_a = add_run(session, d - timedelta(days=3), 5000.4, 1470.6)
        add_rec009(session, uuid.uuid4(), d - timedelta(days=3), activity_a)
        activity_b = add_run(session, d - timedelta(days=2), 5000, 1500)
        cycling = add_run(session, d - timedelta(days=2), 5000, 1500, sport='cycling')
        session.commit()
    before = client.get('/api/v1/blocks/active').json()['data_revision']
    response = client.put(f'/api/v1/blocks/{uid}/benchmark-activity', json={'activity_id': str(activity_b)}, headers=H)
    assert response.status_code == 200, response.text
    assert response.json()['data_revision'] > before
    status = response.json()['data']['benchmark_status']
    assert status['status'] == 'completed' and status['match_method'] == 'manual'
    assert status['activity_id'] == str(activity_b)
    response = client.put(f'/api/v1/blocks/{uid}/benchmark-activity', json={'activity_id': None}, headers=H)
    assert response.status_code == 200, response.text
    status = response.json()['data']['benchmark_status']
    assert status['match_method'] == 'auto' and status['activity_id'] == str(activity_a)
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        row = session.scalar(select(BlockBenchmarkResult))
        assert row.match_method == 'auto' and row.activity_id is None
        session.commit()
    for block_uid, activity_id, code in ((uuid.uuid4(), activity_b, 'block_not_found'),
                                         (uid, uuid.uuid4(), 'activity_not_found'),
                                         (uid, cycling, 'activity_not_found')):
        response = client.put(f'/api/v1/blocks/{block_uid}/benchmark-activity',
                              json={'activity_id': str(activity_id)}, headers=H)
        assert response.status_code == 404 and response.json()['error']['code'] == code
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        session.scalar(select(BlockVersion)).status = 'ended'
        uid = add_block(session, None, d + timedelta(days=5))
        session.commit()
    response = client.put(f'/api/v1/blocks/{uid}/benchmark-activity', json={'activity_id': str(activity_b)}, headers=H)
    assert response.status_code == 409 and response.json()['error']['code'] == 'benchmark_not_set'


def test_benchmark_history(bench_fixture):
    client, connection = bench_fixture
    d = today()
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        first = add_block(session, tt(d - timedelta(days=30)), d - timedelta(days=29))
        session.scalar(select(BlockVersion)).status = 'ended'
        second = add_block(session, tt(d + timedelta(days=3)), d + timedelta(days=5))
        session.add_all([
            BlockBenchmarkResult(block_uid=first, block_version=1, match_method='auto', protocol='5 km',
                                 outcome='progress', local_date=d - timedelta(days=30), result_s=1500, distance_m=5000),
            BlockBenchmarkResult(block_uid=second, block_version=1, match_method='auto', protocol='5 km', outcome=None),
        ])
        session.commit()
    items = client.get('/api/v1/blocks/benchmarks').json()['data']['items']
    assert len(items) == 1
    assert set(items[0]) == {'id', 'block_uid', 'block_version', 'objective', 'protocol', 'distance_m', 'local_date',
                             'result_s', 'outcome', 'compared_with', 'match_method', 'activity_id', 'event_id'}
    assert items[0]['objective'] == 'Synthetic objective'
