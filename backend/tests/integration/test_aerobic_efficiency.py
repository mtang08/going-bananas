"""Aerobic efficiency results against seeded synthetic data."""
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
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import cli
from app.api.metrics import activity_execution, get_windows
from app.config import settings
from app.domain.local_time import date_in_zone
from app.metric_models import MetricResult
from app.metrics import aerobic, engine
from app.migrations_head import EXPECTED_HEAD
from app.models import Activity, ActivityAnnotation
from app.services import calendar
from app.services.timezone import athlete_tz

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
    schema = 'ti_aero_' + uuid.uuid4().hex
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
            monkeypatch.setattr(cli, 'date_in_zone', lambda instant, zone: TODAY)
            monkeypatch.setattr(calendar, 'calendar_today', lambda session, now=None: TODAY)
            assert cli.main() == 0
            capsys.readouterr()
            yield sessions
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def activity_on(session, ago: int) -> Activity:
    day = TODAY - timedelta(days=ago)
    return next(a for a in session.scalars(select(Activity)) if date_in_zone(a.start_at, athlete_tz(session)) == day)


def aero(session, ago: int):
    key = str(activity_on(session, ago).id)
    return engine.latest_results(session, aerobic.METRIC_ID, aerobic.METHOD_VERSION, [key])[key]


def test_demo_activity_results(demo):
    with demo() as session:
        easy = aero(session, 8)
        assert easy.status == 'available'
        assert easy.value['session_class'] == 'easy'
        assert easy.value['ef_m_per_beat'] == pytest.approx(1.183, abs=.002)
        assert easy.value['mean_hr_bpm'] == pytest.approx(142.0, abs=.05)
        assert easy.value['decoupling']['reason_codes'] == ['DECOUPLING_TOO_SHORT']
        assert easy.quality_flags == []
        assert easy.unit == 'm_per_beat'

        long = aero(session, 2)
        assert long.value['session_class'] == 'long'
        assert long.value['decoupling']['status'] == 'available'
        assert long.value['decoupling']['pct'] == pytest.approx(1.88, abs=.05)
        assert long.value['ef_m_per_beat'] == pytest.approx(1.187, abs=.002)
        assert aero(session, 1).value['ef_m_per_beat'] == pytest.approx(1.201, abs=.002)
        hill = aero(session, 26)
        assert 'HILLY_ROUTE' in hill.quality_flags
        assert hill.value['ef_m_per_beat'] == pytest.approx(1.14, abs=.002)

        assert aero(session, 28).value['session_class'] == 'unplanned'

        structured = aero(session, 6)
        assert structured.status == 'not_applicable'
        assert structured.reason_codes == ['STRUCTURED_SESSION']
        assert structured.value is None

        treadmill = aero(session, 20)
        assert treadmill.status == 'not_assessable'
        assert treadmill.reason_codes == ['SPEED_NOT_RECORDED']

        session.add(ActivityAnnotation(activity_id=activity_on(session, 8).id, version=1, excluded=True))
        session.commit()
        excluded = aero(session, 8)
        assert excluded.id != easy.id
        assert excluded.status == 'not_applicable'
        assert excluded.reason_codes == ['ACTIVITY_EXCLUDED']
        assert excluded.value is None


def test_demo_windows(demo):
    with demo() as session:
        short_key = f'w28:{TODAY}'
        long_key = f'w84:{TODAY}'
        rows = engine.latest_results(session, aerobic.METRIC_ID, aerobic.METHOD_VERSION, [short_key, long_key])

        row = rows[short_key]
        assert row.status in ('available', 'partial')
        value = row.value
        assert value['runs_total'] == 13
        assert value['runs_counted'] == 7
        assert value['not_counted'] == {'SPEED_NOT_RECORDED': 1, 'STRUCTURED_SESSION': 5}
        assert value['ef_early_median_m_per_beat'] == pytest.approx(1.144, abs=.002)
        assert value['ef_late_median_m_per_beat'] == pytest.approx(1.185, abs=.002)
        assert value['ef_change_pct'] == pytest.approx(3.58, abs=.05)
        assert value['decoupling_runs_counted'] == 1 and row.quality_flags == []
        assert rows[long_key].value['runs_counted'] == 8
        assert rows[long_key].value['window_days'] == 84
        assert rows[long_key].value['runs_total'] == 14
        with pytest.raises(ValueError, match='^invalid_subject_key$'):
            aerobic.compute(session, 'w7:2026-11-12')


def test_aerobic_reads(demo):
    with demo() as session:
        easy_id = activity_on(session, 8).id
        structured_id = activity_on(session, 6).id
        assert get_windows(TODAY, session)['data']['aerobic']['w28']['metric_id'] == 'aerobic_efficiency'
        assert activity_execution(session, easy_id)['aerobic']['value']['session_class'] == 'easy'
        assert activity_execution(session, structured_id)['aerobic']['reason_codes'] == ['STRUCTURED_SESSION']

        count = select(func.count()).select_from(MetricResult)
        before = session.scalar(count)
        get_windows(TODAY, session)
        activity_execution(session, easy_id)
        activity_execution(session, structured_id)
        assert session.scalar(count) == before
