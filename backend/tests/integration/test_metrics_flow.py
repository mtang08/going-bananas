"""Atomic training metric refresh against isolated, synthetic PostgreSQL schemas."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.metrics import activity_execution, current, explain_metric, get_windows, recovery_nights
from app.checkin_models import SessionRpe
from app.config import settings
from app.db import bump_data_revision, get_revision
from app.metric_models import MetricResult, Prompt
from app.metrics import engine
from app.models import Activity, AppState, CoverageInterval, ProfileVersion
from app.services.sync import import_activity_page

NOW = datetime(2025, 2, 2, 17, tzinfo=UTC)
TODAY = NOW.date()

def _guard_url() -> str:
    url = os.environ.get("MIGRATION_TEST_DATABASE_URL", "")
    parsed = make_url(url)
    assert settings.app_mode == "test"
    assert parsed.drivername in ("postgresql+psycopg", "postgresql")
    assert parsed.host in ("localhost", "127.0.0.1")
    assert parsed.port == 55439 and parsed.database == "mvp1_migration_test"
    return url


@pytest.fixture
def db():
    engine = create_engine(_guard_url())
    schema = "mvp030_" + uuid.uuid4().hex
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
            yield sessionmaker(bind=connection, expire_on_commit=False, autoflush=False)
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def seed(db, tmp_path):
    engine.install_triggers()
    engine.install_triggers()
    with db() as session:
        session.info['metrics_now'] = NOW
        session.add(ProfileVersion(version=1, effective_at=NOW, timezone='America/New_York', facts={}, preferences={}, unknowns=[]))
        records = []
        for index, (day, timer, distance) in enumerate([(27,1800,5000),(29,2400,6500),(31,2100,6000),(2,3600,10000)]):
            stamp = datetime(2025, 2 if day == 2 else 1, day, 12, tzinfo=UTC)
            records.append({'activityId': 3000+index, 'startTimeGMT': stamp.isoformat(),
                'activityType': {'typeKey': 'running'}, 'duration': timer, 'distance': distance})
        import_activity_page(session, tmp_path, records, account_scope='synthetic-metrics', source_kind='demo_fixture')
        runs = list(session.scalars(select(Activity).order_by(Activity.start_at)))
        for row, timer in zip(runs, [1800,2400,2100,3600], strict=True):
            row.timer_s = timer
            row.end_at = row.start_at + timedelta(seconds=timer)
        session.add(CoverageInterval(dataset='activities', start_date=date(2025,1,20), end_date=TODAY,
            status='complete', fully_enumerated=True, completed_at=NOW))
        session.add_all([SessionRpe(activity_id=runs[1].id, rpe=6, source='garmin_fit', collected_at=NOW),
                         SessionRpe(activity_id=runs[3].id, rpe=5, source='manual', collected_at=NOW)])
        session.commit()
        state = session.get(AppState, 1)
        state.planning_authority = 'calendar'
        session.commit()
        return [row.id for row in runs]


def counts(session):
    return tuple(session.scalar(select(func.count()).select_from(model)) for model in (MetricResult, Prompt))


def test_four_runs_idempotent_reads_and_explanation(db, tmp_path):
    ids = seed(db, tmp_path)
    with db() as session:
        session.info['metrics_now'] = NOW
        revision = get_revision(session)
        data = get_windows(TODAY, session)['data']
        volume = data['windows'][0]['volume']
        assert volume['value']['timer_duration_s'] == 9900
        assert volume['value']['distance_m'] == 27500
        assert volume['value']['run_count'] == 4
        rpe = data['windows'][0]['srpe']['value']
        assert rpe['load_au'] == 540
        assert rpe['coverage_duration'] == .606
        assert rpe['coverage_sessions'] == .5
        before = counts(session)
        get_windows(TODAY, session)
        get_windows(TODAY, session)
        assert counts(session) == before
        assert get_revision(session) == revision
        assert explain_metric(session, volume['id'])['value'] == volume['value']
        detail = activity_execution(session, ids[-1])
        assert detail['rpe']['effective'] == 5
        assert detail['rpe']['srpe_load_au'] == 300
        assert set(detail) == {'activity','planned','completion','laps','watch_steps','planned_actual','intervals','intensity','rpe','symptoms'}
        nights = recovery_nights(session, TODAY-timedelta(days=2), TODAY)
        assert len(nights['nights']) == 3
        assert all(night['hrv']['value'] is None for night in nights['nights'])


def test_source_refresh_history_and_rollback(db, tmp_path):
    ids = seed(db, tmp_path)
    with db() as session:
        session.info['metrics_now'] = NOW
        get_windows(TODAY, session)
        before = get_revision(session)
        old = current(session, 'run_volume_frequency', f'w7:{TODAY}')
        old_id = old.id
        row = session.get(Activity, ids[0])
        row.timer_s = 1900
        bump_data_revision(session)
        bump_data_revision(session)
        session.commit()
        assert get_revision(session) == before+1
        fresh = current(session, 'run_volume_frequency', f'w7:{TODAY}')
        assert fresh.value['timer_duration_s'] == 10000
        assert fresh.id != old_id
        assert explain_metric(session, old_id)['value']['timer_duration_s'] == 9900
        baseline = counts(session)
        row.timer_s = 9000
        session.flush()
        session.rollback()
        assert session.get(Activity, ids[0]).timer_s == 1900
        assert counts(session) == baseline
        assert not session.info.get('metrics_scopes')
        assert get_revision(session) == before+1
        session.get(Activity, ids[0]).timer_s = 1800
        session.commit()
        assert get_revision(session) == before+2
        assert current(session, 'run_volume_frequency', f'w7:{TODAY}').value['timer_duration_s'] == 9900


def test_revision_nested_and_legacy(db):
    with db() as session:
        before = get_revision(session)
        assert bump_data_revision(session) == before+1
        assert bump_data_revision(session) == before+2
        session.commit()
        session.get(AppState, 1).planning_authority = 'calendar'
        session.commit()
        before = get_revision(session)
        savepoint = session.begin_nested()
        assert bump_data_revision(session) == before+1
        savepoint.rollback()
        assert get_revision(session) == before
        assert bump_data_revision(session) == before+1
        savepoint = session.begin_nested()
        assert bump_data_revision(session) == before+1
        savepoint.rollback()
        assert bump_data_revision(session) == before+1
        session.commit()
        assert bump_data_revision(session) == before+2
        session.rollback()
        assert bump_data_revision(session) == before+2
        session.commit()


@pytest.mark.parametrize('method', ['explicit', 'auto_same_day', 'confirmed_move'])
def test_every_link_writeback(db, tmp_path, method):
    from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
    ids = seed(db, tmp_path)
    uid = uuid.uuid4()
    with db() as session:
        session.info['metrics_now'] = NOW
        session.get(AppState, 1).calendar_head_version = 1
        session.add(CalendarVersion(number=1, kind='bootstrap', actor='system'))
        session.flush()
        session.add(CalendarSessionRevision(session_uid=uid, revision=1, calendar_version_number=1,
            local_date=TODAY, kind='run', intent='Test run', planned_duration_s=3000, certainty='committed'))
        completion = SessionCompletion(session_uid=uid, activity_id=ids[-1], status='unknown', match_method=method,
            modification_reason='symptom_onset', version=1, input_version=1, updated_at=NOW)
        session.add(completion)
        session.get(Activity, ids[-1]).timer_s = 2820
        session.commit()
        expected = 'moved' if method == 'confirmed_move' else 'completed_modified'
        assert completion.status == expected
        output = activity_execution(session, ids[-1])
        assert output['planned_actual']['value']['overall_status'] == expected
        assert output['completion']['status'] == expected
        assert completion.match_method == method
        version = completion.version
        baseline = counts(session)
        activity_execution(session, ids[-1])
        assert completion.version == version
        assert counts(session) == baseline
        completion.modification_reason = None
        completion.input_version += 1
        session.get(Activity, ids[-1]).timer_s = 1500
        session.commit()
        # A shorter unstructured run is modified; partial requires unfinished prescribed steps.
        assert completion.status == ('moved' if method == 'confirmed_move' else 'completed_modified')
        assert completion.match_method == method


def test_derived_failure_rolls_back_source_and_revision(db, tmp_path, monkeypatch):
    ids = seed(db, tmp_path)
    with db() as session:
        session.info['metrics_now'] = NOW
        get_windows(TODAY, session)
        before = counts(session)
        revision = get_revision(session)
        session.get(Activity, ids[0]).timer_s = 9999
        def fail_refresh(*args):
            raise RuntimeError('synthetic calculation failure')
        monkeypatch.setattr(engine, '_refresh_scopes', fail_refresh)
        with pytest.raises(RuntimeError, match='synthetic calculation'):
            session.commit()
        session.rollback()
        assert session.get(Activity, ids[0]).timer_s == 1800
        assert counts(session) == before
        assert get_revision(session) == revision
        assert not session.info.get('metrics_running')
        assert not session.info.get('metrics_scopes')


def test_http_routes_and_bounds(db, tmp_path):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from app.api.metrics import router
    from app.db import get_session
    from app.main import app as production_app
    from app.main import handle_http
    ids = seed(db, tmp_path)
    api = FastAPI()
    api.include_router(router, prefix='/api/v1')
    api.add_exception_handler(HTTPException, handle_http)
    def override():
        with db() as session:
            session.info['metrics_now'] = NOW
            yield session
    api.dependency_overrides[get_session] = override
    client = TestClient(api)
    response = client.get('/api/v1/metrics/windows')
    assert response.status_code == 200
    assert len(response.json()['data']['windows']) == 4
    assert client.get(f'/api/v1/activities/{ids[0]}/execution').status_code == 200
    assert client.get(f'/api/v1/activities/{uuid.uuid4()}/execution').status_code == 404
    assert client.get(f'/api/v1/metrics/explain/{uuid.uuid4()}').status_code == 404
    assert client.get('/api/v1/metrics/recovery?start=2025-01-01&end=2025-04-03').status_code == 422
    assert client.get('/api/v1/metrics/recovery?start=2025-02-01&end=2025-01-01').status_code == 422
    paths = set(production_app.openapi()['paths'])
    assert {'/api/v1/metrics/windows', '/api/v1/v2/checkins', '/api/v1/coach/v2/daily',
            '/api/v1/activities', '/api/v1/anchors'} <= paths


def test_trace_and_anchor_history(db, tmp_path):
    from app.fit_models import ActivityStream
    from app.metrics.anchors import create_anchor
    ids = seed(db, tmp_path)
    with db() as session:
        session.info['metrics_now'] = NOW
        for kind, value in [('hr_aerobic_upper',150), ('hr_threshold_lower',170)]:
            create_anchor(session, {'kind': kind, 'value_low': value, 'unit': 'bpm', 'protocol': 'manual',
                'confidence': 'high', 'calibrated_at': datetime(2025,1,1,tzinfo=UTC), 'valid_from': date(2025,1,1)})
        stream = ActivityStream(activity_id=ids[-1], t_s=list(range(3601)),
            hr_bpm=[140]*3000+[165]*601, speed_mps=[None]*3601, distance_m=[None]*3601,
            altitude_m=[None]*3601, cadence=[None]*3601, timer_on=[[0,3600]], sample_count=3601,
            max_gap_s=1, quality_flags=[])
        session.add(stream)
        session.commit()
        metric = activity_execution(session, ids[-1])['intensity']
        assert metric['value']['hr']['easy_s'] == 3000
        assert metric['value']['hr']['moderate_s'] == 600
        assert metric['value']['hr']['high_s'] == 0
        assert metric['value']['hr']['coverage'] == 1
        assert metric['value']['speed']['status'] == 'not_assessable'
        assert metric['value']['speed']['easy_s'] is None
        old_id = metric['id']
        stream.hr_bpm = [140]*3601
        session.commit()
        fresh = activity_execution(session, ids[-1])['intensity']
        assert fresh['id'] != old_id
        assert fresh['value']['hr']['easy_s'] == 3600
        assert explain_metric(session, old_id)['value']['hr']['moderate_s'] == 600
        count = counts(session)
        activity_execution(session, ids[-1])
        assert counts(session) == count


def test_recovery_correction_preserves_prior_explanation(db, tmp_path):
    from app.models import RecoveryObservation, SourceRecord
    ids = seed(db, tmp_path)
    with db() as session:
        session.info['metrics_now'] = NOW
        account = session.get(Activity, ids[0]).source_account_id
        source = session.scalar(select(SourceRecord).where(SourceRecord.source_account_id == account))
        source.fields = {**source.fields, 'device_generation': 'synthetic'}
        observations = []
        for index in range(31):
            row = RecoveryObservation(source_account_id=account, source_record_id=source.id,
                metric='hrv', source_date=TODAY-timedelta(days=30-index), time_semantics='night',
                value=(60 if index < 15 else 70) if index < 30 else 50, unit='ms', statistic='nightly_mean',
                source_revision=str(index))
            observations.append(row)
            session.add(row)
        session.commit()
        old = current(session, 'recovery_multisignal_summary', f'night:{TODAY}')
        assert old.value['hrv']['z'] == -2.27
        assert old.value['hrv']['baseline_state'] == 'established'
        old_id = old.id
        observations[0].value = 70
        observations[0].source_revision = 'corrected'
        session.commit()
        fresh = current(session, 'recovery_multisignal_summary', f'night:{TODAY}')
        assert fresh.id != old_id
        assert explain_metric(session, old_id)['value']['hrv']['z'] == -2.27
        assert fresh.value['hrv']['baseline_median'] == pytest.approx(4.248, abs=.001)


def test_old_new_activity_date_invalidation(db, tmp_path):
    from app.models import ActivityAnnotation
    ids = seed(db, tmp_path)
    with db() as session:
        session.info['metrics_now'] = NOW
        get_windows(TODAY, session)
        activity = session.get(Activity, ids[0])
        activity.start_at -= timedelta(days=10)
        activity.end_at -= timedelta(days=10)
        activity.local_date -= timedelta(days=10)
        session.commit()
        assert current(session, 'run_volume_frequency', f'w7:{TODAY}').value['run_count'] == 3
        session.add(ActivityAnnotation(activity_id=ids[-1], version=1, excluded=True))
        session.commit()
        assert current(session, 'run_volume_frequency', f'w7:{TODAY}').value['run_count'] == 2
        assert current(session, 'intensity_time_distribution', str(ids[-1])).status == 'not_applicable'


def test_serialized_writers_keep_both_changes(db, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from sqlalchemy.orm import Session
    ids = seed(db, tmp_path)
    bound = db.kw['bind']
    schema = bound.scalar(text('SELECT current_schema()'))
    bound.commit()
    waiting = Event()
    def second_writer():
        with bound.engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            with Session(bind=connection, autoflush=False, expire_on_commit=False) as second:
                second.info['metrics_now'] = NOW
                waiting.set()
                second.execute(text('SELECT pg_advisory_xact_lock(71382413)'))
                second.get(Activity, ids[1]).timer_s += 20
                second.commit()
    with db() as first, ThreadPoolExecutor(max_workers=1) as pool:
        first.info['metrics_now'] = NOW
        first.execute(text('SELECT pg_advisory_xact_lock(71382413)'))
        revision = get_revision(first)
        first.get(Activity, ids[0]).timer_s += 100
        future = pool.submit(second_writer)
        assert waiting.wait(5)
        first.commit()
        future.result(timeout=20)
    with db() as session:
        assert get_revision(session) == revision+2
        assert session.get(Activity, ids[0]).timer_s == 1900
        assert session.get(Activity, ids[1]).timer_s == 2420
        assert current(session, 'run_volume_frequency', f'w7:{TODAY}').value['timer_duration_s'] == 10020


def test_cli_recompute_and_preview(db, tmp_path, monkeypatch, capsys):
    import json
    import sys

    from app import cli
    from app.services import strong_import
    seed(db, tmp_path)
    class FixedFactory:
        def __call__(self):
            session = db()
            session.info['metrics_now'] = NOW
            return session
        def begin(self):
            from contextlib import contextmanager
            @contextmanager
            def transaction():
                with self() as session:
                    with session.begin():
                        yield session
            return transaction()
    monkeypatch.setattr(cli, 'SessionLocal', FixedFactory())
    args = ['cli', 'metrics-recompute', '--since', str(TODAY), '--until', str(TODAY), '--metric', 'run_volume_frequency']
    monkeypatch.setattr(sys, 'argv', args)
    assert cli.main() == 0
    first = json.loads(capsys.readouterr().out)
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out) == first
    monkeypatch.setattr(sys, 'argv', ['cli', 'metrics-recompute', '--metric', 'unknown'])
    assert cli.main() == 2
    capsys.readouterr()
    calls = []
    def preview(session, private_dir, path, *, apply):
        calls.append(apply)
        return {'status': 'preview'}
    monkeypatch.setattr(strong_import, 'import_strong_csv', preview)
    monkeypatch.setattr(sys, 'argv', ['cli', 'strong-import', str(tmp_path/'synthetic.csv')])
    assert cli.main() == 0
    assert calls == [False]
