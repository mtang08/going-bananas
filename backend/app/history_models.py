"""Frozen tables retained for historical schema metadata."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import uuid_pk


class Checkin(Base):
    __tablename__ = "checkins"
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
    activity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("activities.id"))
    note: Mapped[str | None] = mapped_column(Text)


class CheckinRevision(Base):
    __tablename__ = "checkin_revisions"
    __table_args__ = (UniqueConstraint("checkin_id", "version"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    checkin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("checkins.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class PlanVersion(Base):
    __tablename__ = "plan_versions"
    id: Mapped[uuid.UUID] = uuid_pk()
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plan_versions.id"))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)


class PlannedSession(Base):
    __tablename__ = "planned_sessions"
    id: Mapped[uuid.UUID] = uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plan_versions.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class CompletionLink(Base):
    __tablename__ = "completion_links"
    __table_args__ = (
        UniqueConstraint("planned_session_id", "activity_id"),
        UniqueConstraint("planned_session_id", "manual_session_id"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    planned_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("planned_sessions.id"), nullable=False, unique=True
    )
    activity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("activities.id"), unique=True)
    manual_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("manual_sessions.id"), unique=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WeeklySnapshot(Base):
    __tablename__ = "weekly_snapshots"
    id: Mapped[uuid.UUID] = uuid_pk()
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(30), default="v1")
    metric_version: Mapped[str] = mapped_column(String(30), default="analytics.v1")
    data_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class LegacyImportRun(Base):
    __tablename__ = "legacy_import_runs"
    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    undo_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class LegacyImportMap(Base):
    __tablename__ = "legacy_import_map"
    id: Mapped[uuid.UUID] = uuid_pk()
    import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legacy_import_runs.id"), nullable=False
    )
    source_table: Mapped[str] = mapped_column(String(60), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("source_table", "source_id", "target_kind"),)


class CoachPlanRevision(Base):
    __tablename__ = "coach_plan_revisions"
    __table_args__ = (UniqueConstraint("idempotency_key"), UniqueConstraint("workflow", "as_of", "evidence_hash"))
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("coach_plan_revisions.id"))
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plan_versions.id"))
    workflow: Mapped[str] = mapped_column(String(12), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class CoachRecommendation(Base):
    __tablename__ = "coach_recommendations"
    __table_args__ = (UniqueConstraint("kind", "as_of", "input_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    engine: Mapped[str] = mapped_column(String(40), nullable=False)
    knowledge_version: Mapped[str] = mapped_column(String(80), nullable=False)
    data_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class CoachOutcome(Base):
    __tablename__ = "coach_outcomes"
    __table_args__ = (UniqueConstraint("recommendation_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("coach_recommendations.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    effect: Mapped[str | None] = mapped_column(String(24))
    note: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CoachOutcomeEvent(Base):
    __tablename__ = "coach_outcome_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("coach_recommendations.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    effect: Mapped[str | None] = mapped_column(String(24))
    note: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
