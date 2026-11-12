"""Persisted weekly -> daily -> actual -> next context, using synthetic observations."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.agent_models import CoachPlanRevision
from app.config import settings
from app.db import engine, get_session
from app.main import app
from app.models import (
    Activity,
    Checkin,
    CompletionLink,
    PlannedSession,
    PlanVersion,
    ProfileVersion,
    RecoveryObservation,
    SourceAccount,
)
from app.services.agent_plans import Proposal, validate_proposal

HEADERS = {'X-Local-Request': '1', 'Origin': 'http://testserver'}


@pytest.mark.parametrize(('distances', 'rejected'), [([8] * 6, False), ([8] * 7, True), ([8.1], True)])
def test_distance_bounds_include_equality_and_aggregate(distances, rejected):
    today = datetime.now(UTC).date()
    # Six observed 5 km runs give a 48 km aggregate bound and an 8 km
    # per-session bound. Keep these observations independent of DB fixtures.
    state = {'as_of': today.isoformat(), 'evidence_hash': '0' * 64, 'current_revision_id': None,
        'context': {'profile': {'cycle_anchor': today, 'anchor_confirmed': True, 'strength_days_confirmed': True},
            'timezone': 'UTC', 'recent_checkins': [], 'recurring_sessions': [],
            'recent_activities': [{'id': str(uuid.uuid4()), 'sport': 'running', 'distance_m': 5000,
                'elapsed_s': 1800, 'local_date': (today-timedelta(days=2*i+2)).isoformat()} for i in range(6)],
            'run_opportunities': [{'date': (today+timedelta(days=2*i)).isoformat()} for i in range(7)]}}
    body = proposal(state)
    for index, item in enumerate(body['sessions']):
        item['target'].pop('duration_minutes')
        if index < len(distances):
            item['target']['distance_km'] = distances[index]
        else:
            item['target']['intent'] = 'rest'
    if rejected:
        with pytest.raises(HTTPException) as error:
            validate_proposal(Proposal.model_validate(body), state['context'], [])
        assert error.value.detail['code'] == 'load_jump'
    else:
        assert validate_proposal(Proposal.model_validate(body), state['context'], []) == []


@pytest.fixture
def agent_client():
    assert settings.app_mode == 'test'
    assert settings.database_url.endswith('_test')
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
            # All setup and endpoint commits remain beneath the outer rollback.
            session.execute(delete(CoachPlanRevision))
            for plan in session.scalars(select(PlanVersion).where(PlanVersion.status == 'accepted')):
                plan.status = 'superseded'
            now = datetime.now(UTC)
            today = now.astimezone(ZoneInfo('America/New_York')).date()
            version = (session.scalar(select(func.max(ProfileVersion.version))) or 0) + 1
            session.add(ProfileVersion(version=version, effective_at=now-timedelta(days=365), timezone='America/New_York',
                cycle_anchor=today, anchor_confirmed=True, strength_days_confirmed=True,
                strength_schedule_mode='alternating', strength_week_a_start=today-timedelta(days=today.weekday()),
                strength_week_a_days=[0, 4], strength_week_b_days=[1, 5], mobility_week_a_days=[2],
                mobility_week_b_days=[3], mobility_optional_days=[6], facts={}, preferences={}, unknowns=[]))
            account = SourceAccount(provider='synthetic_agent_test', account_scope=str(uuid.uuid4()))
            session.add(account)
            session.flush()
            run_ids = []
            for offset in range(2, 15, 2):
                start = datetime.combine(today-timedelta(days=offset), time(12),
                    tzinfo=ZoneInfo('America/New_York')).astimezone(UTC)
                run = Activity(source_account_id=account.id, source_identity=str(uuid.uuid4()), start_at=start,
                    original_start=start.isoformat(), local_date=start.astimezone(ZoneInfo('America/New_York')).date(),
                    sport='running', distance_m=5000, elapsed_s=1800, moving_s=1750, avg_hr_bpm=140)
                session.add(run)
                session.flush()
                run_ids.append(str(run.id))
            for offset in range(35):
                session.add(RecoveryObservation(source_account_id=account.id, metric='resting_hr', source_date=today-timedelta(days=offset),
                    time_semantics='calendar_day', value=50+(offset % 3), unit='bpm', statistic='daily', source_revision='test'))
            session.commit()

        def override():
            with Session(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as request_session:
                yield request_session
        app.dependency_overrides[get_session] = override
        try:
            with TestClient(app) as client:
                yield client, connection, today, run_ids
        finally:
            app.dependency_overrides.pop(get_session, None)
            transaction.rollback()


def context(client, workflow):
    response = client.get('/api/v1/coach/agent/context', params={'workflow': workflow})
    assert response.status_code == 200, response.text
    return response.json()['data']


def proposal(state, workflow='weekly', minutes=30):
    return {'workflow': workflow, 'as_of': state['as_of'], 'evidence_hash': state['evidence_hash'],
        'expected_revision_id': state['current_revision_id'], 'idempotency_key': str(uuid.uuid4()),
        'summary': 'Consolidate recent running tolerance', 'rationale': 'Observed easy runs support maintaining familiar exposure.',
        'source_ids': ['S001'], 'review': {
            'actual_vs_plan': 'Recent actual runs are visible; missing completion links remain unknown.',
            'progression': 'Hold the familiar duration while establishing response.',
            'recovery': 'Compare resting HR with the available individual baseline.',
            'symptoms': 'No normal symptoms are inferred from missing reports.',
            'strength': 'Preserve the confirmed alternating strength rotation.',
            'weekly_strategy': 'Consistency before progression; no compressed make-up sessions.',
            'uncertainty': ['Effort and delayed symptoms remain unknown.'], 'follow_up': ['Report next-day response.'],
            'evidence': [{'activity_ids': [str(state['context']['recent_activities'][0]['id'])], 'source_ids': ['S001']}]},
        'sessions': [{'date': slot['date'], 'kind': 'run', 'target': {
            'intent': 'easy', 'purpose': 'Consolidate tolerated aerobic exposure',
            'prescription': f'Run {minutes} minutes on familiar even terrain; stop for worsening symptoms.',
            'intensity': 'Conversational effort without a pace target.', 'duration_minutes': minutes,
            'reason': 'Recent completed runs provide a familiar exposure baseline.'}}
            for slot in state['context']['run_opportunities']] if workflow == 'weekly' else []}


def post(client, body):
    response = client.post('/api/v1/coach/agent/proposals', json=body, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()['data']


def test_persisted_weekly_daily_calendar_feedback_loop(agent_client):
    client, connection, today, run_ids = agent_client
    initial = context(client, 'weekly')
    assert any(a.get('avg_hr_bpm') == 140 and a.get('moving_pace_s_per_km') == 350 for a in initial['context']['recent_activities'])
    baseline = initial['context']['recovery_baselines']['metrics']['resting_hr']
    assert baseline['baseline_count'] >= 28 and baseline['recent_7_count'] >= 7
    assert initial['context']['previous_completed_week']['plan_comparison']['completed'].get('run', 0) == 0
    body = proposal(initial)
    weekly = post(client, body)
    assert weekly['revision']['engine'] == 'codex_skill.v1'
    plan_id = weekly['plan']['id']
    runs = [s for s in weekly['plan']['sessions'] if s['kind'] == 'run']
    assert len(runs) == 7 and all(s['target']['duration_minutes'] == 30 for s in runs)
    commitments = [s for s in weekly['plan']['sessions'] if s['kind'] != 'run']
    assert sum(s['kind'] == 'strength' for s in commitments) == 4
    calendar = client.get('/api/v1/plans', params={'start_date': str(today), 'end_date': str(today+timedelta(days=13))}).json()['data']
    assert any(p['id'] == plan_id for p in calendar['items'] if p['status'] == 'accepted')
    # Our own activation changes context but never constitutes new training evidence.
    refreshed = context(client, 'weekly')
    assert refreshed['evidence_hash'] == initial['evidence_hash']
    changed_request = proposal(refreshed, minutes=25)
    duplicate = post(client, changed_request)
    assert duplicate['revision']['id'] == weekly['revision']['id'] and duplicate['unchanged']
    daily_state = context(client, 'daily')
    assert daily_state['context']['active_weekly_strategy']
    confirmed = post(client, proposal(daily_state, 'daily'))
    assert confirmed['unchanged'] and confirmed['plan']['id'] == plan_id
    assert connection.exec_driver_sql('SELECT count(*) FROM coach_plan_revisions').scalar_one() == 2
    # A reported response is new evidence and daily adjustment has a concrete target.
    checkin = client.post('/api/v1/checkins', headers=HEADERS, json={'idempotency_key': str(uuid.uuid4()),
        'observed_at': datetime.now(UTC).isoformat(), 'symptoms': 'mild', 'change': 'same', 'gait': 'normal', 'feeling': 'tired'})
    assert checkin.status_code == 201, checkin.text
    fresh_daily = context(client, 'daily')
    adjust = proposal(fresh_daily, 'daily')
    adjust['sessions'] = proposal(fresh_daily, minutes=20)['sessions'][:1]
    adjusted = post(client, adjust)
    assert adjusted['plan']['id'] != plan_id and not adjusted['unchanged']
    retained = [s for s in adjusted['plan']['sessions'] if s['kind'] != 'run']
    assert {s['id'] for s in retained} == {s['id'] for s in commitments}
    # Unchanged sessions preserve their owner and completion reference across versions.
    original_future = next(s for s in runs if s['date'] != str(today))
    with Session(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
        session.add(CompletionLink(planned_session_id=uuid.UUID(original_future['id']), activity_id=uuid.UUID(run_ids[0])))
        session.commit()
    # Link a synthetic actual to today's newly adjusted prescription through the public path.
    active_today = next(s for s in adjusted['plan']['sessions'] if s['kind'] == 'run' and s['date'] == str(today))
    link = client.post('/api/v1/completion-links', headers=HEADERS, json={'planned_session_id': active_today['id'], 'activity_id': run_ids[1]})
    assert link.status_code == 201, link.text
    next_review = context(client, 'weekly')
    assert any(s['completion_activity_id'] == run_ids[1] for p in next_review['context']['next_14_days_plan'] for s in p['sessions'])
    assert any(r['id'] == adjusted['revision']['id'] for r in next_review['context']['prior_agent_reviews'])
    # Rollback records a new audit event and leaves completed prescriptions untouched.
    undo = client.post(f"/api/v1/coach/agent/revisions/{adjusted['revision']['id']}/rollback", headers=HEADERS,
        json={'expected_revision_id': adjusted['revision']['id'], 'reason': 'Restore the prior reviewed running exposure.'})
    assert undo.status_code == 200, undo.text
    restored = undo.json()['data']
    protected = next(s for s in restored['plan']['sessions'] if s['id'] == active_today['id'])
    assert protected['completion_activity_id'] == run_ids[1] and protected['target']['duration_minutes'] == 20


def test_reject_stale_invalid_and_protected_mutation(agent_client):
    client, _, today, _ = agent_client
    state = context(client, 'weekly')
    invalid = proposal(state)
    invalid['sessions'][0]['date'] = str(today+timedelta(days=1))
    assert client.post('/api/v1/coach/agent/proposals', json=invalid, headers=HEADERS).status_code == 422
    invalid = proposal(state, minutes=100)
    assert client.post('/api/v1/coach/agent/proposals', json=invalid, headers=HEADERS).json()['error']['code'] == 'load_jump'
    valid = proposal(state)
    valid['sessions'][0]['target']['locked'] = True
    applied = post(client, valid)
    stale = proposal(context(client, 'daily'), 'daily')
    client.post('/api/v1/checkins', headers=HEADERS, json={'idempotency_key': str(uuid.uuid4()), 'observed_at': datetime.now(UTC).isoformat(),
        'symptoms': 'none', 'gait': 'normal', 'feeling': 'usual'})
    rejected = client.post('/api/v1/coach/agent/proposals', json=stale, headers=HEADERS)
    assert rejected.status_code == 409 and rejected.json()['error']['code'] == 'stale_evidence'
    fresh = context(client, 'daily')
    change = proposal(fresh, 'daily')
    change['sessions'] = proposal(fresh, minutes=20)['sessions'][:1]
    refused = client.post('/api/v1/coach/agent/proposals', json=change, headers=HEADERS)
    assert refused.status_code == 422 and refused.json()['error']['code'] == 'protected_session'
    bad_key = dict(valid, summary='Different request under the same key')
    assert client.post('/api/v1/coach/agent/proposals', json=bad_key, headers=HEADERS).status_code == 409
    assert applied['revision']['id']


def test_downstream_adjustment_and_undo_after_confirmation(agent_client):
    client, connection, today, _ = agent_client
    weekly = post(client, proposal(context(client, 'weekly')))
    state = context(client, 'daily')
    body = proposal(state, 'daily')
    body['sessions'] = proposal(state, minutes=20)['sessions'][1:2]
    changed = post(client, body)
    assert changed['revision']['diff'][0]['date'] == str(today+timedelta(days=2))
    # Only one run is revised; remaining prescription and commitment IDs survive.
    old_ids = {s['id'] for s in weekly['plan']['sessions']}
    new_ids = {s['id'] for s in changed['plan']['sessions']}
    assert len(old_ids-new_ids) == 1 and len(new_ids-old_ids) == 1
    # New external response permits another decision, which confirms the plan.
    response = client.post('/api/v1/checkins', headers=HEADERS, json={'idempotency_key': str(uuid.uuid4()),
        'observed_at': datetime.now(UTC).isoformat(), 'symptoms': 'none', 'gait': 'normal', 'feeling': 'usual'})
    assert response.status_code == 201
    confirmed = post(client, proposal(context(client, 'daily'), 'daily'))
    assert confirmed['unchanged'] and confirmed['plan']['id'] == changed['plan']['id']
    history = client.get('/api/v1/coach/agent/revisions').json()['data']
    assert history['current_revision_id'] == confirmed['revision']['id']
    assert history['revertible_revision_id'] == changed['revision']['id']
    undo = client.post(f"/api/v1/coach/agent/revisions/{changed['revision']['id']}/rollback", headers=HEADERS,
        json={'expected_revision_id': confirmed['revision']['id'], 'reason': 'Restore the reviewed weekly duration.'})
    assert undo.status_code == 200, undo.text
    plan = undo.json()['data']['plan']
    session = next(s for s in plan['sessions'] if s['kind'] == 'run' and s['date'] == str(today+timedelta(days=2)))
    assert session['target']['duration_minutes'] == 30
    assert connection.exec_driver_sql('SELECT count(*) FROM coach_plan_revisions').scalar_one() == 4


def test_symptom_confirmation_actual_matching_and_spacing(agent_client):
    client, connection, today, _ = agent_client
    initial = context(client, 'weekly')
    bad = proposal(initial)
    weekday = next(s for s in bad['sessions'] if datetime.fromisoformat(s['date']).weekday() < 5)
    weekday['target']['intent'] = 'long'
    refused = client.post('/api/v1/coach/agent/proposals', json=bad, headers=HEADERS)
    assert refused.status_code == 422 and refused.json()['error']['code'] == 'long_run_weekend'
    bad = proposal(initial)
    bad['sessions'][0]['target']['intent'] = 'quality'
    bad['sessions'][1]['target']['intent'] = 'quality'
    refused = client.post('/api/v1/coach/agent/proposals', json=bad, headers=HEADERS)
    assert refused.status_code == 422 and refused.json()['error']['code'] == 'hard_spacing'
    weekly = post(client, proposal(initial))
    symptoms = client.post('/api/v1/checkins', headers=HEADERS, json={'idempotency_key': str(uuid.uuid4()),
        'observed_at': datetime.now(UTC).isoformat(), 'symptoms': 'severe', 'gait': 'affected', 'feeling': 'tired'})
    assert symptoms.status_code == 201
    state = context(client, 'daily')
    refused = client.post('/api/v1/coach/agent/proposals', json=proposal(state, 'daily'), headers=HEADERS)
    assert refused.status_code == 422 and refused.json()['error']['code'] == 'current_symptoms'
    body = proposal(state, 'daily')
    body['sessions'] = proposal(state)['sessions'][:1]
    body['sessions'][0]['target'].update({'intent': 'rest', 'purpose': 'Respect current walking symptoms',
        'prescription': 'Rest from running and seek assessment for affected walking.', 'intensity': 'No running effort.'})
    body['sessions'][0]['target'].pop('duration_minutes')
    rested = post(client, body)
    assert rested['revision']['diff'][0]['after']['intent'] == 'rest'
    # A newly synced, unlinked run prevents changing its existing prescription.
    with Session(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
        session.add(Checkin(idempotency_key=str(uuid.uuid4()), observed_at=datetime.now(UTC), symptoms='none', gait='normal', feeling='usual'))
        session.add(Activity(start_at=datetime.now(UTC)-timedelta(minutes=10), original_start='synthetic',
            local_date=today, sport='running', distance_m=3000, elapsed_s=1200, avg_hr_bpm=145))
        session.commit()
    body = proposal(context(client, 'daily'), 'daily')
    body['sessions'] = proposal(context(client, 'daily'), minutes=15)['sessions'][:1]
    refused = client.post('/api/v1/coach/agent/proposals', json=body, headers=HEADERS)
    assert refused.status_code == 422 and refused.json()['error']['code'] == 'actual_requires_matching'
    # A stale concurrency token cannot mutate later decisions.
    body = proposal(context(client, 'daily'), 'daily')
    body['expected_revision_id'] = weekly['revision']['id']
    refused = client.post('/api/v1/coach/agent/proposals', json=body, headers=HEADERS)
    assert refused.status_code == 409 and refused.json()['error']['code'] == 'revision_conflict'


def test_rest_distance_load_and_evidence_references(agent_client):
    client, _, _, _ = agent_client
    state = context(client, 'weekly')
    body = proposal(state)
    body['sessions'][0]['target']['intent'] = 'rest'
    response = client.post('/api/v1/coach/agent/proposals', json=body, headers=HEADERS)
    assert response.status_code == 422 and response.json()['error']['code'] == 'contradictory_rest'
    body = proposal(state)
    # Test the existing per-run bound against the supplied observations, which
    # may also include the integration database's other synthetic fixtures.
    observed_max_km = max(a.get('distance_m') or 0 for a in state['context']['recent_activities']
        if a.get('sport') in {'running', 'trail_running', 'treadmill_running'}
        and not a.get('annotations', {}).get('excluded')) / 1000
    for item in body['sessions']:
        item['target'].pop('duration_minutes')
        item['target']['distance_km'] = max(5, observed_max_km * 1.6) + .1
    response = client.post('/api/v1/coach/agent/proposals', json=body, headers=HEADERS)
    assert response.status_code == 422 and response.json()['error']['code'] == 'load_jump'
    body = proposal(state)
    body['review']['evidence'][0]['activity_ids'] = [str(uuid.uuid4())]
    response = client.post('/api/v1/coach/agent/proposals', json=body, headers=HEADERS)
    assert response.status_code == 422 and response.json()['error']['code'] == 'invalid_evidence'
    body = proposal(state)
    body['review']['evidence'][0]['source_ids'] = ['S999']
    response = client.post('/api/v1/coach/agent/proposals', json=body, headers=HEADERS)
    assert response.status_code == 422 and response.json()['error']['code'] == 'invalid_evidence'


@pytest.mark.parametrize('field', ['activity_ids', 'checkin_ids', 'source_ids'])
@pytest.mark.parametrize('references', [None, 12, 'S001', [12]])
def test_malformed_evidence_references_are_rejected(agent_client, field, references):
    client, connection, _, _ = agent_client
    body = proposal(context(client, 'weekly'))
    body['review']['evidence'][0][field] = references
    response = client.post('/api/v1/coach/agent/proposals', json=body, headers=HEADERS)
    assert response.status_code == 422, response.text
    assert connection.exec_driver_sql('SELECT count(*) FROM coach_plan_revisions').scalar_one() == 0


@pytest.mark.parametrize(('kind', 'offset', 'accepted'), [('strength', 0, False), ('run', -2, False), ('run', 0, True)])
def test_daily_confirmation_requires_upcoming_running_plan(agent_client, kind, offset, accepted):
    client, connection, today, _ = agent_client
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        plan = PlanVersion(status='accepted', start_date=today-timedelta(days=2),
            end_date=today+timedelta(days=13), profile_version=1, anchor_date=today)
        session.add(plan)
        session.flush()
        session.add(PlannedSession(plan_id=plan.id, date=today+timedelta(days=offset), kind=kind,
            target={'intent': 'easy', 'duration_minutes': 30} if kind == 'run' else {}))
        session.commit()
    body = proposal(context(client, 'daily'), 'daily')
    response = client.post('/api/v1/coach/agent/proposals', json=body, headers=HEADERS)
    if accepted:
        assert response.status_code == 200, response.text
        assert response.json()['data']['unchanged']
    else:
        assert response.status_code == 409, response.text
        assert response.json()['error']['code'] == 'missing_weekly_plan'
        assert connection.exec_driver_sql('SELECT count(*) FROM coach_plan_revisions').scalar_one() == 0


def test_rollback_permits_same_day_replan_and_replays_current_calendar(agent_client):
    client, connection, _, _ = agent_client
    state = context(client, 'weekly')
    body = proposal(state)
    weekly = post(client, body)
    undo = client.post(f"/api/v1/coach/agent/revisions/{weekly['revision']['id']}/rollback", headers=HEADERS,
        json={'expected_revision_id': weekly['revision']['id'], 'reason': 'Withdraw this plan and reconsider the weekly targets.'})
    assert undo.status_code == 200, undo.text
    withdrawn = undo.json()['data']
    assert all(s['target']['intent'] == 'rest' for s in withdrawn['plan']['sessions'] if s['kind'] == 'run')
    refreshed = context(client, 'weekly')
    assert refreshed['evidence_hash'] != state['evidence_hash']
    # A transport retry remains idempotent, but reports the active calendar.
    replay = post(client, body)
    assert replay['replayed'] and replay['plan']['id'] == withdrawn['plan']['id']
    assert replay['current_revision_id'] == withdrawn['revision']['id']
    assert replay['revision']['superseded_by_revision_id'] == withdrawn['revision']['id']
    # Old evidence under a different key must not return the old plan as success.
    stale = dict(body, idempotency_key=str(uuid.uuid4()))
    response = client.post('/api/v1/coach/agent/proposals', json=stale, headers=HEADERS)
    assert response.status_code == 409 and response.json()['error']['code'] == 'stale_evidence'
    replanned = post(client, proposal(refreshed, minutes=25))
    assert not replanned['unchanged'] and replanned['revision']['id'] != weekly['revision']['id']
    assert all(s['target']['duration_minutes'] == 25 for s in replanned['plan']['sessions'] if s['kind'] == 'run')
    repeated = post(client, proposal(context(client, 'weekly'), minutes=20))
    assert repeated['unchanged'] and repeated['revision']['id'] == replanned['revision']['id']
    assert repeated['plan']['id'] == replanned['plan']['id']
    assert connection.exec_driver_sql('SELECT count(*) FROM coach_plan_revisions').scalar_one() == 3


def test_weekly_change_refreshes_daily_decision_starting_point(agent_client):
    client, connection, _, _ = agent_client
    post(client, proposal(context(client, 'weekly')))
    daily_state = context(client, 'daily')
    daily_body = proposal(daily_state, 'daily')
    first_daily = post(client, daily_body)
    # New reported feedback permits a weekly revision; daily must assess its new
    # starting session even though that week's own output adds no observations.
    feedback = client.post('/api/v1/checkins', headers=HEADERS, json={'idempotency_key': str(uuid.uuid4()),
        'observed_at': datetime.now(UTC).isoformat(), 'symptoms': 'none', 'gait': 'normal', 'feeling': 'usual'})
    assert feedback.status_code == 201
    new_daily_observations = context(client, 'daily')
    confirmed = post(client, proposal(new_daily_observations, 'daily'))
    weekly = post(client, proposal(context(client, 'weekly'), minutes=25))
    refreshed_daily = context(client, 'daily')
    assert refreshed_daily['evidence_hash'] != new_daily_observations['evidence_hash']
    reevaluated = post(client, proposal(refreshed_daily, 'daily'))
    assert reevaluated['revision']['id'] not in {first_daily['revision']['id'], confirmed['revision']['id']}
    assert reevaluated['plan']['id'] == weekly['plan']['id']
    assert reevaluated['unchanged']
    repeated = post(client, proposal(context(client, 'daily'), 'daily'))
    assert repeated['revision']['id'] == reevaluated['revision']['id'] and repeated['unchanged']
    # Replaying the very first decision never returns its superseded calendar.
    old_replay = post(client, daily_body)
    assert old_replay['plan']['id'] == weekly['plan']['id']
    assert old_replay['current_revision_id'] == reevaluated['revision']['id']
    assert connection.exec_driver_sql('SELECT count(*) FROM coach_plan_revisions').scalar_one() == 5
