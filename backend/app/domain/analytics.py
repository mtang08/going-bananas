from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo


def pace_s_per_km(distance_m: float | None, moving_s: float | None) -> float | None:
    if distance_m is None or moving_s is None or distance_m <= 0 or moving_s <= 0:
        return None
    if not isfinite(distance_m) or not isfinite(moving_s):
        raise ValueError("Non-finite measurement")
    return moving_s / (distance_m / 1000)


def utc_date_bounds(start_date: date, end_date: date, timezone_name: str) -> tuple[datetime, datetime]:
    if end_date < start_date:
        raise ValueError("Inverted date range")
    zone = ZoneInfo(timezone_name)
    start = datetime.combine(start_date, datetime.min.time(), zone).astimezone(UTC)
    end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), zone).astimezone(UTC)
    return start, end
