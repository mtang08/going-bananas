"""Athlete-local calendar dates."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


def date_in_zone(instant: datetime, tz: ZoneInfo) -> date:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("naive_instant")
    return instant.astimezone(tz).date()
