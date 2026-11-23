"""Trip edits, calendar event projections, and itinerary views."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.local_time import date_in_zone
from app.domain.travel import OPEN_TRIP_MAX, zone_names
from app.errors import fail
from app.travel_models import GcalEvent, Trip, TripLeg


def _utc_iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def event_local_date(event: GcalEvent, home: ZoneInfo) -> date:
    """The home-zone date an event starts on (contracts §6.3 `local_date`)."""
    if event.all_day:
        assert event.start_date is not None
        return event.start_date
    assert event.start_at is not None
    return date_in_zone(event.start_at, home)


def event_view(event: GcalEvent, trip_id: uuid.UUID | None, home: ZoneInfo) -> dict[str, Any]:
    """Contracts §6.3 `EventView`."""
    return {
        "id": str(event.id),
        "event_type": event.event_type,
        "summary": event.summary,
        "all_day": event.all_day,
        "start_at": _utc_iso(event.start_at),
        "end_at": _utc_iso(event.end_at),
        "start_date": event.start_date.isoformat() if event.start_date else None,
        "end_date": event.end_date.isoformat() if event.end_date else None,
        "start_tz": event.start_tz,
        "end_tz": event.end_tz,
        "local_date": event_local_date(event, home).isoformat(),
        "busy": event.busy,
        "response_status": event.response_status,
        "category": event.category,
        "category_source": event.category_source,
        "auto_category": event.auto_category,
        "flight_code": event.flight_code,
        "destination_label": event.destination_label,
        "location_codes": event.location_codes,
        "removed": event.removed_at is not None,
        "trip_id": str(trip_id) if trip_id else None,
        "version": event.version,
    }


EDITABLE = (
    "start_date",
    "end_date",
    "destination_label",
    "destination_tz",
    "running_access",
    "gym_access",
    "day_availability",
)
INVALID_TRIP = "Trip dates or availability are invalid"
MAX_AVAILABILITY = 60


def _availability(entries: list[Any], start: date, end: date | None) -> list[dict[str, str]]:
    """Contracts §6.6 step 4: keep days inside the trip (open-ended: start + 30), then require ordered dates,
    unique days, and at most 60 entries."""
    if end is not None and end < start:
        fail("invalid_trip", INVALID_TRIP)
    last = end if end is not None else start + OPEN_TRIP_MAX
    kept = [
        {"date": str(entry["date"]), "availability": entry["availability"]}
        for entry in entries
        if start <= date.fromisoformat(str(entry["date"])) <= last
    ]
    if len({entry["date"] for entry in kept}) != len(kept) or len(kept) > MAX_AVAILABILITY:
        fail("invalid_trip", INVALID_TRIP)
    return sorted(kept, key=lambda entry: entry["date"])


def patch_trip(session: Session, trip_id: uuid.UUID, changes: dict[str, Any], now: datetime) -> Trip:
    """Contracts §6.6 in order. `changes` is the validated body without unset keys. Flushes; the caller commits."""
    trip = session.get(Trip, trip_id)
    if trip is None:
        fail("trip_not_found", "Trip not found", 404)
    if trip.version != changes["expected_version"]:
        fail("version_conflict", "Trip changed; reload before editing", 409)
    if trip.source == "manual" and (
        changes.get("accept_detected")
        or changes.get("status") == "pending"
        or ("end_date" in changes and changes["end_date"] is None)
    ):
        fail("invalid_trip", INVALID_TRIP)
    if any(
        key in changes and changes[key] is None
        for key in ("start_date", "status", "destination_tz", "day_availability")
    ):
        fail("invalid_trip", INVALID_TRIP)
    if changes.get("accept_detected") and not trip.detected:
        fail("invalid_trip", INVALID_TRIP)
    new: dict[str, Any] = {}
    if changes.get("accept_detected"):
        detected = trip.detected
        new.update(
            start_date=date.fromisoformat(detected["start_date"]),
            end_date=date.fromisoformat(detected["end_date"]) if detected["end_date"] else None,
            destination_label=detected["destination_label"],
            destination_tz=detected["destination_tz"],
            confidence=detected["confidence"],
        )
    fields = {key: changes[key] for key in EDITABLE if key in changes}
    new.update(fields)
    new["day_availability"] = _availability(
        new.get("day_availability", trip.day_availability),
        new.get("start_date", trip.start_date),
        new.get("end_date", trip.end_date),
    )
    for key, value in new.items():
        setattr(trip, key, value)
    if fields:
        trip.edited = True
    if "status" in changes:
        trip.status = changes["status"]
        if trip.status != "needs_review":
            trip.review_reason = None
    trip.version += 1
    trip.updated_at = now
    session.flush()
    return trip


def travel_days(events: Sequence[GcalEvent], home: ZoneInfo) -> list[str]:
    """Sorted local departure and arrival dates of the non-removed timed legs (contracts §6.5, §7)."""
    days: set[date] = set()
    for event in events:
        if event.removed_at is not None or event.start_at is None or event.end_at is None:
            continue
        dep_tz, arr_tz = zone_names(event.start_tz, event.end_tz, home)
        days.add(date_in_zone(event.start_at, ZoneInfo(dep_tz)))
        days.add(date_in_zone(event.end_at, ZoneInfo(arr_tz)))
    return [day.isoformat() for day in sorted(days)]


def _local_iso(value: datetime | None, tz: str) -> str | None:
    return value.astimezone(ZoneInfo(tz)).isoformat() if value is not None else None


def trip_view(session: Session, trip: Trip, home: ZoneInfo) -> dict[str, Any]:
    """Contracts §6.5 `TripView`; legs in `seq` order with UTC and local times."""
    rows = session.execute(
        select(TripLeg.seq, GcalEvent)
        .join(GcalEvent, GcalEvent.id == TripLeg.gcal_event_id)
        .where(TripLeg.trip_id == trip.id)
        .order_by(TripLeg.seq)
    ).all()
    legs = []
    for seq, event in rows:
        dep_tz, arr_tz = zone_names(event.start_tz, event.end_tz, home)
        legs.append(
            {
                "event_id": str(event.id),
                "seq": seq,
                "summary": event.summary,
                "flight_code": event.flight_code,
                "depart_at": _utc_iso(event.start_at),
                "arrive_at": _utc_iso(event.end_at),
                "depart_tz": dep_tz,
                "arrive_tz": arr_tz,
                "depart_local": _local_iso(event.start_at, dep_tz),
                "arrive_local": _local_iso(event.end_at, arr_tz),
                "removed": event.removed_at is not None,
            }
        )
    return {
        "id": str(trip.id),
        "status": trip.status,
        "start_date": trip.start_date.isoformat(),
        "end_date": trip.end_date.isoformat() if trip.end_date else None,
        "destination_label": trip.destination_label,
        "destination_tz": trip.destination_tz,
        "source": trip.source,
        "confidence": trip.confidence,
        "edited": trip.edited,
        "review_reason": trip.review_reason,
        "detected": trip.detected,
        "running_access": trip.running_access,
        "gym_access": trip.gym_access,
        "day_availability": trip.day_availability,
        "travel_days": travel_days([event for _, event in rows], home),
        "legs": legs,
        "version": trip.version,
    }


def create_manual_trip(session: Session, fields: dict[str, Any], now: datetime) -> Trip:
    """Contracts §6.7: a confirmed trip the athlete adds, without legs. `fields` is the validated body.

    Flushes; the caller commits. Reconciliation never reads manual trips.
    """
    if fields.get("end_date") is None:
        fail("invalid_trip", INVALID_TRIP)
    entries = fields.get("day_availability") or []
    days = _availability(entries, fields["start_date"], fields["end_date"])
    if len(days) != len(entries):
        fail("invalid_trip", INVALID_TRIP)
    trip = Trip(
        source="manual",
        status="confirmed",
        confidence=None,
        detected={},
        edited=True,
        version=1,
        start_date=fields["start_date"],
        end_date=fields["end_date"],
        destination_tz=fields["destination_tz"],
        destination_label=fields.get("destination_label"),
        running_access=fields.get("running_access"),
        gym_access=fields.get("gym_access"),
        day_availability=days,
        created_at=now,
        updated_at=now,
    )
    session.add(trip)
    session.flush()
    return trip
