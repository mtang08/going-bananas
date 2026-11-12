"""Synthetic cutover transaction and source preservation checks in an isolated schema."""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.calendar_models import CalendarSessionRevision, LegacyImportMap, LegacyImportRun, SessionCompletion
from app.config import settings
from app.models import AppState, Checkin
from app.services.legacy_cutover import migrate_legacy_state, require_legacy_write, source_snapshot

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fixtures'))
from legacy_0009 import seed_at_0009, seed_legacy  # noqa: E402


def _guard_url() -> str:
    url = os.environ.get('MIGRATION_TEST_DATABASE_URL', '')
    parsed = make_url(url)
    assert settings.app_mode == 'test'
    assert parsed.drivername in ('postgresql+psycopg', 'postgresql')
    assert parsed.host in ('localhost', '127.0.0.1')
    assert parsed.port == 55439 and parsed.database == 'mvp1_migration_test'
    return url


@pytest.fixture
def db(request):
    engine = create_engine(_guard_url())
    schema = 'mvp068_' + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        with engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            config = Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))
            config.attributes['connection'] = connection
            revision = getattr(request, 'param', 'head')
            command.upgrade(config, revision)
            connection.commit()
            factory = sessionmaker(bind=connection, expire_on_commit=False, autoflush=False)
            if revision == '0009_agent_plan':
                seed_at_0009(connection, date.today())
                connection.commit()
                command.upgrade(config, 'head')
                connection.commit()
            yield factory
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.mark.integration
def test_populated_cutover_preserves_source_after_commit(db):
    with db() as session:
        fixture = seed_legacy(session, date.today())
        session.commit()
        before_counts, before_hashes, _ = source_snapshot(session)
        report = migrate_legacy_state(session, dry_run=False)
        session.commit()
        after_counts, after_hashes, _ = source_snapshot(session)
        assert (after_counts, after_hashes) == (before_counts, before_hashes)
        assert report['key'] == 'remaining_mvp_v1'
        assert report['undo_available'] is False
        state = session.get(AppState, 1, populate_existing=True)
        assert state and state.planning_authority == 'calendar' and state.calendar_head_version == 1
        rows = session.scalars(select(CalendarSessionRevision)).all()
        assert {row.session_uid for row in rows if not row.deleted} == fixture['current']
        assert next(row for row in rows if row.session_uid == fixture['linked']).deleted
        assert fixture['discarded'] not in {row.session_uid for row in rows}
        old_run = next(row for row in rows if row.session_uid in fixture['current'] and row.kind == 'run')
        assert old_run.planned_duration_s == 1800 and old_run.planned_distance_m == 5000
        assert 'Easy warmup' in (old_run.notes or '')
        completion = session.scalar(select(SessionCompletion).where(
            SessionCompletion.session_uid == fixture['linked']))
        assert completion and completion.activity_id == fixture['activity']
        from app.api.metrics import activity_execution
        detail = activity_execution(session, fixture['activity'])
        assert detail['planned']['session_uid'] == fixture['linked']
        assert detail['planned']['intent'] == 'Completed run'
        assert detail['planned']['legacy_payload']['duration_minutes'] == 25
        assert session.scalar(select(func.count()).select_from(LegacyImportMap).where(
            LegacyImportMap.target_kind == 'archive')) == sum(before_counts.values())
        assert session.scalar(select(func.count()).select_from(Checkin)) == 1
        from app.api.history import checkin_history
        history = checkin_history(date.today() - timedelta(days=3), date.today(), session)
        legacy = next(item for item in history['data']['items'] if item['id'] == fixture['checkin'])
        assert legacy['schema_version'] == 1
        assert legacy['payload']['symptoms'] == 'severe'
        assert legacy['payload']['gait'] == 'unaffected'


@pytest.mark.integration
@pytest.mark.parametrize('db', ['0009_agent_plan'], indirect=True)
def test_populated_0009_upgrade_then_cutover(db):
    with db() as session:
        before_counts, before_hashes, _ = source_snapshot(session)
        assert before_counts['planned_sessions'] == 3
        assert before_counts['coach_plan_revisions'] == 1
        report = migrate_legacy_state(session, dry_run=False)
        session.commit()
        assert source_snapshot(session)[:2] == (before_counts, before_hashes)
        assert report['counts']['calendar_sessions'] == 3
        assert session.get(AppState, 1, populate_existing=True).planning_authority == 'calendar'


