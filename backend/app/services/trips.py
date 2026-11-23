"""Trip edits, calendar event projections, and itinerary views."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.domain.local_time import date_in_zone
from app.domain.travel import OPEN_TRIP_MAX, Leg, TripCandidate, detect_trips, make_leg, timezone_basis, zone_names
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


def _active_flight(event: GcalEvent) -> bool:
    return (
        event.removed_at is None
        and event.category == "flight"
        and event.response_status != "declined"
        and event.start_at is not None
        and event.end_at is not None
    )


def travel_days(events: Sequence[GcalEvent], home: ZoneInfo) -> list[str]:
    """Sorted local departure and arrival dates of the non-removed timed legs (contracts §6.5, §7)."""
    days: set[date] = set()
    for event in events:
        if not _active_flight(event) or event.start_at is None or event.end_at is None:
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
                "timezone_basis": timezone_basis(event.start_tz, event.end_tz),
                "depart_local": _local_iso(event.start_at, dep_tz),
                "arrive_local": _local_iso(event.end_at, arr_tz),
                "removed": not _active_flight(event),
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


TRIP_FIELDS = ("start_date", "end_date", "destination_label", "destination_tz", "confidence")


def detected_json(candidate: TripCandidate) -> dict[str, Any]:
    """The contracts §5 `DetectedTrip` stored in `trips.detected`."""
    return {
        "start_date": candidate.start_date.isoformat(),
        "end_date": candidate.end_date.isoformat() if candidate.end_date else None,
        "destination_label": candidate.destination_label,
        "destination_tz": candidate.destination_tz,
        "confidence": candidate.confidence,
        "stops": [
            {"label": stop.label, "tz": stop.tz, "arrive_date": stop.arrive_date.isoformat()}
            for stop in candidate.stops
        ],
    }


def _flight_legs(session: Session, home: ZoneInfo) -> tuple[list[Leg], dict[str, str], dict[str, list[str]]]:
    """Resolve duplicate provider entries into one physical leg before grouping trips."""
    rows = session.scalars(
        select(GcalEvent)
        .where(
            or_(GcalEvent.category == "flight", GcalEvent.auto_category == "flight"),
            GcalEvent.start_at.is_not(None),
            GcalEvent.end_at.is_not(None),
        )
        .order_by(GcalEvent.id)
    ).all()
    groups: dict[tuple, list[GcalEvent]] = {}
    for row in rows:
        key = (row.flight_code, row.start_at, row.end_at) if row.flight_code else (row.id,)
        groups.setdefault(key, []).append(row)
    selected = []
    aliases = {}
    for copies in groups.values():
        eligible = [row for row in copies if _active_flight(row)]
        if not eligible:
            continue
        if len({r.event_type for r in copies}) > 1:
            preferred = min(
                eligible,
                key=lambda r: (
                    timezone_basis(r.start_tz, r.end_tz) != "calendar_endpoints",
                    r.event_type != "fromGmail",
                    str(r.id),
                ),
            )
            selected.append(preferred)
            aliases[str(preferred.id)] = [str(r.id) for r in copies if r.id != preferred.id]
        else:
            selected.extend(eligible)
    legs: list[Leg] = []
    hashes: dict[str, str] = {}
    for row in selected:
        assert row.start_at is not None and row.end_at is not None
        legs.append(
            make_leg(
                str(row.id),
                row.start_at,
                row.end_at,
                row.start_tz,
                row.end_tz,
                row.destination_label,
                row.flight_confidence,
                home,
            )
        )
        hashes[str(row.id)] = row.content_hash
    return legs, hashes, aliases


def _put_legs(
    session: Session, trip: Trip, legs: Sequence[Leg], hashes: dict[str, str], *, append: bool = False
) -> None:
    """Give `legs` to `trip`, taking them from any other trip; without `append`, drop the trip's other legs."""
    event_ids = [uuid.UUID(leg.event_id) for leg in legs]
    taken = TripLeg.gcal_event_id.in_(event_ids)
    for row in session.scalars(select(TripLeg).where(taken if append else or_(taken, TripLeg.trip_id == trip.id))):
        session.delete(row)
    session.flush()
    last = session.scalar(select(func.max(TripLeg.seq)).where(TripLeg.trip_id == trip.id))
    first = 0 if last is None else last + 1
    session.add_all(
        TripLeg(trip_id=trip.id, gcal_event_id=event_id, leg_hash=hashes[leg.event_id], seq=first + n)
        for n, (event_id, leg) in enumerate(zip(event_ids, legs, strict=True))
    )
    session.flush()


