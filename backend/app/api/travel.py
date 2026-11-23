"""Google Calendar sync and status, synced calendar events, and trips."""

from __future__ import annotations

import datetime as dt
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, desc, or_, select
from sqlalchemy.orm import Session

from app.adapters.google_calendar import TOKEN_FILE
from app.api.core import envelope
from app.config import settings
from app.db import get_session, global_write_lock
from app.domain.travel import OPEN_TRIP_MAX
from app.errors import fail
from app.models import ImportBatch
from app.services.gcal_sync import SOURCE_KIND, WINDOW_DAYS_AHEAD, WINDOW_DAYS_BACK
from app.services.timezone import athlete_today, athlete_tz
from app.services.trips import create_manual_trip, event_local_date, event_view, patch_trip, trip_view
from app.travel_models import (
    CATEGORIES,
    DAY_AVAILABILITY,
    GYM_ACCESS,
    RUNNING_ACCESS,
    TRIP_STATUSES,
    GcalEvent,
    Trip,
    TripLeg,
)

router = APIRouter()


@router.get("/google-calendar/status")
def gcal_status(session: Session = Depends(get_session)) -> dict:
    batches = select(ImportBatch).where(ImportBatch.source_kind == SOURCE_KIND)
    last = session.scalars(batches.order_by(desc(ImportBatch.started_at), desc(ImportBatch.id)).limit(1)).first()
    success = session.scalars(
        batches.where(ImportBatch.status == "complete").order_by(desc(ImportBatch.finished_at)).limit(1)
    ).first()
    return envelope(
        session,
        {
            "connected": (settings.private_dir / TOKEN_FILE).is_file(),
            "window": {"days_back": WINDOW_DAYS_BACK, "days_ahead": WINDOW_DAYS_AHEAD},
            "last_sync": None
            if last is None
            else {
                "started_at": last.started_at,
                "finished_at": last.finished_at,
                "status": last.status,
                "error_code": last.error_code,
                "counters": last.counters,
            },
            "last_success_at": success.finished_at if success else None,
        },
    )


TRAVEL_CATEGORIES = ("flight", "lodging", "ground_travel")
RANGE_MAX_DAYS = 400


def _check_range(first: date, last: date) -> None:
    if first > last or (last - first).days > RANGE_MAX_DAYS:
        fail("invalid_date_range", "Date range must be ordered and at most 400 days", 422)


def _event_sort_key(row: GcalEvent, home: ZoneInfo) -> tuple:
    start = row.start_at if row.start_at is not None else datetime.combine(row.start_date, time(), home)
    return (event_local_date(row, home), start, str(row.id))


