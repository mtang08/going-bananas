"""Preservation and constraint checks for the additive MVP schema migrations.

The fixture owns a uniquely named schema in the dedicated synthetic migration database.
It never creates or drops a database and never prints a connection string.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import get_session
from app.main import app

HEAD = '0015_coach_v2'
STAMP = datetime(2026, 11, 12, tzinfo=UTC)
HEADERS = {'X-Local-Request': '1', 'Origin': 'http://testserver'}


def _guard_url() -> str:
    url = os.environ.get('MIGRATION_TEST_DATABASE_URL', '')
    parsed = make_url(url)
    assert settings.app_mode == 'test'
    assert parsed.drivername in {'postgresql+psycopg', 'postgresql'}
    assert parsed.host in {'localhost', '127.0.0.1'}
    assert parsed.port == 55439
    assert parsed.database == 'mvp1_migration_test'
    return url


def _migration(connection, revision: str, *, down: bool = False) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))
    config.attributes['connection'] = connection
    (command.downgrade if down else command.upgrade)(config, revision)


@pytest.fixture
def isolated_schema():
    engine = create_engine(_guard_url(), pool_pre_ping=True)
    name = 'mvp003_' + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{name}"'))
    try:
        with engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{name}"'))
            connection.commit()
            yield connection
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        engine.dispose()


def _insert(connection, table: str, **values) -> uuid.UUID:
    values.setdefault('id', uuid.uuid4())
    if table == 'activities':
        values.setdefault('canonical_revision', 1)
        values.setdefault('resolution_state', 'resolved')
        values.setdefault('field_provenance', '{}')
    if table == 'manual_sessions':
        values.setdefault('version', 1)
    columns = ', '.join(values)
    binds = ', '.join(':' + key for key in values)
    connection.execute(text(f'INSERT INTO {table} ({columns}) VALUES ({binds})'), values)
    return values['id']


def _legacy_snapshot(connection, columns_by_table=None):
    """Project precisely the pre-upgrade columns, including JSON payloads and IDs."""
    inspector = inspect(connection)
    excluded = {'alembic_version'}
    result = {}
    tables = columns_by_table or {table: [column['name'] for column in inspector.get_columns(table)]
        for table in sorted(set(inspector.get_table_names()) - excluded)}
    for table, columns in tables.items():
        if 'id' not in columns and table != 'sync_state':
            continue
        projection = ', '.join('t."' + column + '"' for column in columns)
        rows = connection.execute(text(f'SELECT row_to_json(q)::text FROM (SELECT {projection} FROM "{table}" t) q')).scalars().all()
        canonical = sorted(json.dumps(json.loads(row), sort_keys=True, separators=(',', ':')) for row in rows)
        result[table] = (len(canonical), hashlib.sha256('\n'.join(canonical).encode()).hexdigest(), canonical)
    return result, tables


def _seed_legacy(connection):
    _insert(connection, 'profile_versions', version=1, effective_at=STAMP,
        timezone='America/New_York', cycle_anchor=STAMP.date(), anchor_confirmed=True,
        strength_days_confirmed=True, scheduled_strength_days='[0,4]',
        strength_schedule_mode='alternating', strength_week_a_start='2026-11-09',
        strength_week_a_days='[0,4]', strength_week_b_days='[1,5]',
        mobility_week_a_days='[2]', mobility_week_b_days='[3]',
        mobility_optional_days='[6]', facts='{"training":"synthetic"}',
        preferences='{"long_run_weekdays":[5,6]}', unknowns='[]')
    account = _insert(connection, 'source_accounts', provider='synthetic', account_scope=str(uuid.uuid4()))
    raw = _insert(connection, 'raw_objects', sha256='a'*64, relative_path='synthetic/strong.csv',
        byte_size=20, media_type='text/csv')
    record = _insert(connection, 'source_records', source_account_id=account,
        raw_object_id=raw, source_identity='synthetic-row', payload_hash='b'*64,
        fetched_at=STAMP, parser_version='fixture', source_kind='strong',
        fields='{"sets":[{"reps":5}]}')
    activity = _insert(connection, 'activities', source_account_id=account,
        source_identity='synthetic-run', start_at=STAMP, original_start=STAMP.isoformat(),
        local_date=STAMP.date(), sport='running', distance_m=5000,
        field_provenance='{"distance_m":"synthetic"}')
    _insert(connection, 'strong_workouts', source_account_id=account, source_identity='synthetic-lift',
        source_record_id=record, raw_object_id=raw, payload_hash='c'*64,
        local_date=STAMP.date(), local_start='2026-11-12T08:00:00', workout_name='Fixture lift',
        sets='[{"exercise":"squat","reps":5}]', row_count=1)
    first = _insert(connection, 'plan_versions', version=1, status='accepted',
        start_date='2026-11-09', end_date='2026-11-22', profile_version=1)
    second = _insert(connection, 'plan_versions', version=2, parent_id=first, status='draft',
        start_date='2026-11-16', end_date='2026-11-29', profile_version=1)
    old_session = _insert(connection, 'planned_sessions', plan_id=first, date='2026-11-12',
        kind='run', target='{"intent":"easy","distance_km":5}')
    new_session = _insert(connection, 'planned_sessions', plan_id=second, date='2026-11-18',
        kind='run', target='{"intent":"long","distance_km":8}')
    _insert(connection, 'completion_links', planned_session_id=old_session, activity_id=activity)
    checkin = _insert(connection, 'checkins', idempotency_key='synthetic-checkin', version=2,
        observed_at=STAMP, symptoms='none', gait='normal', feeling='usual',
        activity_id=activity, note='synthetic only')
    _insert(connection, 'checkin_revisions', checkin_id=checkin, version=1,
        payload='{"symptoms":"none","note":"prior synthetic value"}')
    recommendation = _insert(connection, 'coach_recommendations', kind='daily',
        as_of=STAMP.date(), engine='local_rules', knowledge_version='fixture',
        data_revision=0, profile_version=1, plan_version=1, input_hash='f'*64,
        inputs='{"source":"synthetic"}', payload='{"decision":"proceed"}')
    _insert(connection, 'coach_outcomes', recommendation_id=recommendation,
        status='accepted', effect='followed', note='synthetic')
    _insert(connection, 'coach_outcome_events', recommendation_id=recommendation,
        status='accepted', effect='followed', note='synthetic event')
    prior = _insert(connection, 'coach_plan_revisions', plan_id=first, workflow='weekly',
        as_of=STAMP.date(), idempotency_key='synthetic-coach-1', evidence_hash='d'*64,
        summary='synthetic', rationale='synthetic', payload=json.dumps({'active_session_ids':[str(old_session),str(new_session)]}), inputs='{}')
    _insert(connection, 'coach_plan_revisions', parent_revision_id=prior, plan_id=second,
        workflow='daily', as_of=STAMP.date(), idempotency_key='synthetic-coach-2',
        evidence_hash='e'*64, summary='synthetic', rationale='synthetic',
        payload=json.dumps({'active_session_ids':[str(new_session),str(old_session)]}), inputs='{}')
    return activity


def _expect_integrity(connection, sql: str, *, constraint: str | None = None, **params):
    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            connection.execute(text(sql), params)
    if constraint:
        assert error.value.orig.diag.constraint_name == constraint


def test_populated_0009_upgrade_preserves_legacy_and_serves_profile(isolated_schema):
    connection = isolated_schema
    _migration(connection, '0009_agent_plan')
    activity = _seed_legacy(connection)
    connection.commit()
    before, projection = _legacy_snapshot(connection)
    _migration(connection, HEAD)
    connection.commit()
    after, _ = _legacy_snapshot(connection, projection)
    assert after == before
    assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == HEAD
    assert connection.execute(text('SELECT calendar_head_version, planning_authority FROM app_state WHERE id=1')).one() == (0, 'legacy')
    assert connection.execute(text('SELECT fit_status FROM activities WHERE id=:id'), {'id': activity}).scalar_one() == 'not_fetched'

    factory = sessionmaker(bind=connection, expire_on_commit=False)
    def override():
        with factory() as session:
            yield session
    app.dependency_overrides[get_session] = override
    with patch('app.main.SessionLocal', factory):
        try:
            client = TestClient(app)
            assert client.get('/api/v1/health/ready').status_code == 200
            profile = client.get('/api/v1/profile').json()['data']
            assert profile['strength_schedule_mode'] == 'alternating'
            assert profile['planning_authority'] == 'legacy'
            profile['expected_version'] = profile['version']
            profile['planning_authority'] = 'calendar'
            profile['preferences'] = {'long_run_weekdays': [6]}
            response = client.put('/api/v1/profile', json=profile, headers=HEADERS)
            assert response.status_code == 200, response.text
            assert response.json()['data']['planning_authority'] == 'legacy'
            assert connection.execute(text('SELECT planning_authority FROM app_state WHERE id=1')).scalar_one() == 'legacy'
            connection.execute(text("UPDATE app_state SET planning_authority='calendar' WHERE id=1"))
            connection.commit()
            profile = client.get('/api/v1/profile').json()['data']
            assert profile['planning_authority'] == 'calendar'
            profile.update(expected_version=profile['version'], planning_authority='legacy')
            response = client.put('/api/v1/profile', json=profile, headers=HEADERS)
            assert response.status_code == 200, response.text
            assert response.json()['data']['planning_authority'] == 'calendar'
            assert connection.execute(text('SELECT planning_authority FROM app_state WHERE id=1')).scalar_one() == 'calendar'
        finally:
            app.dependency_overrides.pop(get_session, None)


def test_empty_round_trip_and_each_nonempty_downgrade_guard(isolated_schema):
    connection = isolated_schema
    _migration(connection, HEAD)
    connection.commit()
    factory = sessionmaker(bind=connection, expire_on_commit=False)
    def override():
        with factory() as session:
            yield session
    app.dependency_overrides[get_session] = override
    try:
        response = TestClient(app).get('/api/v1/profile')
        assert response.status_code == 200
        assert response.json()['data']['planning_authority'] == 'legacy'
    finally:
        app.dependency_overrides.pop(get_session, None)
    guard_cases = [
        ('0015_coach_v2', '0014_anchors_metrics_prompts', 'daily_guidance',
         dict(local_date=STAMP.date(), engine='local_rules.v2', decision='proceed',
              rationale='synthetic', input_hash='a'*64)),
        ('0014_anchors_metrics_prompts', '0013_blocks_goals', 'prompts',
         dict(kind='rpe', opens_at=STAMP, status='open')),
        ('0013_blocks_goals', '0012_calendar', 'goals',
         dict(text='synthetic goal', horizon='season', priority=1, status='active')),
        ('0012_calendar', '0011_checkins_v2', 'calendar_versions',
         dict(number=1, kind='bootstrap', actor='system')),
        ('0011_checkins_v2', '0010_ingest_fit', 'checkins_v2',
         dict(idempotency_key='synthetic', kind='exception', observed_at=STAMP)),
        ('0010_ingest_fit', '0009_agent_plan', 'activity_laps', None),
    ]
    for revision, previous, table, values in guard_cases:
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == revision
        if values is None:
            activity = _insert(connection, 'activities', start_at=STAMP,
                original_start=STAMP.isoformat(), local_date=STAMP.date(), sport='running')
            values = dict(activity_id=activity, lap_index=0, start_at=STAMP)
        row_id = _insert(connection, table, **values)
        connection.commit()
        with pytest.raises(RuntimeError, match='restore_required_nonempty_mvp_schema'):
            _migration(connection, previous, down=True)
        connection.rollback()
        assert connection.execute(text(f"SELECT to_regclass('{table}') IS NOT NULL")).scalar_one()
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == revision
        connection.execute(text(f'DELETE FROM {table} WHERE id=:id'), {'id': row_id})
        if revision == '0012_calendar':
            connection.execute(text("UPDATE app_state SET planning_authority='calendar' WHERE id=1"))
            connection.commit()
            with pytest.raises(RuntimeError, match='restore_required_nonempty_mvp_schema'):
                _migration(connection, previous, down=True)
            connection.rollback()
            assert connection.execute(text("SELECT to_regclass('calendar_versions') IS NOT NULL")).scalar_one()
            connection.execute(text("UPDATE app_state SET planning_authority='legacy', calendar_head_version=2 WHERE id=1"))
            connection.commit()
            with pytest.raises(RuntimeError, match='restore_required_nonempty_mvp_schema'):
                _migration(connection, previous, down=True)
            connection.rollback()
            connection.execute(text('UPDATE app_state SET calendar_head_version=0 WHERE id=1'))
        if revision == '0010_ingest_fit':
            connection.execute(text("UPDATE activities SET fit_status='fetched' WHERE id=:id"), {'id': activity})
            connection.commit()
            with pytest.raises(RuntimeError, match='restore_required_nonempty_mvp_schema'):
                _migration(connection, previous, down=True)
            connection.rollback()
            assert connection.execute(text("SELECT to_regclass('fit_files') IS NOT NULL")).scalar_one()
            connection.execute(text("UPDATE activities SET fit_status='not_fetched' WHERE id=:id"), {'id': activity})
        _migration(connection, previous, down=True)
        connection.commit()
    _migration(connection, HEAD)
    connection.commit()
    assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == HEAD


def test_database_subject_uniqueness_ranges_and_late_foreign_keys(isolated_schema):
    connection = isolated_schema
    _migration(connection, HEAD)
    connection.commit()
    expected_foreign_keys = {
        ('activities', 'fit_file_id', 'fit_files'),
        ('checkins_v2', 'prompt_id', 'prompts'),
        ('calendar_versions', 'block_version_id', 'block_versions'),
        ('calendar_versions', 'proposal_id', 'coach_proposals'),
        ('calendar_session_revisions', 'strength_slot_id', 'strength_routine_slots'),
        ('block_versions', 'proposal_id', 'coach_proposals'),
        ('block_decisions', 'proposal_id', 'coach_proposals'),
        ('intensity_anchors', 'proposal_id', 'coach_proposals'),
    }
    actual_foreign_keys = {(table, column, fk['referred_table'])
        for table in {item[0] for item in expected_foreign_keys}
        for fk in inspect(connection).get_foreign_keys(table)
        for column in fk['constrained_columns']}
    assert expected_foreign_keys <= actual_foreign_keys
    activity = _insert(connection, 'activities', start_at=STAMP, original_start=STAMP.isoformat(),
        local_date=STAMP.date(), sport='running')
    manual = _insert(connection, 'manual_sessions', date=STAMP.date(), kind='run')
    connection.commit()

    _insert(connection, 'prompts', kind='rpe', opens_at=STAMP, status='open')
    connection.commit()
    _expect_integrity(connection,
        "INSERT INTO prompts (id,kind,opens_at,status) VALUES (:id,'rpe',:at,'open')",
        constraint='uq_prompts_kind_activity_session', id=uuid.uuid4(), at=STAMP)
    _expect_integrity(connection,
        "INSERT INTO session_rpe (id,rpe,source,collected_at) VALUES (:id,5,'manual',:at)",
        constraint='ck_session_rpe_subject', id=uuid.uuid4(), at=STAMP)
    _expect_integrity(connection,
        "INSERT INTO session_rpe (id,activity_id,manual_session_id,rpe,source,collected_at) VALUES (:id,:activity,:manual,5,'manual',:at)",
        constraint='ck_session_rpe_subject', id=uuid.uuid4(), activity=activity, manual=manual, at=STAMP)
    _expect_integrity(connection,
        "INSERT INTO session_rpe (id,activity_id,rpe,source,collected_at) VALUES (:id,:activity,11,'manual',:at)",
        constraint='ck_session_rpe_rpe', id=uuid.uuid4(), activity=activity, at=STAMP)
    _insert(connection, 'session_rpe', activity_id=activity, rpe=0, source='manual', collected_at=STAMP)
    _insert(connection, 'session_rpe', manual_session_id=manual, rpe=10, source='manual', collected_at=STAMP)
    connection.commit()

    _insert(connection, 'session_completions', session_uid=uuid.uuid4(), status='skipped',
        match_method='none', updated_at=STAMP)
    connection.commit()
    _expect_integrity(connection,
        "INSERT INTO session_completions (id,session_uid,status,match_method,updated_at) VALUES (:id,:uid,'completed_as_planned','none',:at)",
        constraint='ck_session_completions_status_subject', id=uuid.uuid4(), uid=uuid.uuid4(), at=STAMP)
    _expect_integrity(connection,
        "INSERT INTO session_completions (id,session_uid,activity_id,manual_session_id,status,match_method,updated_at) VALUES (:id,:uid,:activity,:manual,'skipped','explicit',:at)",
        constraint='ck_session_completions_subject', id=uuid.uuid4(), uid=uuid.uuid4(), activity=activity, manual=manual, at=STAMP)
    _expect_integrity(connection,
        "INSERT INTO checkins_v2 (id,idempotency_key,kind,observed_at,context_tags) VALUES (:id,'bad-tag','exception',:at,ARRAY['invalid'])",
        constraint='ck_checkins_v2_context_tags', id=uuid.uuid4(), at=STAMP)
    _expect_integrity(connection,
        "INSERT INTO checkins_v2 (id,idempotency_key,kind,observed_at,context_tags,prompt_id) VALUES (:id,'bad-prompt','exception',:at,ARRAY[]::varchar[],:prompt)",
        constraint='fk_checkins_v2_prompt_id', id=uuid.uuid4(), at=STAMP, prompt=uuid.uuid4())
    _insert(connection, 'calendar_versions', number=1, kind='bootstrap', actor='system')
    connection.commit()
    _expect_integrity(connection,
        "INSERT INTO calendar_session_revisions (id,session_uid,revision,calendar_version_number,local_date,kind,intent,certainty,strength_slot_id) VALUES (:id,:uid,1,1,:day,'strength','lift','committed',:slot)",
        constraint='fk_calendar_session_revisions_strength_slot_id',
        id=uuid.uuid4(), uid=uuid.uuid4(), day=STAMP.date(), slot=uuid.uuid4())

    anchor = dict(anchor_key='fixture-aerobic', kind='hr_aerobic_upper', value_low=140,
        unit='bpm', protocol='manual', confidence='high', status='active',
        calibrated_at=STAMP, valid_from=STAMP.date(), review_after=STAMP.date())
    _insert(connection, 'intensity_anchors', **anchor)
    connection.commit()
    _expect_integrity(connection,
        """INSERT INTO intensity_anchors (id,anchor_key,kind,value_low,unit,protocol,confidence,status,calibrated_at,valid_from,review_after)
           VALUES (:id,'bad-unit','hr_aerobic_upper',140,'mps','manual','high','active',:at,:day,:day)""",
        id=uuid.uuid4(), at=STAMP, day=STAMP.date())
    _expect_integrity(connection,
        """INSERT INTO intensity_anchors (id,anchor_key,kind,value_low,value_high,unit,protocol,confidence,status,calibrated_at,valid_from,review_after)
           VALUES (:id,'bad-range','hr_aerobic_upper',150,140,'bpm','manual','high','active',:at,:day,:day)""",
        id=uuid.uuid4(), at=STAMP, day=STAMP.date())

    metric_config = dict(metric_id='fixture', method_version='v1', config='{}', config_hash='a'*64)
    _insert(connection, 'metric_configs', **metric_config)
    connection.commit()
    _expect_integrity(connection,
        "INSERT INTO metric_configs (id,metric_id,method_version,config,config_hash) VALUES (:id,'fixture','v1','{}',:hash)",
        id=uuid.uuid4(), hash='a'*64)
    metric = dict(metric_id='fixture', method_version='v1', subject_type='activity',
        subject_key=str(activity), status='available', reason_codes='{}', quality_flags='{}',
        source_refs='{}', anchor_keys='{}', config_hash='a'*64,
        calculated_at=STAMP, dependency_hash='b'*64, timezone='America/New_York')
    _insert(connection, 'metric_results', **metric)
    connection.commit()
    _expect_integrity(connection,
        """INSERT INTO metric_results (id,metric_id,method_version,subject_type,subject_key,status,
             reason_codes,quality_flags,source_refs,anchor_keys,config_hash,calculated_at,
             dependency_hash,timezone)
             VALUES (:id,'fixture','v1','activity',:subject,'available','{}','{}','{}','{}',:config,:at,:dependency,'America/New_York')""",
        constraint='uq_metric_results_identity', id=uuid.uuid4(), subject=str(activity), config='a'*64, dependency='b'*64, at=STAMP)
    _expect_integrity(connection,
        """INSERT INTO metric_results (id,metric_id,method_version,subject_type,subject_key,status,
             reason_codes,quality_flags,source_refs,anchor_keys,config_hash,calculated_at,
             dependency_hash,timezone)
             VALUES (:id,'fixture','v1','activity',:subject,'available','{}','{}','{}','{}',:config,:at,:dependency,'America/New_York')""",
        constraint='uq_metric_results_current', id=uuid.uuid4(), subject=str(activity), config='a'*64, dependency='c'*64, at=STAMP)