def _merge(session: Session, trip: Trip, candidate: TripCandidate, hashes: dict[str, str]) -> str | None:
    """Apply a matched candidate by the design §7 table; returns the counter to bump, if any."""
    current = session.execute(
        select(TripLeg.gcal_event_id, TripLeg.leg_hash).where(TripLeg.trip_id == trip.id).order_by(TripLeg.seq)
    ).all()
    if trip.status == "dismissed":
        mine = {str(row.gcal_event_id) for row in current}
        new = [leg for leg in candidate.legs if leg.event_id not in mine]
        if new:
            _put_legs(session, trip, new, hashes, append=True)
        return None
    detected = detected_json(candidate)
    wanted = [(uuid.UUID(leg.event_id), hashes[leg.event_id]) for leg in candidate.legs]
    if trip.detected == detected and [tuple(row) for row in current] == wanted:
        return None
    _put_legs(session, trip, candidate.legs, hashes)
    trip.detected = detected
    trip.version += 1
    if trip.status == "pending" and not trip.edited:
        for key in TRIP_FIELDS:
            setattr(trip, key, getattr(candidate, key))
        return "updated"
    trip.status, trip.review_reason = "needs_review", "source_changed"
    return "flagged"


def _unmatched(session: Session, trip: Trip) -> str | None:
    """A detected trip no candidate claimed: drop an untouched suggestion, flag anything the athlete acted on."""
    if (
        trip.status == "dismissed"
        or trip.review_reason == "source_removed"
        or (trip.status == "confirmed" and not trip.detected)
    ):
        return None
    if trip.status == "pending" and not trip.edited:
        session.delete(trip)
        return "deleted"
    trip.detected = {}
    trip.status, trip.review_reason = "needs_review", "source_removed"
    trip.version += 1
    return "flagged"


def reconcile_trips(session: Session, home: ZoneInfo) -> dict[str, int]:
    """Re-detect trips from stored flights and merge them into detected trips (design §7). Flushes."""
    counts = {"created": 0, "updated": 0, "flagged": 0, "deleted": 0}
    legs, hashes, aliases = _flight_legs(session, home)
    trips = {trip.id: trip for trip in session.scalars(select(Trip).where(Trip.source == "detected"))}
    owner = {
        str(event_id): trip_id
        for event_id, trip_id in session.execute(
            select(TripLeg.gcal_event_id, TripLeg.trip_id).where(TripLeg.trip_id.in_(list(trips)))
        )
    }
    # A second calendar entry for the same flight may outlive the original linked entry.
    for representative, copies in aliases.items():
        if representative not in owner:
            previous = next((owner[copy] for copy in copies if copy in owner), None)
            if previous is not None:
                owner[representative] = previous
    claimed: set[uuid.UUID] = set()
    for candidate in detect_trips(legs, home):
        ids = {
            owner[leg.event_id]
            for leg in candidate.legs
            if leg.event_id in owner
            and (owner[leg.event_id] not in claimed or trips[owner[leg.event_id]].status == "dismissed")
        }
        trip = min(
            (trips[i] for i in ids), key=lambda t: (t.status != "dismissed", t.start_date, str(t.id)), default=None
        )
        if trip is None:
            trip = Trip(
                status="pending",
                source="detected",
                edited=False,
                version=1,
                detected=detected_json(candidate),
                **{key: getattr(candidate, key) for key in TRIP_FIELDS},
            )
            session.add(trip)
            session.flush()
            _put_legs(session, trip, candidate.legs, hashes)
            counts["created"] += 1
            continue
        claimed.add(trip.id)
        outcome = _merge(session, trip, candidate, hashes)
        if outcome:
            counts[outcome] += 1
    for trip in trips.values():
        if trip.id not in claimed and (outcome := _unmatched(session, trip)):
            counts[outcome] += 1
    session.flush()
    return counts


def set_event_category(
    session: Session, event_id: uuid.UUID, expected_version: int, category: str | None, home: ZoneInfo
) -> tuple[GcalEvent, dict[str, int]]:
    """Contracts §6.4: an athlete category, or None to restore auto; then re-detect trips. Flushes; caller commits."""
    event = session.get(GcalEvent, event_id)
    if event is None:
        fail("event_not_found", "Calendar event not found", 404)
    if event.version != expected_version:
        fail("version_conflict", "Calendar event changed; reload before editing", 409)
    event.category, event.category_source = (event.auto_category, "auto") if category is None else (category, "athlete")
    event.version += 1
    session.flush()
    return event, reconcile_trips(session, home)
