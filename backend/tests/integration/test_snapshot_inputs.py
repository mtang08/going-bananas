"""Snapshot input sections on guarded synthetic state."""
from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from app.calendar_models import SessionCompletion
from app.checkin_models import Checkin, SymptomReport
from app.metric_models import MetricResult
from app.metrics.engine import REGISTRY, metric_modules
from app.planning_models import Block, BlockVersion, Event, Goal
from app.services import calendar, weekly_digest
from app.services.snapshot import _load_metrics, load_inputs
from app.services.snapshot.common import ROLLING
from app.services.snapshot.payload import build_payload

NOW = datetime(2026, 11, 16, 15, tzinfo=UTC)
TODAY = date(2026, 11, 16)


@pytest.fixture
def seeded(proposal_session):
    session = proposal_session
    checkin = Checkin(idempotency_key='snapshot-fixture', kind='exception',
        observed_at=NOW - timedelta(days=1), context_tags=[], version=1, schema_version=2)
    session.add(checkin)
    block = Block(block_uid=uuid.uuid4())
    session.add(block)
    session.flush()
    session.add(SymptomReport(checkin_id=checkin.id, site='Achilles', side='left', severity=3.0,
                              timing='during'))
    session.add(Goal(text='Synthetic goal', horizon='season', priority=1, status='active'))
    session.add(Event(name='Synthetic 10K', event_date=TODAY + timedelta(days=20),
                      priority='target', status='registered'))
    session.add(BlockVersion(block_uid=block.block_uid, version=1, status='active',
        objective='Build', rationale='Ready', maintained_qualities=[], non_goals=[],
        eligible_recipe_ids=['REC001'], progression_dimension='duration', constraints=[],
        start_date=TODAY, review_date=date(2026, 12, 28), completion_indicators=[],
        early_review_triggers=[], objective_status='unresolved'))
    run = next(row for row in calendar.state_at(session, 1) if row['kind'] == 'run')
    session.add(SessionCompletion(session_uid=run['session_uid'], status='skipped',
        match_method='none', updated_at=NOW))
    session.commit()
    return session


def test_load_inputs_sections(seeded):
    inputs = load_inputs(seeded, TODAY, now=NOW)
    assert len(inputs.checkins) == 1 and inputs.checkins[0]['symptoms'][0]['site'] == 'Achilles'
    assert [goal['text'] for goal in inputs.goals] == ['Synthetic goal']
    assert inputs.events[0]['name'] == 'Synthetic 10K'
    assert inputs.active_block['status'] == 'active'
    assert inputs.timezone == 'America/New_York'


def test_snapshot_metrics_ignore_other_current_versions(seeded, monkeypatch):
    metric_modules()
    activity_key = str(uuid.uuid4())
    long_run = 'long_run_exposure'
    rpe = 'session_rpe_load'
    old_version = 'v1'
    new_version = 'v2'
    monkeypatch.setitem(REGISTRY, long_run, replace(REGISTRY[long_run], method_version=new_version))
    monkeypatch.setitem(REGISTRY, rpe, replace(REGISTRY[rpe], method_version=old_version))
    for metric in (long_run, rpe):
        for version in (old_version, new_version):
            seeded.add(MetricResult(
                metric_id=metric, method_version=version, subject_type='activity', subject_key=activity_key,
                status='available', source_refs={}, config_hash='synthetic', dependency_hash='synthetic',
                timezone='UTC', calculated_at=NOW, is_current=True,
            ))
    seeded.flush()

    rows = _load_metrics(seeded, TODAY, [{'activity_id': activity_key}])

    assert [(row['metric_id'], row['method_version']) for row in rows if row['subject_key'] == activity_key] == [
        (long_run, new_version),
        (rpe, old_version),
    ]


def test_rolling_snapshot_carries_weekly_digest(seeded):
    inputs = load_inputs(seeded, TODAY, now=NOW)
    payload = build_payload(inputs, ROLLING)
    section = payload['weekly_digest']
    assert section['schema'] == 'weekly_digest.v1'
    assert [w['week_start'] for w in section['weeks']] == ['2026-11-09', '2026-11-16']
    previous, current = section['weeks']
    assert (previous['days_elapsed'], current['days_elapsed']) == (7, 1)
    expected = weekly_digest.load_week(seeded, TODAY, today=TODAY)
    assert current['totals'] == expected['totals']
    sessions = current['totals']['sessions']
    assert (sessions['planned'], sessions['planned_to_date'], sessions['by_outcome']['missed']) == (3, 1, 1)
    assert previous['totals']['sessions']['planned'] == 0
    assert [row['outcome'] for row in current['not_done']] == ['missed']
    assert current['key_sessions'] == []
    assert 'quality_sessions' not in payload['exception_summary']
