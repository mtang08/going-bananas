"""CLI source snapshots and pending proposal submission, using synthetic state."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.coach_v2_models import CoachDecisionKey, CoachProposal, CoachProposalChange, CoachSnapshot
from app.config import settings
from app.db import engine
from app.models import AppState, ProfileVersion
from app.services import calendar

NOW = datetime(2026, 11, 16, 15, tzinfo=UTC)
TODAY = date(2026, 11, 16)

@pytest.fixture
def proposal_session(monkeypatch):
    parsed = urlsplit(settings.database_url)
    assert settings.app_mode == "test"
    assert parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == 55439
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
                session.commit()
                yield session
        finally:
            outer.rollback()


def _doc(snapshot: CoachSnapshot, uid: uuid.UUID) -> dict:
    return {
        "schema_version": "coach_proposal.v1",
        "operation": snapshot.operation,
        "snapshot_id": str(snapshot.id),
        "base_calendar_version": snapshot.calendar_version_number,
        "base_block_version_id": None,
        "summary": "Add easy time",
        "rationale": "Ready for a small increase",
        "confidence": {"decision": "moderate", "evidence": "moderate", "data": "moderate"},
        "changes": [
            {
                "change_id": "c1",
                "op": "modify",
                "session_uid": str(uid),
                "after": {"planned_duration_s": 2400},
                "reason": "Progression",
            }
        ],
        "preserved": [],
        "evidence_ids": ["E-AER-01"],
        "policy_ids": ["P001"],
        "recipe_ids": ["REC001"],
        "skill_version": "running-coach.v1",
    }




@pytest.fixture
def cli_db(proposal_session, monkeypatch, capsys):
    import json
    import sys

    from sqlalchemy.orm import sessionmaker

    from app import cli
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(cli, 'datetime', Clock)
    factory = sessionmaker(bind=proposal_session.bind, join_transaction_mode='create_savepoint',
        expire_on_commit=False, info={'metrics_now':NOW})
    monkeypatch.setattr(cli, 'SessionLocal', factory)
    def run(*args):
        monkeypatch.setattr(sys, 'argv', ['app.cli','coach',*args])
        status = cli.main()
        captured = capsys.readouterr()
        return status, json.loads(captured.out) if captured.out else None, captured.err
    return run, proposal_session


def snapshot_doc(run, session):
    code, result, error = run('snapshot','--operation','review_rolling_plan')
    assert code == 0, error
    snapshot = session.get(CoachSnapshot, uuid.UUID(result['snapshot_id']))
    uid = next(row['session_uid'] for row in calendar.state_at(session, snapshot.calendar_version_number)
               if row['kind'] == 'run')
    return result, _doc(snapshot, uid)


def write_doc(tmp_path, document):
    import json
    path = tmp_path/'proposal.json'
    path.write_text(json.dumps(document))
    return str(path)


def test_snapshot_twice_same_payload_hash(cli_db):
    run, session = cli_db
    before = session.get(AppState, 1).data_revision
    first, _ = snapshot_doc(run, session)
    second, _ = snapshot_doc(run, session)
    a = session.get(CoachSnapshot, uuid.UUID(first['snapshot_id']))
    b = session.get(CoachSnapshot, uuid.UUID(second['snapshot_id']))
    assert a.id != b.id and a.payload_sha256 == b.payload_sha256
    assert session.get(AppState, 1, populate_existing=True).data_revision == before
    assert first['payload']['snapshot_meta']['source_fingerprint'] == a.source_fingerprint
    assert first['kb']['excerpts']


def test_resubmit_same_file_idempotent(cli_db, tmp_path):
    run, session = cli_db
    _, document = snapshot_doc(run, session)
    path = write_doc(tmp_path, document)
    code, first, error = run('submit','--file',path)
    assert code == 0, (first,error)
    code, second, error = run('submit','--file',path)
    assert code == 0 and first == second
    assert session.scalar(select(func.count()).select_from(CoachProposal)) == 1
    assert first['status'] == 'pending'
    assert session.get(AppState, 1, populate_existing=True).calendar_head_version == 1


def test_submit_invalid_exit_2_nothing_written(cli_db, tmp_path):
    run, session = cli_db
    _, document = snapshot_doc(run, session)
    document['extra_field'] = 1
    code, result, error = run('submit','--file',write_doc(tmp_path, document))
    assert code == 2 and result['status'] == 'invalid'
    assert result['proposal_id'] is None and result['errors'][0]['code'] == 'V1.schema'
    assert session.scalar(select(func.count()).select_from(CoachProposal)) == 0


def test_manual_edit_stales_pending_proposal(cli_db, tmp_path):
    run, session = cli_db
    _, document = snapshot_doc(run, session)
    code, submitted, error = run('submit','--file',write_doc(tmp_path,document))
    assert code == 0, (submitted,error)
    result = calendar.apply_edits(session, 1, [{'op':'modify','session_uid':uuid.UUID(document['changes'][0]['session_uid']),
        'fields':{'intent':'Athlete change'}}], 'User edit')
    session.commit()
    assert uuid.UUID(submitted['proposal_id']) in result['stale_proposals']
    assert session.get(CoachProposal, uuid.UUID(submitted['proposal_id']), populate_existing=True).status == 'stale'


def test_submit_stale_exit_3(cli_db, tmp_path):
    run, session = cli_db
    _, document = snapshot_doc(run, session)
    calendar.apply_edits(session, 1, [{'op':'modify','session_uid':uuid.UUID(document['changes'][0]['session_uid']),
        'fields':{'intent':'Athlete change'}}], 'User edit')
    session.commit()
    code, result, error = run('submit','--file',write_doc(tmp_path, document))
    assert code == 3 and result['status'] == 'stale'


def test_query_commands_and_schema(cli_db):
    run, session = cli_db
    code, schema, _ = run('schema')
    assert code == 0 and schema['activation'] == 'manual' and schema['required_authority'] == 'calendar'
    code, data, error = run('query','calendar_diff','--from','0','--to','1')
    assert code == 0, error
    assert 'changes' in data['data']
    code, data, error = run('query','activity_execution')
    assert code == 2 and 'missing_argument' in error
    code, data, error = run('query','activity_execution','--activity-id',str(uuid.uuid4()))
    assert code == 4 and 'activity_not_found' in error


def test_coach_router_and_structured_fields(cli_db):
    import asyncio
    import json

    from fastapi import HTTPException
    from starlette.requests import Request

    from app.main import app, handle_http
    assert '/api/v1/coach/proposals' in app.openapi()['paths']
    response = asyncio.run(handle_http(Request({'type':'http'}), HTTPException(422,detail={
        'code':'proposal_invalid_subset','message':'Invalid subset',
        'fields':[{'code':'V9.strength_count','path':'changes.1','message':'Preserve strength'}]})))
    assert json.loads(response.body)['error']['fields'][0]['path'] == 'changes.1'


def test_snapshot_kb_integrity_exit_4(cli_db, tmp_path, monkeypatch):
    import shutil

    from app.services import knowledge
    run, session = cli_db
    _, document = snapshot_doc(run, session)
    before = session.scalar(select(func.count()).select_from(CoachSnapshot))
    kb = tmp_path / 'kb'
    shutil.copytree(knowledge.DEFAULT_ROOT, kb)
    workflow = kb / 'workflows' / 'weekly_review.md'
    workflow.write_bytes(workflow.read_bytes() + b' ')
    monkeypatch.setattr(knowledge, 'DEFAULT_ROOT', kb)
    for args in [('snapshot', '--operation', 'review_rolling_plan'),
                 ('submit', '--file', write_doc(tmp_path, document))]:
        code, result, error = run(*args)
        assert code == 4 and result is None and 'knowledge_unavailable' in error
    assert session.scalar(select(func.count()).select_from(CoachSnapshot)) == before
    assert session.scalar(select(func.count()).select_from(CoachProposal)) == 0
    from app.api.metrics import recovery_nights
    assert recovery_nights(session, TODAY - timedelta(days=1), TODAY)['end'] == TODAY


def test_snapshot_excludes_checkin_notes(cli_db):
    from app.checkin_models import Checkin, SymptomReport
    run, session = cli_db
    checkin = Checkin(idempotency_key=str(uuid.uuid4()), kind='exception', observed_at=NOW-timedelta(hours=30),
        context_tags=[], note='cli-private-canary', gait_change='no')
    session.add(checkin)
    session.flush()
    session.add(SymptomReport(checkin_id=checkin.id, site='ankle', side='left', severity=2, timing='next_morning'))
    session.commit()
    code, result, error = run('snapshot', '--operation', 'review_rolling_plan')
    assert code == 0, error
    assert 'cli-private-canary' not in str(result)
    assert any(report['severity'] == 2 for report in result['payload']['symptoms']['reports'])
