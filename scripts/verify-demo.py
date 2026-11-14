"""Cross-layer acceptance check. Mutates ONLY an explicitly demo-mode server."""
import argparse
import json
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
from urllib.parse import urlparse

parser=argparse.ArgumentParser()
parser.add_argument('--base-url',default='http://127.0.0.1:8000')
args=parser.parse_args()
parsed=urlparse(args.base_url)
if parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost'} or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'','/'}:
    raise SystemExit('Only a local HTTP server may be verified')
origin=args.base_url.rstrip('/')
base=origin+'/api/v1'
def request(path, body=None, method=None, expected=200):
    headers={'Content-Type':'application/json','X-Local-Request':'1','Origin':origin}
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
if profile.get('planning_authority')!='calendar':
    raise SystemExit('Calendar planning authority required; run planning-cutover first.')
calendar=request('/calendar')
assert calendar['head'] >= 2 and len({s['local_date'] for s in calendar['sessions'] if s['local_date'] >= calendar['today']}) <= 14
original_head=calendar['head']
request('/calendar/edits',{'expected_head':original_head-1,'edits':[]},'POST',409)
editable=next(s for s in calendar['sessions'] if s['local_date'] >= calendar['today'] and not s['locked'] and s.get('activity_id') is None)
changed=request('/calendar/edits',{'expected_head':original_head,'edits':[{'op':'modify','session_uid':editable['session_uid'],'fields':{'notes':'synthetic verify note'}}]},'POST',201)
assert changed['version']==original_head+1
restored=request('/calendar/rollback',{'expected_head':changed['version'],'to_version':original_head,'reason':'synthetic verify restore'},'POST',201)
assert restored['version']==changed['version']+1
request('/calendar/bootstrap',{'anchor_date':profile['cycle_anchor'],'start_date':calendar['today'],'pattern':{'quality':1,'long':1}},'POST',409)
checkin_body={'idempotency_key':str(uuid4()),'kind':'exception','observed_at':datetime.now(timezone.utc).isoformat(),
              'fatigue':7,'illness':None,'gait_change':None,'context_tags':[],'symptoms':[],
              'activity_id':None,'prompt_id':None,'note':'synthetic-private-note-canary'}
checkin=request('/v2/checkins',checkin_body,'POST',201)
assert request('/v2/checkins',checkin_body,'POST')['id']==checkin['id']
guidance=request('/coach/v2/daily/request',{},'POST')
assert guidance['decision']=='modify'
reloaded=request('/coach/v2/daily')
assert reloaded['id']==guidance['id']
today=date.fromisoformat(calendar['today'])
historical=request('/calendar?start='+str(today-timedelta(days=14))+'&end='+str(today+timedelta(days=13)))
def execution(days_ago):
    planned=next(s for s in historical['sessions'] if s['local_date']==str(today-timedelta(days=days_ago)) and s['kind']=='run')
    completed=next(c for c in historical['completions'] if c['session_uid']==planned['session_uid'])
    return request('/activities/'+completed['activity_id']+'/execution'),completed['activity_id']
structured,_=execution(6)
assert len(structured['intervals']['value']['reps'])==4
mismatch,_=execution(12)
assert mismatch['intervals']['status']=='not_assessable' and 'WATCH_WORKOUT_MISMATCH' in mismatch['intervals']['reason_codes']
rated,rated_id=execution(10)
assert rated['rpe']['effective']==4.0
request('/activities/'+rated_id+'/rpe',{'rpe':-1},'PUT',422)
request('/activities/'+rated_id+'/rpe',{'rpe':11},'PUT',422)
print('Calendar demo acceptance: stale head, edit/rollback, bootstrap conflict, check-in replay, persisted guidance and privacy passed.')
raise SystemExit(0)
