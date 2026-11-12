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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import uuid_pk


class CalendarVersion(Base):
    __tablename__ = 'calendar_versions'
    id: Mapped[uuid.UUID] = uuid_pk()
    number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    parent_number: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    restored_from_number: Mapped[int | None] = mapped_column(Integer)
    block_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (CheckConstraint("kind IN ('bootstrap','manual_edit','proposal_accept','rollback','legacy_import')", name='ck_calendar_versions_kind'), CheckConstraint("actor IN ('system','user','coach')", name='ck_calendar_versions_actor'),)

class CalendarSessionRevision(Base):
    __tablename__ = 'calendar_session_revisions'
    id: Mapped[uuid.UUID] = uuid_pk()
    session_uid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    calendar_version_number: Mapped[int] = mapped_column(Integer, ForeignKey('calendar_versions.number'), nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default='false')
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default='0')
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    recipe_id: Mapped[str | None] = mapped_column(String(10))
    custom: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default='false')
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default='false')
    legacy_unstructured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default='false')
    legacy_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    placeholder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default='false')
    intent: Mapped[str] = mapped_column(String(200), nullable=False)
    certainty: Mapped[str] = mapped_column(String(12), nullable=False)
    planned_duration_s: Mapped[int | None] = mapped_column(Integer)
    planned_distance_m: Mapped[int | None] = mapped_column(Integer)
    structure: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    strength_slot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint('session_uid','revision'), CheckConstraint("kind IN ('run','strength','cross','rest','mobility')", name='ck_calendar_session_revisions_kind'), CheckConstraint("certainty IN ('committed','provisional')", name='ck_calendar_session_revisions_certainty'), CheckConstraint('slot >= 0', name='ck_calendar_session_revisions_slot'), CheckConstraint('planned_duration_s IS NULL OR planned_duration_s > 0', name='ck_calendar_session_revisions_planned_duration_s'), CheckConstraint('planned_distance_m IS NULL OR planned_distance_m > 0', name='ck_calendar_session_revisions_planned_distance_m'), Index('ix_calendar_session_revisions_calendar_version_number','calendar_version_number'), Index('ix_calendar_session_revisions_local_date','local_date'))

class SessionCompletion(Base):
    __tablename__ = 'session_completions'
    id: Mapped[uuid.UUID] = uuid_pk()
    session_uid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    activity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('activities.id'), unique=True)
    strong_workout_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('strong_workouts.id'), unique=True)
    manual_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('manual_sessions.id'), unique=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    match_method: Mapped[str] = mapped_column(String(20), nullable=False)
    modification_reason: Mapped[str | None] = mapped_column(String(40))
    reason_note: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default='1')
    input_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default='1')
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (CheckConstraint('num_nonnulls(activity_id,strong_workout_id,manual_session_id) <= 1', name='ck_session_completions_subject'), CheckConstraint("status IN ('skipped','unknown') OR num_nonnulls(activity_id,strong_workout_id,manual_session_id) = 1", name='ck_session_completions_status_subject'), CheckConstraint("status IN ('completed_as_planned','completed_modified','partial','moved','skipped','extra','unknown')", name='ck_session_completions_status'), CheckConstraint("match_method IN ('explicit','auto_same_day','confirmed_move','user_marked','none')", name='ck_session_completions_match_method'), CheckConstraint("modification_reason IN ('symptom_onset','fatigue','illness','schedule','weather','equipment','other')", name='ck_session_completions_modification_reason'),)

class LegacyImportRun(Base):
    __tablename__ = 'legacy_import_runs'
    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    undo_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

class LegacyImportMap(Base):
    __tablename__ = 'legacy_import_map'
    id: Mapped[uuid.UUID] = uuid_pk()
    import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('legacy_import_runs.id'), nullable=False)
    source_table: Mapped[str] = mapped_column(String(60), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint('source_table','source_id','target_kind'),)

class LegacyUndoRequest(Base):
    __tablename__ = 'legacy_undo_requests'
    idempotency_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('legacy_import_runs.id'), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
