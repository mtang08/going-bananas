"""Read-only smoke check against a running local app; never dumps response bodies."""
import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

parser=argparse.ArgumentParser()
parser.add_argument('--base-url',default='http://127.0.0.1:8000')
parser.add_argument('--mode',choices=['demo','test','real'],required=True)
args=parser.parse_args()
if not args.base_url.startswith(('http://127.0.0.1:', 'http://localhost:')):
    raise SystemExit('Only a local server may be smoke tested')
paths=['health/live','health/ready','profile','activities','summary','recovery','checkins','manual-sessions','plans','conflicts','sync/status','weekly-summary','context']
for path in paths:
    with urlopen(args.base_url+'/api/v1/'+path,timeout=15) as response:
        assert response.status==200,path
        data=json.load(response)
        assert data['mode']==args.mode,path
        assert 'data' in data and 'data_revision' in data,path
        if path=='context':
            encoded=json.dumps(data).lower()
            for forbidden in ['access_token','api_key','latitude','longitude']:
                assert forbidden not in encoded, 'private field in context'
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
