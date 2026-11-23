"""Google Calendar sync: the fetch window, event upsert with in-window removal, and the inline sync run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WINDOW_DAYS_BACK = 30
WINDOW_DAYS_AHEAD = 180
PROJECTED = (
    "event_type",
    "google_status",
    "summary",
    "location_codes",
    "all_day",
    "start_at",
    "end_at",
    "start_date",
    "end_date",
    "start_tz",
    "end_tz",
    "transparency",
    "response_status",
    "busy",
    "google_updated_at",
    "content_hash",
)


@dataclass(frozen=True)
class SyncWindow:
    home: ZoneInfo
    start: date
    end: date
    time_min: datetime
    time_max: datetime


def sync_window(home: ZoneInfo, today: date) -> SyncWindow:
    """Home-zone dates [today-30, today+180] and the instants [start midnight, end+1 midnight) sent to Google."""
    start, end = today - timedelta(days=WINDOW_DAYS_BACK), today + timedelta(days=WINDOW_DAYS_AHEAD)
    return SyncWindow(
        home,
        start,
        end,
        datetime.combine(start, time(), tzinfo=home),
        datetime.combine(end + timedelta(days=1), time(), tzinfo=home),
    )


SOURCE_KIND = "google_calendar"
