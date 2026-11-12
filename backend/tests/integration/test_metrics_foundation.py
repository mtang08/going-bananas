"""Synthetic metric history and anchor effective-date tests on an isolated schema."""
from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.anchors import router
from app.config import settings
from app.db import get_session
from app.main import handle_http, handle_validation
from app.metric_models import MetricConfig
from app.metric_models import MetricResult as MetricResultRow
from app.metrics.anchors import active_anchors, anchor_set_hash, create_anchor
from app.metrics.contract import MetricResultData, Status
from app.metrics.engine import ensure_metric_config, latest_results, upsert_results
from app.models import AppState

STAMP = datetime(2026, 11, 12, 12, tzinfo=UTC)


def _guard_url() -> str:
    url = os.environ.get('MIGRATION_TEST_DATABASE_URL', '')
    parsed = make_url(url)
    assert settings.app_mode == 'test'
    assert parsed.drivername in ('postgresql+psycopg', 'postgresql')
    assert parsed.host in ('localhost', '127.0.0.1')
    assert parsed.port == 55439 and parsed.database == 'mvp1_migration_test'
    return url


@pytest.fixture
def db():
    engine = create_engine(_guard_url())
    schema = 'mvp011_' + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        with engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            config = Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
            connection.commit()
            SessionLocal = sessionmaker(bind=connection, expire_on_commit=False)
            with SessionLocal() as session:
                state = session.get(AppState, 1)
                assert state is not None
                state.planning_authority = 'legacy'
                session.commit()
            yield SessionLocal
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def _result(config_hash: str, source: str) -> MetricResultData:
    return MetricResultData(metric_id='test_metric.v1', method_version='v1',
        subject_type='activity', subject_key='synthetic-1', status=Status.available,
        reason_codes=(), quality_flags=(), source_refs={'input_hash': source},
        anchor_keys=(), config_hash=config_hash, value={'seconds': 7}, unit='s',
        calculated_at=STAMP, timezone='America/New_York')


@pytest.mark.integration
def test_config_upsert_and_result_history_with_same_session_replay(db) -> None:
    with db() as session:
        digest = ensure_metric_config(session, 'test_metric.v1', 'v1', {'limit': 7})
        assert digest == ensure_metric_config(session, 'test_metric.v1', 'v1', {'limit': 7})
        assert len(session.scalars(select(MetricConfig)).all()) == 1
        first = _result(digest, 'source-v1')
        upsert_results(session, [first])
        first_row = latest_results(session, 'test_metric.v1', 'v1', ['synthetic-1'])['synthetic-1']
        first_id = first_row.id
        upsert_results(session, [replace(first, source_refs={'input_hash': 'source-v2'}, value={'seconds': 8})])
        second_row = latest_results(session, 'test_metric.v1', 'v1', ['synthetic-1'])['synthetic-1']
        assert second_row.id != first_id
        assert len(session.scalars(select(MetricResultRow)).all()) == 2
        upsert_results(session, [first])
        restored = latest_results(session, 'test_metric.v1', 'v1', ['synthetic-1'])['synthetic-1']
        assert restored.id == first_id
        assert len(session.scalars(select(MetricResultRow)).all()) == 2
        upsert_results(session, [replace(first, subject_key='synthetic-2', source_refs={})])
        missing = latest_results(session, 'test_metric.v1', 'v1', ['synthetic-2'])['synthetic-2']
        assert missing.status == 'invalid'
        assert missing.value is None
        upsert_results(session, [replace(first, subject_key='synthetic-2', source_refs={})])
        assert latest_results(session, 'test_metric.v1', 'v1', ['synthetic-2'])['synthetic-2'].value is None
        upsert_results(session, [replace(first, subject_key='synthetic-3', timezone='')])
        filled = latest_results(session, 'test_metric.v1', 'v1', ['synthetic-3'])['synthetic-3']
        assert filled.status == 'available' and filled.timezone == 'America/New_York'
        assert 'MISSING_PROVENANCE' in missing.reason_codes
        session.commit()


def _anchor(kind: str, value: float, valid: date, *, supersedes: str | None = None,
            calibrated: datetime = STAMP) -> dict:
    return {'kind': kind, 'value_low': value, 'unit': 'bpm', 'protocol': 'manual',
            'confidence': 'moderate', 'calibrated_at': calibrated,
            'valid_from': valid, 'supersedes_key': supersedes}


@pytest.mark.integration
def test_anchor_history_same_date_correction_and_backdate_guard(db) -> None:
    with db() as session:
        state = session.get(AppState, 1)
        state.planning_authority = 'calendar'
        session.commit()
        first = create_anchor(session, _anchor('hr_aerobic_upper', 140, date(2026, 11, 1)))
        second = create_anchor(session, _anchor('hr_aerobic_upper', 145, date(2026, 11, 10),
                                                supersedes=first['anchor_key']))
        assert active_anchors(session, date(2026, 11, 9))['hr_aerobic_upper'].value_low == 140
        assert active_anchors(session, date(2026, 11, 10))['hr_aerobic_upper'].value_low == 145
        earlier_calibration = datetime(2026, 11, 10, tzinfo=UTC)
        corrected = create_anchor(session, _anchor('hr_aerobic_upper', 146, date(2026, 11, 10),
            supersedes=second['anchor_key'], calibrated=earlier_calibration))
        active = active_anchors(session, date(2026, 11, 10))['hr_aerobic_upper']
        assert active.anchor_key == corrected['anchor_key'] and active.value_low == 146
        assert anchor_set_hash([active]) != anchor_set_hash([active_anchors(session, date(2026, 11, 9))['hr_aerobic_upper']])
        with pytest.raises(Exception) as error:
            create_anchor(session, _anchor('hr_aerobic_upper', 147, date(2026, 11, 8),
                                           supersedes=corrected['anchor_key']))
        assert getattr(error.value, 'detail', {}).get('code') == 'anchor_backdate_conflict'
        with pytest.raises(Exception) as error:
            create_anchor(session, _anchor('hr_aerobic_upper', 147, date(2026, 11, 11)))
        assert getattr(error.value, 'detail', {}).get('code') == 'anchor_supersede_required'
        session.commit()


