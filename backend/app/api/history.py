"""Read-only history across the legacy and calendar check-in generations."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.core import envelope, fail, tz
from app.calendar_models import LegacyImportMap
from app.checkin_models import Checkin as CheckinV2
from app.db import get_session
from app.models import Checkin as LegacyCheckin
from app.services.timezone import local_date

router = APIRouter()


@router.get('/history/checkins')
def checkin_history(start: date, end: date, session: Session = Depends(get_session)) -> dict:
    if start > end:
        fail('invalid_date_window', 'Start must not follow end', 422)
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(tz(session))
    items = []
    archived = session.scalars(select(LegacyImportMap).where(
        LegacyImportMap.source_table == 'checkins', LegacyImportMap.target_kind == 'archive')).all()
    if archived:
        for archive_row in archived:
            payload = archive_row.payload
            observed = datetime.fromisoformat(payload['observed_at'].replace('Z', '+00:00'))
            if start <= local_date(observed, zone) <= end:
                items.append({'schema_version': 1, 'source_table': 'checkins',
                              'id': archive_row.source_id, 'observed_at': observed, 'payload': payload})
    else:
        for legacy_row in session.scalars(select(LegacyCheckin)).all():
            if start <= local_date(legacy_row.observed_at, zone) <= end:
                payload = {column.name: getattr(legacy_row, column.name)
                           for column in LegacyCheckin.__table__.columns}
                items.append({'schema_version': 1, 'source_table': 'checkins',
                              'id': legacy_row.id, 'observed_at': legacy_row.observed_at, 'payload': payload})
    for row in session.scalars(select(CheckinV2)).all():
        if start <= local_date(row.observed_at, zone) <= end:
            payload = {column.name: getattr(row, column.name)
                       for column in CheckinV2.__table__.columns}
            items.append({'schema_version': 2, 'source_table': 'checkins_v2',
                          'id': row.id, 'observed_at': row.observed_at, 'payload': payload})
    items.sort(key=lambda item: (item['observed_at'], str(item['id'])))
    return envelope(session, {'items': items})
