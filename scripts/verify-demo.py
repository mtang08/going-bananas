"""Cross-layer acceptance check. Mutates ONLY an explicitly demo-mode server."""
import json
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

base='http://127.0.0.1:8000/api/v1'
def request(path, body=None, method=None, expected=200):
    headers={'Content-Type':'application/json','X-Local-Request':'1','Origin':'http://127.0.0.1:8000'}
    req=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
    try:
        response=urlopen(req,timeout=15)
    except HTTPError as error:
        assert error.code==expected,(path,error.code,expected)
        return None
    assert response.status==expected,(path,response.status,expected)
    payload=json.load(response)
    assert payload['mode']=='demo','Refusing to mutate non-demo app'
    return payload['data']

assert request('/health/live')['status']=='ok'
profile=request('/profile')
# Explicitly synthetic configuration; do not infer athlete's actual cycle.
profile.update(expected_version=profile.pop('version'),cycle_anchor='2026-11-02',anchor_confirmed=True,strength_days_confirmed=True,scheduled_strength_days=[0,4])
request('/profile',profile,'PUT')
now=datetime.now(timezone.utc)
idempotency=str(uuid4())
body={'idempotency_key':idempotency,'observed_at':now.isoformat(),'symptoms':'none','gait':'normal','feeling':'usual','note':'synthetic-private-note-canary'}
checkin=request('/checkins',body,'POST',201)
assert request('/checkins',body,'POST')['id']==checkin['id']
changed=request('/checkins/'+checkin['id'],{'expected_version':1,'symptoms':'mild'},'PATCH')
assert changed['version']==2 and changed['symptoms']=='mild'
request('/checkins/'+checkin['id'],{'expected_version':1,'symptoms':'none'},'PATCH',409)
request('/checkins/'+checkin['id'],{'expected_version':2,'observed_at':None},'PATCH',422)
context=request('/context')
assert 'synthetic-private-note-canary' not in json.dumps(context)
# A real manual strength record must contribute to the same overview metrics.
local_day=now.astimezone().date().isoformat()
before=request('/summary')['selected']['strength_count']
manual=request('/manual-sessions',{'date':local_day,'kind':'strength','duration_s':1800},'POST',201)
assert request('/summary')['selected']['strength_count']==before+1
monday=(now.astimezone().date()-timedelta(days=now.astimezone().weekday())).isoformat()
snapshot=request('/weekly-snapshots',{'week_start':monday},'POST',201)
assert snapshot['summary']['summary']['strength_count']>=1
sessions=[{'date':f'2026-11-{day:02}','kind':'run'} for day in (2,4,6,8,10,12,14)]
sessions += [{'date':f'2026-11-{day:02}','kind':'strength'} for day in (2,6,9,13)]
plan=request('/plans',{'start_date':'2026-11-02','end_date':'2026-11-15','sessions':sessions},'POST',201)
accepted=request('/plans/'+plan['id']+'/accept',{'expected_version':plan['version']},'POST')
assert accepted['status']=='accepted'
invalid=request('/plans',{'start_date':'2026-11-02','end_date':'2026-11-15','sessions':sessions+[{'date':'2026-11-03','kind':'run'}]},'POST',201)
request('/plans/'+invalid['id']+'/accept',{'expected_version':invalid['version']},'POST',422)
print('Demo acceptance: feedback retry/edit/version conflict/privacy, manual strength metrics, weekly snapshot, valid/invalid cycle plans passed.')
