from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


def opportunity(day: date, anchor: date | None) -> dict | None:
    if anchor is None or (day-anchor).days % 2:
        return None
    offset = (day-anchor).days
    return {'date': day.isoformat(), 'fortnight_index': offset // 14, 'slot': (offset % 14)//2}


def opportunities(start: date, end: date, anchor: date | None) -> list[dict]:
    return [item for i in range((end-start).days+1) if (item := opportunity(start+timedelta(days=i), anchor)) is not None]


def recurring_sessions(
    start: date,
    end: date,
    profile: Any,
    accepted_ranges: list[tuple[date, date]] | None = None,
) -> list[dict]:
    """Expand a confirmed weekday pattern by calendar weeks, without writing plans."""
    if profile is None or not profile.strength_days_confirmed:
        return []
    mode = profile.strength_schedule_mode or "weekly"
    if mode == "alternating":
        anchor = profile.strength_week_a_start
        if anchor is None or anchor.weekday() != 0:
            return []
        week_a = profile.strength_week_a_days or []
        week_b = profile.strength_week_b_days or []
        if len(week_a) != 2 or len(week_b) != 2:
            return []
    else:
        week_a = profile.scheduled_strength_days or []
        if len(week_a) != 2:
            return []
    excluded = accepted_ranges or []
    effective_at = getattr(profile, "effective_at", None)
    effective_day = (
        effective_at.astimezone(ZoneInfo(profile.timezone)).date()
        if isinstance(effective_at, datetime) else None
    )
    result: list[dict] = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        if effective_day is not None and day < effective_day:
            continue
        if any(first <= day <= last for first, last in excluded):
            continue
        if mode == "alternating":
            week = day - timedelta(days=day.weekday())
            week_number = (week - anchor).days // 7
            weekdays = week_a if week_number % 2 == 0 else week_b
            mobility_days = (profile.mobility_week_a_days or []) if week_number % 2 == 0 else (profile.mobility_week_b_days or [])
            optional_mobility_days = profile.mobility_optional_days or []
        else:
            weekdays = week_a
            mobility_days = []
            optional_mobility_days = []
        if day.weekday() in weekdays:
            result.append({"date": day.isoformat(), "kind": "strength", "source": "recurring_schedule", "optional": False})
        if day.weekday() in mobility_days:
            result.append({"date": day.isoformat(), "kind": "mobility", "source": "recurring_schedule", "optional": False})
        elif day.weekday() in optional_mobility_days:
            result.append({"date": day.isoformat(), "kind": "mobility", "source": "recurring_schedule", "optional": True})
    return result
