"""Differential snapshot inputs on guarded synthetic state."""
from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
import types
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.checkin_models import Checkin, SymptomReport
from app.coach_v2_models import CoachDecisionKey, CoachProposal, CoachProposalChange, CoachSnapshot
from app.config import settings
from app.db import engine
from app.models import AppState, ProfileVersion
from app.planning_models import Block, BlockVersion, Event, Goal
from app.services import calendar
from app.services.snapshot import load_inputs

NOW = datetime(2026, 11, 16, 15, tzinfo=UTC)
TODAY = date(2026, 11, 16)
REPO = Path(__file__).resolve().parents[3]
REFERENCE_SHA = 'a5a6cd5fcf2961d4e430ed27261b06f9139e6c63'
_REFERENCE: types.ModuleType | None = None


@pytest.fixture
def seeded(monkeypatch):
    parsed = urlsplit(settings.database_url)
    assert settings.app_mode == "test"
    assert parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == int(os.environ.get('TEST_DATABASE_PORT', '55439'))
    assert parsed.path == "/garmin_test"
    monkeypatch.setattr(calendar, "_today", lambda session, now=None: TODAY)
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                session.info['metrics_now'] = NOW
                session.execute(delete(CoachDecisionKey))
                session.execute(delete(CoachProposalChange))
                session.execute(delete(CoachProposal))
                session.execute(delete(CoachSnapshot))
                session.execute(delete(SessionCompletion))
                session.execute(delete(CalendarSessionRevision))
                session.execute(delete(CalendarVersion))
                state = session.get(AppState, 1, with_for_update=True)
                state.calendar_head_version = 0
                state.planning_authority = "calendar"
                version = (session.scalar(select(func.max(ProfileVersion.version))) or 0) + 1
                session.add(
                    ProfileVersion(
                        version=version,
                        effective_at=NOW - timedelta(days=1),
                        timezone="America/New_York",
                        cycle_anchor=TODAY,
                        anchor_confirmed=True,
                        strength_days_confirmed=True,
                        scheduled_strength_days=[0, 4],
                        strength_schedule_mode="weekly",
                        facts={},
                        preferences={},
                        unknowns=[],
                    )
                )
                session.flush()
                edits = [
                    {
                        "op": "add",
                        "fields": {
                            "local_date": date(2026, 11, day),
                            "kind": kind,
                            "intent": "Train",
                            **({"recipe_id": "REC001", "planned_duration_s": 1800} if kind == "run" else {}),
                        },
                    }
                    for day, kind in [
                        (16, "strength"),
                        (20, "strength"),
                        (23, "strength"),
                        (27, "strength"),
                        (18, "run"),
                    ]
                ]
                calendar.apply_edits(session, 0, edits, "Fixture")
                session.flush()
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
                yield session
        finally:
            outer.rollback()


def _reference_module() -> types.ModuleType:
    global _REFERENCE
    if _REFERENCE is None:
        source = subprocess.run(['git', 'show', f'{REFERENCE_SHA}:backend/app/services/snapshot.py'], cwd=REPO,
                                check=True, capture_output=True, text=True).stdout
        module = types.ModuleType('_snapshot_reference')
        sys.modules['_snapshot_reference'] = module
        exec(compile(source, '_snapshot_reference.py', 'exec'), module.__dict__)
        _REFERENCE = module
    return _REFERENCE


def _reference_load_inputs(session, as_of, *, now):
    return _reference_module().load_inputs(session, as_of, now=now)


def test_load_inputs_matches_reference(seeded):
    assert dataclasses.asdict(load_inputs(seeded, TODAY, now=NOW)) == dataclasses.asdict(
        _reference_load_inputs(seeded, TODAY, now=NOW))


def test_load_inputs_sections(seeded):
    inputs = load_inputs(seeded, TODAY, now=NOW)
    assert len(inputs.checkins) == 1 and inputs.checkins[0]['symptoms'][0]['site'] == 'Achilles'
    assert [goal['text'] for goal in inputs.goals] == ['Synthetic goal']
    assert inputs.events[0]['name'] == 'Synthetic 10K'
    assert inputs.active_block['status'] == 'active'
    assert inputs.timezone == 'America/New_York'
