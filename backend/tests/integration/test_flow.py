from __future__ import annotations

import uuid
from datetime import UTC, date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, get_revision
from app.main import app
from app.models import Activity
from app.services.sync import import_activity_page


def test_import_summary_feedback_and_privacy(tmp_path: Path):
    assert settings.app_mode == 'test', 'Integration tests require APP_MODE=test and TEST_DATABASE_URL'
    garmin_id = str(uuid.uuid4().int)
    record = {'ownerId': 12345, 'activityId': garmin_id, 'startTimeGMT': '2026-11-15T13:00:00Z',
              'activityType': {'typeKey': 'running'}, 'distance': 1609.344,
              'elapsedDuration': 700, 'movingDuration': 600}
    client = TestClient(app)
    distance_before = client.get('/api/v1/summary?as_of=2026-11-15&days=14').json()['data']['rolling_7']['distance_m']
    with SessionLocal() as session:
        before = get_revision(session)
        first = import_activity_page(session, tmp_path, [record], account_scope='garmin-owner:12345')
        session.commit()
        assert first['changed'] == 1
        after = get_revision(session)
        assert after == before+1
        again = import_activity_page(session, tmp_path, [record], account_scope='garmin-owner:12345')
        session.commit()
        assert again['changed'] == 0 and get_revision(session) == after
        row = session.scalar(select(Activity).where(Activity.garmin_id == garmin_id))
        assert row is not None and row.local_date == date(2026,11,15)
    summary = client.get('/api/v1/summary?as_of=2026-11-15&days=14').json()['data']
    assert abs(summary['rolling_7']['distance_m'] - distance_before - 1609.344) < 1e-8
    headers = {'X-Local-Request':'1', 'Origin':'http://testserver'}
    body = {'idempotency_key':str(uuid.uuid4()),'observed_at':'2026-11-16T09:00:00-05:00',
            'symptoms':'none','gait':'normal','feeling':'usual','note':'private-canary'}
    created = client.post('/api/v1/checkins',json=body,headers=headers)
    assert created.status_code == 201, created.text
    assert client.post('/api/v1/checkins',json=body,headers=headers).json()['data']['id'] == created.json()['data']['id']
    assert client.patch('/api/v1/checkins/'+created.json()['data']['id'],json={'expected_version':1,'observed_at':None},headers=headers).status_code == 422
    context = client.get('/api/v1/context?as_of=2026-11-16').text
    assert 'private-canary' not in context
    assert client.post('/api/v1/checkins',json=body,headers={**headers,'Origin':'https://foreign.example'}).status_code == 403



def test_server_error_redacts_canary():
    from app.db import get_session
    def broken_session():
        raise RuntimeError('secret-canary-value')
    app.dependency_overrides[get_session] = broken_session
    try:
        response = TestClient(app, raise_server_exceptions=False).get('/api/v1/profile')
        assert response.status_code == 500
        assert response.json()['error']['code'] == 'internal_error'
        assert 'secret-canary-value' not in response.text
    finally:
        app.dependency_overrides.clear()


def test_conflict_merge_reverse_and_keep_separate():
    from datetime import datetime

    from app.models import Conflict
    assert settings.app_mode == 'test'
    with SessionLocal() as session:
        a = Activity(start_at=datetime(2026,11,14,13,tzinfo=UTC), original_start='2026-11-14T13:00:00Z',
                     local_date=date(2026,11,14), sport='running', distance_m=1000,
                     resolution_state='pending')
        b = Activity(start_at=datetime(2026,11,14,13,1,tzinfo=UTC), original_start='2026-11-14T13:01:00Z',
                     local_date=date(2026,11,14), sport='running', distance_m=1000,
                     resolution_state='pending')
        session.add_all([a,b])
        session.flush()
        conflict = Conflict(kind='possible_duplicate', activity_ids=[str(a.id),str(b.id)], details={})
        session.add(conflict)
        session.commit()
        ids = str(conflict.id), str(a.id), str(b.id)
    client = TestClient(app)
    endpoint = '/api/v1/conflicts/'+ids[0]+'/resolve'
    headers = {'X-Local-Request':'1','Origin':'http://testserver'}
    before = client.get('/api/v1/summary?as_of=2026-11-15&days=14').json()['data']['rolling_7']['distance_m']
    assert client.post(endpoint,json={'resolution':'merge','canonical_activity_id':ids[1]},headers=headers).status_code == 200
    merged = client.get('/api/v1/summary?as_of=2026-11-15&days=14').json()['data']['rolling_7']['distance_m']
    assert merged-before == 1000
    assert client.post(endpoint,json={'resolution':'reverse'},headers=headers).status_code == 200
    reversed_total = client.get('/api/v1/summary?as_of=2026-11-15&days=14').json()['data']['rolling_7']['distance_m']
    assert reversed_total == before
    assert client.post(endpoint,json={'resolution':'keep_separate'},headers=headers).status_code == 200
    separate = client.get('/api/v1/summary?as_of=2026-11-15&days=14').json()['data']['rolling_7']['distance_m']
    assert abs(separate-before-2000) < 1e-8