@pytest.mark.integration
def test_dry_run_replay_and_legacy_guard(db):
    with db() as session:
        seed_legacy(session, date.today())
        session.commit()
        preview = migrate_legacy_state(session, dry_run=True)
        session.rollback()
        assert session.scalar(select(func.count()).select_from(LegacyImportRun)) == 0
        assert session.get(AppState, 1, populate_existing=True).planning_authority == 'legacy'
        applied = migrate_legacy_state(session, dry_run=False)
        session.commit()
        replay = migrate_legacy_state(session, dry_run=False)
        assert replay['already_imported'] is True
        assert replay['source_fingerprint'] == preview['source_fingerprint'] == applied['source_fingerprint']
        assert session.scalar(select(func.count()).select_from(LegacyImportRun)) == 1
        with pytest.raises(HTTPException) as error:
            require_legacy_write(session)
        assert error.value.status_code == 409
        assert error.value.detail['code'] == 'legacy_write_disabled'


@pytest.mark.integration
def test_mid_import_failure_rolls_back_authority_and_sources(db, monkeypatch):
    with db() as session:
        seed_legacy(session, date.today())
        session.commit()
        before = source_snapshot(session)[:2]
        from app.metrics import engine as metrics_engine
        def fail_recompute(session, scope):
            raise RuntimeError('synthetic injected failure')
        monkeypatch.setattr(metrics_engine, 'recompute', fail_recompute)
        with pytest.raises(RuntimeError, match='synthetic injected failure'):
            migrate_legacy_state(session, dry_run=False)
        session.rollback()
        assert source_snapshot(session)[:2] == before
        assert session.get(AppState, 1, populate_existing=True).planning_authority == 'legacy'
        assert session.scalar(select(func.count()).select_from(LegacyImportRun)) == 0
        require_legacy_write(session)


@pytest.mark.integration
def test_unsupported_kind_aborts_without_loss(db):
    with db() as session:
        seed_legacy(session, date.today())
        from app.models import PlannedSession
        row = session.scalar(select(PlannedSession).limit(1))
        assert row is not None
        row.kind = 'teleport'
        session.commit()
        before = source_snapshot(session)[:2]
        with pytest.raises(HTTPException) as error:
            migrate_legacy_state(session, dry_run=False)
        assert error.value.detail['code'] == 'unsupported_legacy_kind'
        session.rollback()
        assert source_snapshot(session)[:2] == before
        assert session.scalar(select(func.count()).select_from(LegacyImportRun)) == 0


@pytest.mark.integration
def test_old_entrypoints_reject_writes_after_cutover(db):
    from app.api import coaching, core
    from app.services import agent_plans
    with db() as session:
        seed_legacy(session, date.today())
        session.commit()
        migrate_legacy_state(session, dry_run=False)
        session.commit()
        before = source_snapshot(session)[:2]
        fake = uuid.uuid4()
        calls = [
            lambda: core.post_checkin(None, None, session),
            lambda: core.patch_checkin(fake, None, session),
            lambda: core.post_plan(None, session),
            lambda: core.decide_plan(fake, None, 'accepted', session),
            lambda: core.post_completion_link(None, session),
            lambda: core.delete_completion_link(fake, session),
            lambda: core.post_weekly_snapshot(None, session),
            lambda: coaching._post(session, 'daily', None, None),
            lambda: coaching.post_outcome(fake, None, session),
            lambda: agent_plans.submit(session, None),
            lambda: agent_plans.rollback(session, fake, fake, 'synthetic'),
            lambda: agent_plans._persist(session, day=date.today(), workflow='daily',
                summary='', rationale='', evidence_hash='', key='', current=None,
                before=[], updates=[], inputs={}, review={}, source_ids=[], warnings=[]),
        ]
        for call in calls:
            with pytest.raises(HTTPException) as error:
                call()
            assert error.value.status_code == 409
            assert error.value.detail['code'] == 'legacy_write_disabled'
        session.rollback()
        assert source_snapshot(session)[:2] == before
