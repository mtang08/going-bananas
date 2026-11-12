"""Read-only smoke check against a running local app; never dumps response bodies."""
import argparse
import json
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

parser=argparse.ArgumentParser()
parser.add_argument('--base-url',default='http://127.0.0.1:8000')
parser.add_argument('--mode',choices=['demo','test','real'],required=True)
args=parser.parse_args()
parsed=urlparse(args.base_url)
if parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost'} or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'','/'}:
    raise SystemExit('Only a local server may be smoke tested')
args.base_url=args.base_url.rstrip('/')
paths=['health/live','health/ready','profile','activities','summary','recovery','checkins','manual-sessions','plans','conflicts','sync/status','weekly-summary','context','coach/daily','coach/weekly',
       'coach/context?workflow=daily','strength/years',
       'strength/history?start_date=2026-01-01&end_date=2026-11-10']
with urlopen(args.base_url+'/api/v1/profile',timeout=15) as response:
    profile=json.load(response)
authority=profile['data'].get('planning_authority','legacy')
if authority=='calendar':
    paths += ['calendar','calendar/versions','prompts','coach/v2/daily',
              'metrics/windows','metrics/recovery','anchors','goals','events',
              'strength-routine','blocks/active','coach/proposals']
for path in paths:
    with urlopen(args.base_url+'/api/v1/'+path,timeout=15) as response:
        assert response.status==200,path
        data=json.load(response)
        assert data['mode']==args.mode,path
        assert 'data' in data and 'data_revision' in data,path
        encoded=json.dumps(data).lower()
        for forbidden in ['access_token','api_key','latitude','longitude']:
            assert forbidden not in encoded, 'private field in '+path
    print(path+': OK')
# Host and foreign-origin checks must precede mutations and body validation.
request=Request(args.base_url+'/api/v1/checkins',data=b'{}',headers={'Origin':'https://foreign.example','Content-Type':'application/json','X-Local-Request':'1'},method='POST')
try:
    urlopen(request,timeout=15)
except HTTPError as exc:
    assert exc.code==403, f'foreign origin returned {exc.code}'
else:
    raise AssertionError('foreign mutation accepted')
print('foreign-origin mutation: rejected')