def test_partial_week_plan_cannot_bypass_strength_requirement():
    assert settings.app_mode == 'test'
    client = TestClient(app)
    headers = {'X-Local-Request': '1', 'Origin': 'http://testserver'}
    profile = client.get('/api/v1/profile').json()['data']
    edited = {**profile, 'expected_version': profile['version'], 'cycle_anchor': '2026-11-02',
              'anchor_confirmed': True, 'strength_days_confirmed': True,
              'scheduled_strength_days': [0, 4]}
    edited.pop('version')
    assert client.put('/api/v1/profile', json=edited, headers=headers).status_code == 200
    draft = client.post('/api/v1/plans', json={'start_date': '2026-11-04', 'end_date': '2026-11-06',
        'sessions': [{'date':'2026-11-04','kind':'run'}, {'date':'2026-11-06','kind':'run'},
                     {'date':'2026-11-05','kind':'strength'}]}, headers=headers)
    assert draft.status_code == 201, draft.text
    plan_id = draft.json()['data']['id']
    accept = client.post('/api/v1/plans/'+plan_id+'/accept', json={'expected_version':1}, headers=headers)
    assert accept.status_code == 422
    assert accept.json()['error']['code'] == 'plan_invalid'


def test_manual_strength_overlap_both_arrival_orders(tmp_path: Path):
    from datetime import timedelta
    assert settings.app_mode == 'test'
    client = TestClient(app)
    headers = {'X-Local-Request': '1', 'Origin': 'http://testserver'}
    base_day = date(2024, 1, 1) + timedelta(days=uuid.uuid4().int % 650)
    for manual_first, day in [(False, base_day), (True, base_day + timedelta(days=1))]:
        record = {'ownerId':12345, 'activityId':str(uuid.uuid4().int),
                  'startTimeGMT': day.isoformat()+'T13:00:00Z',
                  'activityType':{'typeKey':'strength_training'}, 'elapsedDuration':1800}
        if manual_first:
            manual = client.post('/api/v1/manual-sessions', json={'date':day.isoformat(),
                'kind':'strength','duration_s':1800,'note':'synthetic lift note'}, headers=headers).json()['data']
        with SessionLocal() as session:
            import_activity_page(session, tmp_path, [record], account_scope='garmin-owner:12345')
            session.commit()
        if not manual_first:
            manual = client.post('/api/v1/manual-sessions', json={'date':day.isoformat(),
                'kind':'strength','duration_s':1800,'note':'synthetic lift note'}, headers=headers).json()['data']
        conflicts = client.get('/api/v1/conflicts').json()['data']['items']
        conflict = next(c for c in conflicts if c['manual_session_id'] == manual['id'])
        assert conflict['status'] == 'open' and conflict['kind'] == 'manual_import_overlap'
        before = client.get('/api/v1/summary?as_of='+day.isoformat()+'&days=1').json()['data']['selected']
        assert before['strength_count'] == 1
        activity_id = conflict['activity_ids'][0]
        resolved = client.post('/api/v1/conflicts/'+conflict['id']+'/resolve',
            json={'resolution':'merge','canonical_activity_id':activity_id}, headers=headers)
        assert resolved.status_code == 200
        after = client.get('/api/v1/summary?as_of='+day.isoformat()+'&days=1').json()['data']['selected']
        assert after['strength_count'] == 1
        detail = client.get('/api/v1/manual-sessions?start_date='+day.isoformat()+'&end_date='+day.isoformat()).json()['data']['items']
        assert any(item['id'] == manual['id'] and item['note'] == 'synthetic lift note' and
                   item['linked_activity_id'] == activity_id for item in detail)


