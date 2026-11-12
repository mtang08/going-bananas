from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import uuid_pk


class Checkin(Base):
    __tablename__ = 'checkins_v2'
    id: Mapped[uuid.UUID] = uuid_pk()
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default='1')
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    fatigue: Mapped[float | None] = mapped_column(Numeric(3, 1, asdecimal=False))
    illness: Mapped[str | None] = mapped_column(String(10))
    gait_change: Mapped[str | None] = mapped_column(String(10))
    context_tags: Mapped[list[Any]] = mapped_column(ARRAY(String(30)), nullable=False, default=list, server_default='{}')
    activity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('activities.id'))
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(Text)
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2, server_default='2')
    __table_args__ = (CheckConstraint("kind IN ('exception','post_run','delayed_followup')", name='ck_checkins_v2_kind'), CheckConstraint("context_tags <@ ARRAY['heat','travel','poor_sleep','unusual_surface','equipment']::varchar[]", name='ck_checkins_v2_context_tags'), CheckConstraint('fatigue IS NULL OR (fatigue >= 0 AND fatigue <= 10)', name='ck_checkins_v2_fatigue'), CheckConstraint("illness IN ('none','possible','present')", name='ck_checkins_v2_illness'), CheckConstraint("gait_change IN ('yes','no','unsure')", name='ck_checkins_v2_gait_change'),)

class CheckinRevision(Base):
    __tablename__ = 'checkin_v2_revisions'
    id: Mapped[uuid.UUID] = uuid_pk()
    checkin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('checkins_v2.id'), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint('checkin_id','version'),)

class SymptomReport(Base):
    __tablename__ = 'symptom_reports'
    id: Mapped[uuid.UUID] = uuid_pk()
    checkin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('checkins_v2.id'), nullable=False)
    site: Mapped[str] = mapped_column(String(60), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    severity: Mapped[float] = mapped_column(Numeric(3, 1, asdecimal=False), nullable=False)
    timing: Mapped[str] = mapped_column(String(20), nullable=False)
    __table_args__ = (CheckConstraint("side IN ('left','right','both','na')", name='ck_symptom_reports_side'), CheckConstraint('severity IS NULL OR (severity >= 0 AND severity <= 10)', name='ck_symptom_reports_severity'), CheckConstraint("timing IN ('during','immediately_after','next_morning','hours_24_48','later','unknown')", name='ck_symptom_reports_timing'),)

class SessionRpe(Base):
    __tablename__ = 'session_rpe'
    id: Mapped[uuid.UUID] = uuid_pk()
    activity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('activities.id'))
    strong_workout_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('strong_workouts.id'))
    manual_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('manual_sessions.id'))
    rpe: Mapped[float] = mapped_column(Numeric(3, 1, asdecimal=False), nullable=False)
    source: Mapped[str] = mapped_column(String(12), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collection_delay_s: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (CheckConstraint('num_nonnulls(activity_id,strong_workout_id,manual_session_id) = 1', name='ck_session_rpe_subject'), UniqueConstraint('activity_id','source'), UniqueConstraint('strong_workout_id','source'), UniqueConstraint('manual_session_id','source'), CheckConstraint('rpe IS NULL OR (rpe >= 0 AND rpe <= 10)', name='ck_session_rpe_rpe'), CheckConstraint("source IN ('manual','garmin_fit')", name='ck_session_rpe_source'),)
