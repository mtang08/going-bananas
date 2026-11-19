"""Progression read model against seeded synthetic data."""
from __future__ import annotations

import argparse
import os
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import cli
from app.config import settings
from app.migrations_head import EXPECTED_HEAD
from app.models import Activity
from app.services import calendar
from app.services.timezone import athlete_tz, local_date
from app.services.workout_progression import linked_run_ids, progression_groups, workout_history

TODAY = date(2026, 11, 12)


@pytest.fixture
def demo(monkeypatch, tmp_path, capsys):
    url = os.environ['MIGRATION_TEST_DATABASE_URL']
    parsed = make_url(url)
    assert settings.app_mode == 'test'
    assert parsed.host in {'127.0.0.1', 'localhost'}
    assert parsed.port == int(os.environ.get('TEST_DATABASE_PORT', '55439'))
    assert parsed.database == 'mvp1_migration_test'
    engine = create_engine(url)
    schema = 'ti_prog_' + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        with engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            config = Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))
            config.attributes['connection'] = connection
            command.upgrade(config, EXPECTED_HEAD)
            connection.commit()
            sessions = sessionmaker(bind=connection, expire_on_commit=False)
            monkeypatch.setattr(cli, 'SessionLocal', sessions)
            monkeypatch.setattr(cli, 'settings', SimpleNamespace(app_mode='demo', private_dir=tmp_path))
            monkeypatch.setattr(cli, '_parse', lambda: argparse.Namespace(command='seed-demo'))
            monkeypatch.setattr(cli, 'local_date', lambda instant, zone: TODAY)
            monkeypatch.setattr(calendar, '_today', lambda session, now=None: TODAY)
            assert cli.main() == 0
            capsys.readouterr()
            yield sessions
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def activity_on(session, ago: int) -> Activity:
    day = TODAY - timedelta(days=ago)
    return next(a for a in session.scalars(select(Activity)) if local_date(a.start_at, athlete_tz(session)) == day)


def test_demo_progression_groups_and_history(demo):
    start = TODAY - timedelta(days=179)
    with demo() as session:
        groups = progression_groups(session, start, TODAY, 'signature')
        assert [g['group_key'] for g in groups] == ['sig:ws1:4xt300', 'sig:ws1:5xt240']
        other, = groups[1]['points']
        assert (other['status'], other['work_speed_mps'], other['work_hr_bpm'], other['work_m_per_beat'],
                other['recovery_s']) == ('available', 3.7, 163.0, 1.362, 480)
        group = groups[0]
        assert group['group_key'] == 'sig:ws1:4xt300'
        assert (group['sessions_total'], group['sessions_assessable']) == (4, 3)
        points = group['points']
        assert [p['status'] for p in points] == ['partial', 'available', 'not_assessable', 'available']
        partial = points[0]
        assert partial['n_completed'] == 3 and 'INCOMPLETE_WORK_STEPS' in partial['reason_codes']
        assert 'REPS_EXCLUDED' not in partial['reason_codes']
        assert (partial['work_speed_mps'], partial['work_hr_bpm'], partial['work_m_per_beat']) == (3.45, 160.0, 1.294)
        assert points[2]['reason_codes'] == ['WATCH_WORKOUT_MISMATCH']
        last = points[-1]
        assert (last['work_speed_mps'], last['work_hr_bpm'], last['work_m_per_beat']) == (3.55, 161.0, 1.323)
        assert (last['n_completed'], last['cv_speed'], last['last_first_change_pct']) == (4, 2.817, 0.0)
        assert last['target_coverage'] is None and last['recovery_s'] == 360
        assert (points[1]['work_speed_mps'], points[1]['work_hr_bpm'], points[1]['work_m_per_beat']) == (3.6, 158.0, 1.367)
        recipe = progression_groups(session, start, TODAY, 'recipe')
        assert len(recipe) == 1 and recipe[0]['group_key'] == 'recipe:REC003' and len(recipe[0]['points']) == 5
        assert recipe[0]['signatures'] == ['ws1:4xt300', 'ws1:5xt240']
        history = workout_history(session, activity_on(session, 6), 6)
        assert history['signature'] == 'ws1:4xt300' and history['reason'] is None
        dates = [(TODAY - timedelta(days=ago)).isoformat() for ago in (22, 14, 12, 6)]
        assert [p['local_date'] for p in history['points']] == dates
        assert [p['local_date'] for p in workout_history(session, activity_on(session, 6), 2)['points']] == dates[-2:]
        assert workout_history(session, activity_on(session, 8), 6)['reason'] == 'NO_STRUCTURED_PLAN'
        assert workout_history(session, activity_on(session, 28), 6)['reason'] == 'NO_PLAN_LINK'
        assert len(linked_run_ids(session, start, TODAY)) == 5


def test_progression_routes(demo):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from sqlalchemy import func

    from app.api.metrics import router, workout_progression_data
    from app.db import get_session
    from app.main import handle_http
    from app.metric_models import MetricResult

    app = FastAPI()
    app.include_router(router, prefix='/api/v1')
    app.add_exception_handler(HTTPException, handle_http)

    def override():
        with demo() as session:
            yield session

    app.dependency_overrides[get_session] = override
    client = TestClient(app)
    progression = '/api/v1/metrics/workout-progression'
    start = TODAY - timedelta(days=179)
    params = {'start': str(start), 'end': str(TODAY)}
    response = client.get(progression, params=params)
    assert response.status_code == 200
    data = response.json()['data']
    assert data['group_by'] == 'signature' and len(data['groups']) == 2
    recipe = client.get(progression, params={**params, 'group_by': 'recipe'})
    assert recipe.json()['data']['groups'][0]['group_key'] == 'recipe:REC003'
    assert client.get(progression, params={**params, 'group_by': 'week'}).status_code == 422
    for invalid_start in (TODAY + timedelta(days=1), TODAY - timedelta(days=366)):
        invalid = client.get(progression, params={**params, 'start': str(invalid_start)})
        assert invalid.status_code == 422 and invalid.json()['error']['code'] == 'invalid_date_window'

    with demo() as session:
        activity_id = activity_on(session, 6).id
        count = select(func.count()).select_from(MetricResult)
        before = session.scalar(count)
        for _ in range(2):
            workout_progression_data(session, start, TODAY, 'signature')
        assert session.scalar(count) == before
    url = f'/api/v1/activities/{activity_id}/workout-history'
    response = client.get(url)
    assert response.status_code == 200 and len(response.json()['data']['points']) == 4
    for limit in (1, 21):
        assert client.get(url, params={'limit': limit}).status_code == 422
    assert client.get(f'/api/v1/activities/{uuid.uuid4()}/workout-history').status_code == 404