def test_partial_overlap_rejected_without_losing_accepted_days():
    assert settings.app_mode == 'test'
    client = TestClient(app)
    headers = {'X-Local-Request':'1','Origin':'http://testserver'}
    profile = client.get('/api/v1/profile').json()['data']
    if not (profile['anchor_confirmed'] and profile['cycle_anchor'] == '2026-11-02'):
        edited = {**profile, 'expected_version':profile['version'], 'cycle_anchor':'2026-11-02',
                  'anchor_confirmed':True, 'strength_days_confirmed':True, 'scheduled_strength_days':[0,4]}
        edited.pop('version')
        assert client.put('/api/v1/profile',json=edited,headers=headers).status_code == 200
    full = client.post('/api/v1/plans',json={'start_date':'2026-12-07','end_date':'2026-12-13',
        'sessions':[{'date':f'2026-12-{day:02}','kind':'run'} for day in (8,10,12)] +
                   [{'date':f'2026-12-{day:02}','kind':'strength'} for day in (7,11)]},headers=headers)
    assert full.status_code == 201
    full_id = full.json()['data']['id']
    assert client.post('/api/v1/plans/'+full_id+'/accept',json={'expected_version':1},headers=headers).status_code == 200
    partial = client.post('/api/v1/plans',json={'start_date':'2026-12-08','end_date':'2026-12-10',
        'sessions':[{'date':'2026-12-08','kind':'run'},{'date':'2026-12-10','kind':'run'}]},headers=headers)
    assert partial.status_code == 201
    response = client.post('/api/v1/plans/'+partial.json()['data']['id']+'/accept',
                           json={'expected_version':1},headers=headers)
    assert response.status_code == 422 and response.json()['error']['code'] == 'overlapping_plan'
    plans = client.get('/api/v1/plans?start_date=2026-12-07&end_date=2026-12-13').json()['data']['items']
    original = next(item for item in plans if item['id'] == full_id)
    assert original['status'] == 'accepted'
    assert any(item['date'] == '2026-12-11' and item['kind'] == 'strength' for item in original['sessions'])


def test_strong_coverage_recap_and_context():
    assert settings.app_mode == 'test'
    client = TestClient(app)
    headers = {'X-Local-Request':'1','Origin':'http://testserver'}
    profile = client.get('/api/v1/profile').json()['data']
    edited = {**profile, 'expected_version':profile['version'],
              'preferences':{**profile['preferences'],'strength_source':'strong'}}
    edited.pop('version')
    assert client.put('/api/v1/profile',json=edited,headers=headers).status_code == 200
    summary = client.get('/api/v1/summary?as_of=2026-12-13&days=7').json()['data']
    assert summary['strength_coverage']['reason'] == 'strong_not_connected'
    assert summary['strength_coverage']['complete'] is False
    weekly = client.get('/api/v1/weekly-summary?week_start=2026-12-07').json()['data']
    assert weekly['plan_comparison']['planned']['run'] == 3
    assert weekly['plan_comparison']['planned']['strength'] == 2
    assert weekly['plan_comparison']['unlinked']['strength'] == 2
    assert weekly['strength_coverage']['reason'] == 'strong_not_connected'
    assert weekly['missingness']['recovery_missing_dates']['hrv'] == 7
    context = client.get('/api/v1/context?as_of=2026-12-13').json()['data']
    assert context['strength_coverage']['reason'] == 'strong_not_connected'
    assert 'recovery' in context


def test_checkin_and_manual_cursor_pages():
    assert settings.app_mode == 'test'
    client = TestClient(app)
    headers = {'X-Local-Request':'1','Origin':'http://testserver'}
    for hour in (9,10):
        body = {'idempotency_key':str(uuid.uuid4()), 'observed_at':f'2026-10-20T{hour:02}:00:00-04:00',
                'symptoms':'none','gait':'normal','feeling':'usual'}
        assert client.post('/api/v1/checkins',json=body,headers=headers).status_code == 201
        assert client.post('/api/v1/manual-sessions',json={'date':'2026-10-20','kind':'mobility'},
                           headers=headers).status_code == 201
    for path in ('checkins','manual-sessions'):
        page1 = client.get(f'/api/v1/{path}?start_date=2026-10-20&end_date=2026-10-20&limit=1').json()['data']
        assert len(page1['items']) == 1 and page1['truncated'] and page1['next_cursor']
        page2 = client.get(f'/api/v1/{path}?start_date=2026-10-20&end_date=2026-10-20&limit=1',
                           params={'cursor':page1['next_cursor']}).json()['data']
        assert page2['items'][0]['id'] != page1['items'][0]['id']
