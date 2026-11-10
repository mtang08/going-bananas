"""Compare archive history and pre-import API baseline without exposing raw records."""
import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
import sys
from zipfile import ZipFile
from zoneinfo import ZoneInfo

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from sqlalchemy import select,func
from app.config import settings
from app.db import SessionLocal
from app.models import Activity,RecoveryObservation,ProfileVersion,Checkin,PlanVersion,RawObject

args=argparse.ArgumentParser()
args.add_argument('archive',type=Path)
opts=args.parse_args()
assert settings.app_mode=='real'
baseline=json.loads((settings.private_dir/'pre-export-baseline.json').read_text())
with ZipFile(opts.archive) as z:
    member=next(n for n in z.namelist() if n.endswith('summarizedActivities.json'))
    rows=json.loads(z.read(member))[0]['summarizedActivitiesExport']
    expected_recovery={}
    for name in z.namelist():
        metric = ('sleep' if name.endswith('_sleepData.json') else
                  'hrv' if name.endswith('_healthStatusData.json') else
                  'resting_hr' if Path(name).name.startswith('UDSFile_') and name.endswith('.json') else None)
        if metric is None:
            continue
        for row in json.loads(z.read(name)):
            day=row.get('calendarDate')
            if not day:
                continue
            value=None
            if metric=='sleep' and all(row.get(k) is not None for k in
                    ['sleepStartTimestampGMT','sleepEndTimestampGMT','awakeSleepSeconds']):
                start=datetime.fromisoformat(row['sleepStartTimestampGMT'].replace('Z','+00:00'))
                end=datetime.fromisoformat(row['sleepEndTimestampGMT'].replace('Z','+00:00'))
                value=(end-start).total_seconds()-row['awakeSleepSeconds']
            elif metric=='resting_hr':
                value=row.get('restingHeartRate')
            elif metric=='hrv':
                values=[v['value'] for v in row.get('metrics',[]) if v.get('type')=='HRV']
                if len(values)==1:
                    value=values[0]
            if value is not None and value>0:
                expected_recovery[f'{metric}:{day}']=value
expected_ids=set(baseline['activities'])|{str(r['activityId']) for r in rows}
with SessionLocal() as s:
    activities=s.scalars(select(Activity)).all()
    actual={r.garmin_id:r for r in activities}
    assert len(actual)==len(activities)==len(expected_ids) and set(actual)==expected_ids
    for key,fields in baseline['activities'].items():
        a=actual[key]
        for field,value in fields.items():
            assert str(getattr(a,field))==value,f'Prior API field changed: {field}'
    independent_total=0.0
    for raw in rows:
        a=actual[str(raw['activityId'])]
        if str(raw['activityId']) not in baseline['activities']:
            assert a.start_at==datetime.fromtimestamp(raw['startTimeGmt']/1000,UTC)
            for origin,field,divisor in [('distance','distance_m',100),('elapsedDuration','elapsed_s',1000),('movingDuration','moving_s',1000)]:
                if raw.get(origin) is not None:assert math.isclose(getattr(a,field),raw[origin]/divisor,rel_tol=1e-10,abs_tol=1e-6)
        if a.sport in {'running','treadmill_running','trail_running'}:
            independent_total+=float(baseline['activities'][str(raw['activityId'])]['distance_m']) if str(raw['activityId']) in baseline['activities'] else (raw.get('distance') or 0)/100
    canonical_total=sum(a.distance_m or 0 for a in activities if a.sport in {'running','treadmill_running','trail_running'})
    assert math.isclose(independent_total,canonical_total,rel_tol=1e-10,abs_tol=1e-6)
    recovery={f'{r.metric}:{r.source_date}':r.value for r in s.scalars(select(RecoveryObservation))}
    expected_recovery.update(baseline['recovery'])
    assert set(recovery)==set(expected_recovery),'Recovery date coverage differs'
    for key,value in expected_recovery.items():
        assert math.isclose(recovery[key],value,rel_tol=1e-10,abs_tol=1e-6),'Recovery source value differs'
    for key,value in baseline['recovery'].items(): assert recovery[key]==value,'Prior API recovery changed'
    for m in [ProfileVersion,Checkin,PlanVersion]:
        assert s.scalar(select(func.count()).select_from(m))==baseline['user_counts'][m.__tablename__]
    raws=s.scalars(select(RawObject)).all()
    for raw in raws:
        file=settings.private_dir/raw.relative_path
        with file.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==raw.sha256
    dates=[a.start_at.astimezone(ZoneInfo('America/New_York')).date() for a in activities]
    output={'activities':len(activities),'activity_dates':[str(min(dates)),str(max(dates))],
            'runs':sum(a.sport in {'running','treadmill_running','trail_running'} for a in activities),
            'recovery_observations':len(recovery),'prior_api_and_user_data_unchanged':True,
            'raw_objects_checksum_verified':len(raws),'independent_run_volume_matches':True,
            'all_recovery_values_match_source':True}
    print(json.dumps(output))
