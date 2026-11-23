"""Google Calendar sync: the fetch window, event upsert with in-window removal, and the inline sync run."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.google_calendar import TOKEN_FILE, GcalError, authorized_session, fetch_events, to_record
from app.db import global_write_lock
from app.domain.travel import categorize, parse_flight
from app.errors import fail
from app.models import ImportBatch
from app.services.timezone import athlete_today, athlete_tz
from app.services.trips import reconcile_trips
from app.travel_models import GcalEvent

WINDOW_DAYS_BACK = 30
WINDOW_DAYS_AHEAD = 180
SOURCE_KIND = "google_calendar"
ADAPTER_VERSION = "gcal-v1"
ERRORS = {
    "gcal_not_connected": ("Google Calendar is not connected. Run calendar-connect.", 409),
    "gcal_credential_permissions": ("Google Calendar files must not be readable by other users.", 409),
    "gcal_reauth_required": ("Google Calendar access expired or was revoked. Run calendar-connect again.", 409),
    "gcal_scope_missing": ("Google Calendar read access was not granted. Run calendar-connect again.", 409),
    "gcal_rate_limited": ("Google Calendar is rate limiting requests. Try again shortly.", 503),
    "gcal_remote_error": ("Google Calendar request failed.", 502),
    "gcal_invalid_response": ("Google Calendar returned an unexpected response.", 502),
}
_SYNC_LOCK_FILE = ".google-calendar-sync.lock"

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
    """Home-zone dates [today-30, today+180] and instants [start midnight, end+1 midnight)."""
    start, end = today - timedelta(days=WINDOW_DAYS_BACK), today + timedelta(days=WINDOW_DAYS_AHEAD)
    return SyncWindow(
        home,
        start,
        end,
        datetime.combine(start, time(), tzinfo=home),
        datetime.combine(end + timedelta(days=1), time(), tzinfo=home),
    )


def _values(record: dict[str, Any], home: ZoneInfo) -> dict[str, Any]:
    values = {key: record[key] for key in PROJECTED}
    for key in ("start_at", "end_at", "google_updated_at"):
        values[key] = datetime.fromisoformat(record[key]) if record[key] else None
    for key in ("start_date", "end_date"):
        values[key] = date.fromisoformat(record[key]) if record[key] else None
    category, confidence = categorize(record, home)
    title = record["summary"] or ""
    code, label = parse_flight(title) if category == "flight" or "flight" in title.lower() else (None, None)
    values.update(auto_category=category, flight_confidence=confidence, flight_code=code, destination_label=label)
    return values


def _overlaps(row: GcalEvent, window: SyncWindow) -> bool:
    if row.all_day:
        assert row.start_date is not None and row.end_date is not None
        return row.end_date > window.start and row.start_date <= window.end
    assert row.start_at is not None and row.end_at is not None
    return row.end_at > window.time_min and row.start_at < window.time_max


def upsert_events(session: Session, records: list[dict[str, Any]], window: SyncWindow, now: datetime) -> dict[str, int]:
    """Apply one complete fetch of contracts §3 records (design §5). Flushes; the caller commits."""
    by_id = {record["google_event_id"]: record for record in records}
    counts = {"fetched": len(by_id), "created": 0, "changed": 0, "unchanged": 0, "removed": 0, "restored": 0}
    existing = {row.google_event_id: row for row in session.scalars(select(GcalEvent))}
    for google_id, record in by_id.items():
        row = existing.get(google_id)
        if row is None:
            values = _values(record, window.home)
            session.add(
                GcalEvent(
                    google_event_id=google_id,
                    category=values["auto_category"],
                    category_source="auto",
                    first_seen_at=now,
                    changed_at=now,
                    version=1,
                    **values,
                )
            )
            counts["created"] += 1
            continue
        if row.content_hash == record["content_hash"] and row.removed_at is None:
            counts["unchanged"] += 1
            continue
        counts["restored" if row.removed_at is not None else "changed"] += 1
        if row.content_hash != record["content_hash"]:
            for key, value in _values(record, window.home).items():
                setattr(row, key, value)
            if row.category_source == "auto":
                row.category = row.auto_category
            row.changed_at = now
        row.removed_at = None
        row.version += 1
    for google_id, row in existing.items():
        if google_id not in by_id and row.removed_at is None and _overlaps(row, window):
            row.removed_at = now
            row.version += 1
            counts["removed"] += 1
    session.flush()
    return counts


@contextmanager
def _sync_lock(private_dir: Path) -> Iterator[None]:
    """Serialize calendar fetches on this host without holding a database connection."""
    path = private_dir / _SYNC_LOCK_FILE
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def run_sync(session: Session, private_dir: Path, now: datetime) -> dict[str, Any]:
    """POST /google-calendar/sync (design §4). Commits before the fetch and once for its result."""
    if not (private_dir / TOKEN_FILE).is_file():
        fail("gcal_not_connected", *ERRORS["gcal_not_connected"])
    home = athlete_tz(session)
    window = sync_window(home, athlete_today(session, now))
    session.commit()

    with _sync_lock(private_dir):
        try:
            http = authorized_session(private_dir)
            with closing(http):
                items = fetch_events(http, window.time_min, window.time_max)
                records = [record for item in items if (record := to_record(item)) is not None]
        except GcalError as exc:
            code = str(exc)
            session.add(
                ImportBatch(
                    source_kind=SOURCE_KIND,
                    status="failed",
                    started_at=now,
                    finished_at=datetime.now(UTC),
                    adapter_version=ADAPTER_VERSION,
                    counters={},
                    error_code=code,
                )
            )
            session.commit()
            fail(code, *ERRORS[code])
        with session.begin():
            global_write_lock(session)
            counters = upsert_events(session, records, window, now)
            trips = reconcile_trips(session, home)
            finished = datetime.now(UTC)
            session.add(
                ImportBatch(
                    source_kind=SOURCE_KIND,
                    status="complete",
                    started_at=now,
                    finished_at=finished,
                    adapter_version=ADAPTER_VERSION,
                    counters={**counters, **{f"trips_{key}": value for key, value in trips.items()}},
                )
            )
        return {
            "sync": {
                "started_at": now.isoformat(),
                "finished_at": finished.isoformat(),
                "window": {"start": window.start.isoformat(), "end": window.end.isoformat()},
                "counters": counters,
            },
            "trips": trips,
        }
