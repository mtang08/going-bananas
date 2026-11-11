from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class AppState(Base):
    __tablename__ = 'app_state'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ProfileVersion(Base):
    __tablename__ = 'profile_versions'
    id: Mapped[uuid.UUID] = uuid_pk()
    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), default='America/New_York')
    cycle_anchor: Mapped[date | None] = mapped_column(Date)
    anchor_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    strength_days_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    scheduled_strength_days: Mapped[list[int]] = mapped_column(JSONB, default=list)
    strength_schedule_mode: Mapped[str] = mapped_column(String(16), default='weekly', nullable=False)
    strength_week_a_start: Mapped[date | None] = mapped_column(Date)
    strength_week_a_days: Mapped[list[int]] = mapped_column(JSONB, default=list)
    strength_week_b_days: Mapped[list[int]] = mapped_column(JSONB, default=list)
    mobility_week_a_days: Mapped[list[int]] = mapped_column(JSONB, default=list)
    mobility_week_b_days: Mapped[list[int]] = mapped_column(JSONB, default=list)
    mobility_optional_days: Mapped[list[int]] = mapped_column(JSONB, default=list)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    unknowns: Mapped[list[str]] = mapped_column(JSONB, default=list)


class SourceAccount(Base):
    __tablename__ = 'source_accounts'
    __table_args__ = (UniqueConstraint('provider', 'account_scope'),)
    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    account_scope: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImportBatch(Base):
    __tablename__ = 'import_batches'
    id: Mapped[uuid.UUID] = uuid_pk()
    source_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='running')
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    adapter_version: Mapped[str] = mapped_column(String(80), default='unknown')
    counters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))


class RawObject(Base):
    __tablename__ = 'raw_objects'
    id: Mapped[uuid.UUID] = uuid_pk()
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceRecord(Base):
    __tablename__ = 'source_records'
    __table_args__ = (UniqueConstraint('source_account_id', 'source_identity', 'payload_hash'),)
    id: Mapped[uuid.UUID] = uuid_pk()
    source_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('source_accounts.id'), nullable=False)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('import_batches.id'))
    raw_object_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('raw_objects.id'))
    source_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    rejected_reason: Mapped[str | None] = mapped_column(String(100))


class Activity(Base):
    __tablename__ = 'activities'
    __table_args__ = (UniqueConstraint('source_account_id', 'garmin_id'), UniqueConstraint('source_account_id', 'source_identity'))
    id: Mapped[uuid.UUID] = uuid_pk()
    source_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('source_accounts.id'))
    garmin_id: Mapped[str | None] = mapped_column(String(100))
    source_identity: Mapped[str | None] = mapped_column(String(256))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    original_start: Mapped[str] = mapped_column(String(100), nullable=False)
    source_timezone: Mapped[str | None] = mapped_column(String(100))
    local_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sport: Mapped[str] = mapped_column(String(50), nullable=False)
    subtype: Mapped[str | None] = mapped_column(String(80))
    distance_m: Mapped[float | None] = mapped_column(Float)
    elapsed_s: Mapped[float | None] = mapped_column(Float)
    moving_s: Mapped[float | None] = mapped_column(Float)
    avg_hr_bpm: Mapped[float | None] = mapped_column(Float)
    cadence_spm: Mapped[float | None] = mapped_column(Float)
    source_workout_label: Mapped[str | None] = mapped_column(String(40))
    canonical_revision: Mapped[int] = mapped_column(Integer, default=1)
    resolution_state: Mapped[str] = mapped_column(String(30), default='resolved')
    field_provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ActivitySource(Base):
    __tablename__ = 'activity_sources'
    __table_args__ = (UniqueConstraint('activity_id', 'source_record_id'),)
    id: Mapped[uuid.UUID] = uuid_pk()
    activity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('activities.id'), nullable=False)
    source_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('source_records.id'), nullable=False)
    selected_fields: Mapped[list[str]] = mapped_column(JSONB, default=list)


