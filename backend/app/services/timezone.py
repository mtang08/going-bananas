from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.local_time import date_in_zone
from app.models import ProfileVersion

DEFAULT_TIMEZONE = "America/New_York"


def athlete_tz(session: Session) -> ZoneInfo:
    name = session.scalar(select(ProfileVersion.timezone).order_by(ProfileVersion.version.desc()).limit(1))
    return ZoneInfo(name or DEFAULT_TIMEZONE)



def athlete_today(session: Session, now: datetime | None = None) -> date:
    return date_in_zone(now if now is not None else datetime.now(UTC), athlete_tz(session))
