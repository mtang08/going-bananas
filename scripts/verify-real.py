"""Private source comparison: prints outcomes/counts, never source payloads."""
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from sqlalchemy import select
from app.config import settings
from app.db import SessionLocal
from app.models import Activity, RawObject, RecoveryObservation, SourceRecord, SyncState
from app.api.core import get_summary

assert settings.app_mode=='real','Real mode required'
with SessionLocal() as session:
    rows=session.scalars(select(Activity).order_by(Activity.start_at)).all()
    assert rows,'No real activity imported'
    ids=[(str(r.source_account_id),r.garmin_id) for r in rows]
    assert len(ids)==len(set(ids)),'Duplicate provider identity'
    checked=0
    for row in rows:
        for field,sourcefield in [('distance_m','distance'),('elapsed_s','elapsedDuration'),('moving_s','movingDuration')]:
            selected=row.field_provenance.get(field)
            if not selected:
                assert getattr(row,field) is None
                continue
            record=session.get(SourceRecord,selected['source_record_id'])
            raw=session.get(RawObject,record.raw_object_id)
            source=json.loads((settings.private_dir/raw.relative_path).read_bytes())
            original=(source.get('summaryDTO') or source).get(sourcefield)
            assert original is not None,(field,'missing source field')
            assert math.isclose(getattr(row,field),original,rel_tol=1e-10,abs_tol=1e-8),(field,'mismatch')
        selected=row.field_provenance['start_at']
        record=session.get(SourceRecord,selected['source_record_id'])
        raw=session.get(RawObject,record.raw_object_id)
        source=json.loads((settings.private_dir/raw.relative_path).read_bytes())
        instant=datetime.fromisoformat(source['startTimeGMT'].replace('Z','+00:00'))
        if instant.tzinfo is None: instant=instant.replace(tzinfo=UTC)
        assert instant==row.start_at,'source timestamp mismatch'
        assert str(source['activityId'])==row.garmin_id,'source id mismatch'
        checked+=1
    summary=get_summary(session=session,days=28,as_of=None)['data']
    today=datetime.now(ZoneInfo(summary['timezone'])).date()
    start=today-timedelta(days=13)
    expected=sum(r.distance_m for r in rows if r.sport in {'running','trail_running','treadmill_running'} and start<=r.start_at.astimezone(ZoneInfo(summary['timezone'])).date()<=today and r.distance_m is not None and r.resolution_state=='resolved')
    assert math.isclose(expected,summary['rolling_14']['distance_m'],rel_tol=1e-10,abs_tol=1e-8),'rolling total mismatch'
    recovery=session.scalars(select(RecoveryObservation)).all()
    states=session.scalars(select(SyncState)).all()
    assert all(s.last_success_at is not None for s in states),'dataset sync not successful'
    print(json.dumps({'source_compared_activities':checked,'canonical_identities_unique':True,'rolling_14_source_sum_matches':True,'recovery_observations':len(recovery),'datasets':{s.dataset:s.status for s in states}}))