class ActivityAnnotation(Base):
    __tablename__ = 'activity_annotations'
    __table_args__ = (UniqueConstraint('activity_id', 'version'),)
    id: Mapped[uuid.UUID] = uuid_pk()
    activity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('activities.id'), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    workout_label: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RecoveryObservation(Base):
    __tablename__ = 'recovery_observations'
    __table_args__ = (UniqueConstraint('source_account_id', 'metric', 'source_date', 'statistic'),)
    id: Mapped[uuid.UUID] = uuid_pk()
    source_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('source_accounts.id'), nullable=False)
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('source_records.id'))
    metric: Mapped[str] = mapped_column(String(50), nullable=False)
    source_date: Mapped[date] = mapped_column(Date, nullable=False)
    time_semantics: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    statistic: Mapped[str] = mapped_column(String(100), nullable=False)
    source_revision: Mapped[str] = mapped_column(String(100), nullable=False)


class CoverageInterval(Base):
    __tablename__ = 'coverage_intervals'
    id: Mapped[uuid.UUID] = uuid_pk()
    dataset: Mapped[str] = mapped_column(String(50), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    observed_start: Mapped[date | None] = mapped_column(Date)
    observed_end: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String(100))
    fully_enumerated: Mapped[bool] = mapped_column(Boolean, default=False)


class SyncJob(Base):
    __tablename__ = 'sync_jobs'
    id: Mapped[uuid.UUID] = uuid_pk()
    dataset: Mapped[str] = mapped_column(String(50), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default='queued')
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    counters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))


class SyncState(Base):
    __tablename__ = 'sync_state'
    dataset: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    newest_observation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_start: Mapped[date | None] = mapped_column(Date)
    requested_end: Mapped[date | None] = mapped_column(Date)
    fully_enumerated: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(40), default='unavailable')
    reason: Mapped[str | None] = mapped_column(String(100))


class Checkin(Base):
    __tablename__ = 'checkins'
    id: Mapped[uuid.UUID] = uuid_pk()
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    symptoms: Mapped[str] = mapped_column(String(20), nullable=False)
    change: Mapped[str | None] = mapped_column(String(20))
    gait: Mapped[str] = mapped_column(String(20), nullable=False)
    feeling: Mapped[str] = mapped_column(String(20), nullable=False)
    effort: Mapped[int | None] = mapped_column(Integer)
    activity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('activities.id'))
    note: Mapped[str | None] = mapped_column(Text)


class CheckinRevision(Base):
    __tablename__ = 'checkin_revisions'
    __table_args__ = (UniqueConstraint('checkin_id', 'version'),)
    id: Mapped[uuid.UUID] = uuid_pk()
    checkin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('checkins.id'), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ManualSession(Base):
    __tablename__ = 'manual_sessions'
    id: Mapped[uuid.UUID] = uuid_pk()
    version: Mapped[int] = mapped_column(Integer, default=1)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    time: Mapped[time | None] = mapped_column(Time)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    duration_s: Mapped[float | None] = mapped_column(Float)
    effort: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    linked_activity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('activities.id'))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlanVersion(Base):
    __tablename__ = 'plan_versions'
    id: Mapped[uuid.UUID] = uuid_pk()
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('plan_versions.id'))
    status: Mapped[str] = mapped_column(String(30), default='draft')
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)


class PlannedSession(Base):
    __tablename__ = 'planned_sessions'
    id: Mapped[uuid.UUID] = uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('plan_versions.id'), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class CompletionLink(Base):
    __tablename__ = 'completion_links'
    __table_args__ = (UniqueConstraint('planned_session_id', 'activity_id'), UniqueConstraint('planned_session_id', 'manual_session_id'))
    id: Mapped[uuid.UUID] = uuid_pk()
    planned_session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('planned_sessions.id'), nullable=False, unique=True)
    activity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('activities.id'), unique=True)
    manual_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('manual_sessions.id'), unique=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Conflict(Base):
    __tablename__ = 'conflicts'
    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default='open')
    activity_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    manual_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('manual_sessions.id'))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    resolution: Mapped[str | None] = mapped_column(String(30))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WeeklySnapshot(Base):
    __tablename__ = 'weekly_snapshots'
    id: Mapped[uuid.UUID] = uuid_pk()
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(30), default='v1')
    metric_version: Mapped[str] = mapped_column(String(30), default='analytics.v1')
    data_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
