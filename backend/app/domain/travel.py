"""Trip date and timezone conventions."""

from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

OPEN_TRIP_MAX = timedelta(days=30)


def _known(name: str | None) -> str | None:
    if not name:
        return None
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return name


def zone_names(start_tz: str | None, end_tz: str | None, home: ZoneInfo) -> tuple[str, str]:
    """Departure and arrival zone names: a missing or unknown side uses the other side, then home."""
    start, end = _known(start_tz), _known(end_tz)
    return start or end or home.key, end or start or home.key