@pytest.mark.integration
def test_bare_anchor_router_authority_and_envelope(db) -> None:
    app = FastAPI()
    app.include_router(router, prefix='/api/v1')
    from fastapi import HTTPException
    from fastapi.exceptions import RequestValidationError
    app.add_exception_handler(HTTPException, handle_http)
    app.add_exception_handler(RequestValidationError, handle_validation)
    def session_override():
        with db() as session:
            yield session
    app.dependency_overrides[get_session] = session_override
    client = TestClient(app)
    payload = _anchor('hr_threshold_lower', 160, date(2026, 11, 1))
    payload['calibrated_at'] = STAMP.isoformat()
    payload['valid_from'] = payload['valid_from'].isoformat()
    response = client.post('/api/v1/anchors', json=payload)
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'planning_not_active'
    with db() as session:
        session.get(AppState, 1).planning_authority = 'calendar'
        session.commit()
    response = client.post('/api/v1/anchors', json=payload)
    assert response.status_code == 200
    data = response.json()['data']
    assert data['kind'] == 'hr_threshold_lower' and data['content_hash']
    assert client.get('/api/v1/anchors').json()['data']['items'][0]['anchor_key'] == data['anchor_key']


@pytest.mark.integration
def test_run_selection_coverage_and_source_refs(db) -> None:
    from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
    from app.fit_models import FitFile
    from app.metrics.contract import metric_source_refs
    from app.metrics.engine import activities_coverage_complete, load_runs
    from app.models import Activity, ActivityAnnotation, CoverageInterval, RawObject

    with db() as session:
        activity_id = uuid.uuid4()
        session.add(Activity(id=activity_id, start_at=STAMP,
            original_start=STAMP.isoformat(), local_date=date(2026, 11, 12),
            sport='running', timer_s=1800, distance_m=5000,
            resolution_state='resolved', canonical_revision=1,
            source_workout_label='easy', field_provenance={}))
        session.add(ActivityAnnotation(activity_id=activity_id, version=1,
                                       workout_label='long', excluded=False))
        session.flush()
        runs = load_runs(session, date(2026, 11, 12), date(2026, 11, 13))
        assert len(runs) == 1 and runs[0].workout_label == 'long'
        original_revision = runs[0].source_revision
        session.add(ActivityAnnotation(activity_id=activity_id, version=2,
                                       workout_label='recovery', excluded=False))
        session.flush()
        assert load_runs(session, date(2026, 11, 12), date(2026, 11, 13))[0].source_revision != original_revision
        session.add(CoverageInterval(dataset='activities', start_date=date(2026, 11, 12),
            end_date=date(2026, 11, 12), status='complete', fully_enumerated=True))
        session.flush()
        assert activities_coverage_complete(session, date(2026, 11, 12), date(2026, 11, 13))
        assert not activities_coverage_complete(session, date(2026, 11, 11), date(2026, 11, 13))
        raw = RawObject(sha256='a'*64, relative_path='synthetic.fit.zip', byte_size=10,
                        media_type='application/zip')
        session.add(raw)
        session.flush()
        fit = FitFile(raw_object_id=raw.id, activity_id=activity_id, zip_sha256='a'*64,
                      fit_sha256='b'*64, sdk_version='21.221.0', profile_version='2.1',
                      message_inventory={}, device={})
        session.add(fit)
        version = CalendarVersion(number=1, kind='bootstrap', actor='system')
        session.add(version)
        session.flush()
        uid = uuid.uuid4()
        revision = CalendarSessionRevision(session_uid=uid, revision=1,
            calendar_version_number=1, local_date=date(2026, 11, 12),
            kind='run', intent='Synthetic run', certainty='committed', structure=None)
        session.add(revision)
        session.get(AppState, 1).calendar_head_version = 1
        completion = SessionCompletion(session_uid=uid, activity_id=activity_id,
            status='unknown', match_method='explicit', input_version=1, updated_at=STAMP)
        session.add(completion)
        session.flush()
        refs = metric_source_refs(session, activity_id, uid)
        assert refs['fit']['fit_sha256'] == 'b'*64
        assert refs['plan']['revision_id'] == str(revision.id)
        assert refs['activity']['source_revision']
        association = refs['completion_association_hash']
        completion.status = 'completed_modified'
        completion.version = 8
        session.flush()
        assert metric_source_refs(session, activity_id, uid)['completion_association_hash'] == association
        completion.reason_note = 'Changed association note'
        completion.input_version += 1
        session.flush()
        assert metric_source_refs(session, activity_id, uid)['completion_association_hash'] != association
        session.add(ActivityAnnotation(activity_id=activity_id, version=3, excluded=True))
        session.flush()
        assert load_runs(session, date(2026, 11, 12), date(2026, 11, 13)) == []
        session.commit()
