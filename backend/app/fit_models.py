from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    REAL,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import uuid_pk


class FitFile(Base):
    __tablename__ = 'fit_files'
    id: Mapped[uuid.UUID] = uuid_pk()
    raw_object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('raw_objects.id'), nullable=False, unique=True)
    activity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('activities.id'), nullable=False, unique=True)
    zip_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(100))
    fit_sha256: Mapped[str | None] = mapped_column(String(64))
    profile_version: Mapped[str | None] = mapped_column(String(20))
    sdk_version: Mapped[str | None] = mapped_column(String(20))
    decoded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decode_error: Mapped[str | None] = mapped_column(String(100))
    message_inventory: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    device: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

class ActivityLap(Base):
    __tablename__ = 'activity_laps'
    id: Mapped[uuid.UUID] = uuid_pk()
    activity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('activities.id'), nullable=False)
    lap_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timer_s: Mapped[float | None] = mapped_column(Float)
    elapsed_s: Mapped[float | None] = mapped_column(Float)
    distance_m: Mapped[float | None] = mapped_column(Float)
    avg_speed_mps: Mapped[float | None] = mapped_column(Float)
    avg_hr_bpm: Mapped[float | None] = mapped_column(Float)
    max_hr_bpm: Mapped[float | None] = mapped_column(Float)
    lap_trigger: Mapped[str | None] = mapped_column(String(30))
    wkt_step_index: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint('activity_id','lap_index'),)

class ActivityWorkoutStep(Base):
    __tablename__ = 'activity_workout_steps'
    id: Mapped[uuid.UUID] = uuid_pk()
    activity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('activities.id'), nullable=False)
    message_index: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str | None] = mapped_column(String(100))
    intensity: Mapped[str | None] = mapped_column(String(20))
    duration_type: Mapped[str] = mapped_column(String(30), nullable=False)
    __table_args__ = (UniqueConstraint('activity_id','message_index'), CheckConstraint("intensity IN ('active','rest','warmup','cooldown','recovery','interval','other')", name='ck_activity_workout_steps_intensity'))
    duration_value: Mapped[float | None] = mapped_column(Float)
    target_type: Mapped[str | None] = mapped_column(String(30))
    target_low: Mapped[float | None] = mapped_column(Float)
    target_high: Mapped[float | None] = mapped_column(Float)
    repeat_from: Mapped[int | None] = mapped_column(Integer)
    repeat_count: Mapped[int | None] = mapped_column(Integer)

class ActivityStream(Base):
    __tablename__ = 'activity_streams'
    activity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('activities.id'), primary_key=True)
    t_s: Mapped[list[Any]] = mapped_column(ARRAY(Integer), nullable=False)
    hr_bpm: Mapped[list[Any]] = mapped_column(ARRAY(SmallInteger), nullable=False)
    speed_mps: Mapped[list[Any]] = mapped_column(ARRAY(REAL), nullable=False)
    distance_m: Mapped[list[Any]] = mapped_column(ARRAY(REAL), nullable=False)
    altitude_m: Mapped[list[Any]] = mapped_column(ARRAY(REAL), nullable=False)
    cadence: Mapped[list[Any]] = mapped_column(ARRAY(REAL), nullable=False)
    timer_on: Mapped[list[Any]] = mapped_column(ARRAY(Integer, dimensions=2), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_gap_s: Mapped[int] = mapped_column(Integer, nullable=False)
    quality_flags: Mapped[list[Any]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default='{}')
