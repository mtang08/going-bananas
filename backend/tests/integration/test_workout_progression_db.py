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
            monkeypatch.setattr(cli, '_parse', lambda: argparse.Namespace(command='seed-demo', calendar_preview=True))
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
        assert len(groups) == 1
        group = groups[0]
        assert group['group_key'] == 'sig:ws1:4xt300'
        assert (group['sessions_total'], group['sessions_assessable']) == (3, 2)
        points = group['points']
        assert [p['status'] for p in points] == ['available', 'not_assessable', 'available']
        assert points[1]['reason_codes'] == ['WATCH_WORKOUT_MISMATCH']
        last = points[2]
        assert (last['work_speed_mps'], last['work_hr_bpm'], last['work_m_per_beat']) == (3.55, 161.0, 1.323)
        assert (last['n_completed'], last['cv_speed'], last['last_first_change_pct']) == (4, 2.817, 0.0)
        assert last['target_coverage'] is None and last['recovery_s'] == 360
        assert (points[0]['work_speed_mps'], points[0]['work_hr_bpm'], points[0]['work_m_per_beat']) == (3.6, 158.0, 1.367)
        recipe = progression_groups(session, start, TODAY, 'recipe')
        assert len(recipe) == 1 and recipe[0]['group_key'] == 'recipe:REC003' and len(recipe[0]['points']) == 3
        history = workout_history(session, activity_on(session, 6), 6)
        assert history['signature'] == 'ws1:4xt300' and history['reason'] is None
        dates = [(TODAY - timedelta(days=ago)).isoformat() for ago in (14, 12, 6)]
        assert [p['local_date'] for p in history['points']] == dates
        assert [p['local_date'] for p in workout_history(session, activity_on(session, 6), 2)['points']] == dates[-2:]
        assert workout_history(session, activity_on(session, 8), 6)['reason'] == 'NO_STRUCTURED_PLAN'
        assert workout_history(session, activity_on(session, 28), 6)['reason'] == 'NO_PLAN_LINK'
        assert len(linked_run_ids(session, start, TODAY)) == 3
