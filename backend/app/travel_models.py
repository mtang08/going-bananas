"""Google Calendar events and trips (migration 0024_google_calendar) and their vocabularies (contracts §2)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import uuid_pk

CATEGORIES = (
    "flight",
    "lodging",
    "ground_travel",
    "reservation",
    "out_of_office",
    "appointment",
    "work",
    "social",
    "other",
)
CATEGORY_SOURCES = ("auto", "athlete")
FLIGHT_CONFIDENCE = ("high", "medium")
TRIP_STATUSES = ("pending", "confirmed", "dismissed", "needs_review")
TRIP_SOURCES = ("detected", "manual")
TRIP_CONFIDENCE = ("high", "medium", "low")
REVIEW_REASONS = ("source_changed", "source_removed")
RUNNING_ACCESS = ("normal", "limited", "none")
GYM_ACCESS = ("full", "limited", "none")
DAY_AVAILABILITY = ("normal", "reduced", "unavailable")
EMPTY_LIST = text("'[]'::jsonb")
TIME_SHAPE = (
    "(all_day AND start_date IS NOT NULL AND end_date IS NOT NULL AND start_at IS NULL AND end_at IS NULL) OR "
    "(NOT all_day AND start_at IS NOT NULL AND end_at IS NOT NULL AND start_date IS NULL AND end_date IS NULL)"
)
SOURCE_SHAPE = (
    "(source = 'detected' AND confidence IS NOT NULL) OR "
    "(source = 'manual' AND confidence IS NULL AND end_date IS NOT NULL AND status <> 'needs_review')"
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({','.join(repr(value) for value in values)})"


class GcalEvent(Base):
    __tablename__ = "gcal_events"
    id: Mapped[uuid.UUID] = uuid_pk()
    google_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    google_status: Mapped[str] = mapped_column(String(12), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    location_codes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=EMPTY_LIST)
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    start_tz: Mapped[str | None] = mapped_column(String(64))
    end_tz: Mapped[str | None] = mapped_column(String(64))
    transparency: Mapped[str] = mapped_column(String(12), nullable=False)
    response_status: Mapped[str | None] = mapped_column(String(12))
    busy: Mapped[bool] = mapped_column(Boolean, nullable=False)
    flight_code: Mapped[str | None] = mapped_column(String(8))
    destination_label: Mapped[str | None] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    auto_category: Mapped[str] = mapped_column(String(16), nullable=False)
    category_source: Mapped[str] = mapped_column(String(8), nullable=False)
    flight_confidence: Mapped[str | None] = mapped_column(String(8))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    google_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    __table_args__ = (
        UniqueConstraint("google_event_id", name="uq_gcal_events_google_id"),
        CheckConstraint(_in("google_status", ("confirmed", "tentative")), name="ck_gcal_events_status"),
        CheckConstraint(_in("transparency", ("opaque", "transparent")), name="ck_gcal_events_transparency"),
        CheckConstraint(
            _in("response_status", ("needsAction", "declined", "tentative", "accepted")), name="ck_gcal_events_response"
        ),
        CheckConstraint(_in("category", CATEGORIES), name="ck_gcal_events_category"),
        CheckConstraint(_in("auto_category", CATEGORIES), name="ck_gcal_events_auto_category"),
        CheckConstraint(_in("category_source", CATEGORY_SOURCES), name="ck_gcal_events_category_source"),
        CheckConstraint(_in("flight_confidence", FLIGHT_CONFIDENCE), name="ck_gcal_events_flight_confidence"),
        CheckConstraint(TIME_SHAPE, name="ck_gcal_events_time_shape"),
        Index("ix_gcal_events_start_at", "start_at"),
        Index("ix_gcal_events_start_date", "start_date"),
    )


class Trip(Base):
    __tablename__ = "trips"
    id: Mapped[uuid.UUID] = uuid_pk()
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    destination_label: Mapped[str | None] = mapped_column(String(120))
    destination_tz: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="detected", server_default="detected")
    confidence: Mapped[str | None] = mapped_column(String(8))
    running_access: Mapped[str | None] = mapped_column(String(8))
    gym_access: Mapped[str | None] = mapped_column(String(8))
    day_availability: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=EMPTY_LIST)
    edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    detected: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    review_reason: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    __table_args__ = (
        CheckConstraint(_in("status", TRIP_STATUSES), name="ck_trips_status"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_trips_dates"),
        CheckConstraint(_in("source", TRIP_SOURCES), name="ck_trips_source"),
        CheckConstraint(_in("confidence", TRIP_CONFIDENCE), name="ck_trips_confidence"),
        CheckConstraint(SOURCE_SHAPE, name="ck_trips_source_shape"),
        CheckConstraint(_in("running_access", RUNNING_ACCESS), name="ck_trips_running_access"),
        CheckConstraint(_in("gym_access", GYM_ACCESS), name="ck_trips_gym_access"),
        CheckConstraint(_in("review_reason", REVIEW_REASONS), name="ck_trips_review_reason"),
        CheckConstraint("(status = 'needs_review') = (review_reason IS NOT NULL)", name="ck_trips_review_status"),
    )


class TripLeg(Base):
    __tablename__ = "trip_legs"
    id: Mapped[uuid.UUID] = uuid_pk()
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    gcal_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("gcal_events.id"), nullable=False)
    leg_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    __table_args__ = (
        UniqueConstraint("gcal_event_id", name="uq_trip_legs_event"),
        UniqueConstraint("trip_id", "seq", name="uq_trip_legs_seq"),
    )