def _trip_ids(session: Session, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    if not event_ids:
        return {}
    rows = session.execute(select(TripLeg.gcal_event_id, TripLeg.trip_id).where(TripLeg.gcal_event_id.in_(event_ids)))
    return {event_id: trip_id for event_id, trip_id in rows}


@router.get("/google-calendar/events")
def list_gcal_events(
    start: date | None = None,
    end: date | None = None,
    category: str | None = None,
    include_removed: bool = False,
    session: Session = Depends(get_session),
) -> dict:
    home = athlete_tz(session)
    today = athlete_today(session)
    first = start or today - timedelta(days=WINDOW_DAYS_BACK)
    last = end or today + timedelta(days=WINDOW_DAYS_AHEAD)
    _check_range(first, last)
    if category is not None and category != "travel" and category not in CATEGORIES:
        fail("validation_error", "Invalid request fields", 422)
    lo = datetime.combine(first, time(), home)
    hi = datetime.combine(last + timedelta(days=1), time(), home)
    query = select(GcalEvent).where(
        or_(
            and_(GcalEvent.all_day.is_(False), GcalEvent.start_at >= lo, GcalEvent.start_at < hi),
            and_(GcalEvent.all_day.is_(True), GcalEvent.start_date >= first, GcalEvent.start_date <= last),
        )
    )
    if not include_removed:
        query = query.where(GcalEvent.removed_at.is_(None))
    if category == "travel":
        query = query.where(GcalEvent.category.in_(TRAVEL_CATEGORIES))
    elif category is not None:
        query = query.where(GcalEvent.category == category)
    rows = sorted(session.scalars(query), key=lambda row: _event_sort_key(row, home))
    trip_ids = _trip_ids(session, [row.id for row in rows])
    return envelope(session, {"items": [event_view(row, trip_ids.get(row.id), home) for row in rows]})


class _TripFieldChecks(BaseModel):
    @field_validator("destination_tz", check_fields=False)
    @classmethod
    def known_zone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError("Unknown timezone") from exc
        return value

    @field_validator("running_access", check_fields=False)
    @classmethod
    def known_running(cls, value: str | None) -> str | None:
        if value is not None and value not in RUNNING_ACCESS:
            raise ValueError("Unknown running access")
        return value

    @field_validator("gym_access", check_fields=False)
    @classmethod
    def known_gym(cls, value: str | None) -> str | None:
        if value is not None and value not in GYM_ACCESS:
            raise ValueError("Unknown gym access")
        return value


class DayAvailabilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: dt.date
    availability: str

    @field_validator("availability")
    @classmethod
    def known_availability(cls, value: str) -> str:
        if value not in DAY_AVAILABILITY:
            raise ValueError("Unknown availability")
        return value


class TripPatchInput(_TripFieldChecks):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    status: str | None = None
    accept_detected: bool = False
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    destination_label: str | None = Field(default=None, max_length=120)
    destination_tz: str | None = None
    running_access: str | None = None
    gym_access: str | None = None
    day_availability: list[DayAvailabilityInput] | None = None

    @field_validator("status")
    @classmethod
    def athlete_status(cls, value: str | None) -> str | None:
        if value is not None and value not in ("confirmed", "dismissed", "pending"):
            raise ValueError("Status must be confirmed, dismissed, or pending")
        return value


class ManualTripInput(_TripFieldChecks):
    model_config = ConfigDict(extra="forbid")
    start_date: dt.date
    end_date: dt.date
    destination_tz: str
    destination_label: str | None = Field(default=None, max_length=120)
    running_access: str | None = None
    gym_access: str | None = None
    day_availability: list[DayAvailabilityInput] = Field(default_factory=list)


@router.get("/trips")
def list_trips(
    start: date | None = None,
    end: date | None = None,
    status: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    today = athlete_today(session)
    first = start or today - timedelta(days=30)
    last = end or today + timedelta(days=365)
    _check_range(first, last)
    statuses = [s for s in status.split(",") if s] if status else [s for s in TRIP_STATUSES if s != "dismissed"]
    if not statuses or any(s not in TRIP_STATUSES for s in statuses):
        fail("validation_error", "Invalid request fields", 422)
    rows = session.scalars(
        select(Trip)
        .where(
            Trip.status.in_(statuses),
            Trip.start_date <= last,
            or_(
                Trip.end_date >= first,
                and_(Trip.end_date.is_(None), Trip.start_date >= first - OPEN_TRIP_MAX),
            ),
        )
        .order_by(Trip.start_date, Trip.id)
    )
    home = athlete_tz(session)
    return envelope(session, {"items": [trip_view(session, row, home) for row in rows]})


@router.patch("/trips/{trip_id}")
def patch_trip_route(trip_id: uuid.UUID, body: TripPatchInput, session: Session = Depends(get_session)) -> dict:
    global_write_lock(session)
    trip = patch_trip(session, trip_id, body.model_dump(exclude_unset=True), datetime.now(UTC))
    session.commit()
    return envelope(session, trip_view(session, trip, athlete_tz(session)))


@router.post("/trips", status_code=201)
def post_trip(body: ManualTripInput, session: Session = Depends(get_session)) -> dict:
    global_write_lock(session)
    trip = create_manual_trip(session, body.model_dump(), datetime.now(UTC))
    session.commit()
    return envelope(session, trip_view(session, trip, athlete_tz(session)))
