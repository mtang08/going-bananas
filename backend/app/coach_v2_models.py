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
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import uuid_pk


class CoachSnapshot(Base):
    __tablename__ = 'coach_snapshots'
    id: Mapped[uuid.UUID] = uuid_pk()
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calendar_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    block_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    data_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    kb_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    kb_package_version: Mapped[str] = mapped_column(String(30), nullable=False)
    kb_routes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    approx_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (CheckConstraint("operation IN ('proceed_or_modify_today','review_rolling_plan','review_training_block','select_quality_session','recalibrate_intensity','handle_goal_or_race_change')", name='ck_coach_snapshots_operation'),)

class CoachProposal(Base):
    __tablename__ = 'coach_proposals'
    id: Mapped[uuid.UUID] = uuid_pk()
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('coach_snapshots.id'), nullable=False)
    base_calendar_version: Mapped[int] = mapped_column(Integer, nullable=False)
    base_block_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_ids: Mapped[list[Any]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default='{}')
    policy_ids: Mapped[list[Any]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default='{}')
    recipe_ids: Mapped[list[Any]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default='{}')
    follow_up: Mapped[str | None] = mapped_column(Text)
    escalation: Mapped[str | None] = mapped_column(String(32))
    block_change: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    anchor_changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    decision_idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    decision_hash: Mapped[str | None] = mapped_column(String(64))
    decision_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_errors: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    skill_version: Mapped[str] = mapped_column(String(20), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    __table_args__ = (CheckConstraint("operation IN ('proceed_or_modify_today','review_rolling_plan','review_training_block','select_quality_session','recalibrate_intensity','handle_goal_or_race_change')", name='ck_coach_proposals_operation'), CheckConstraint("status IN ('pending','accepted','partially_accepted','rejected','stale','invalid')", name='ck_coach_proposals_status'), CheckConstraint("escalation IN ('proceed_or_modify_today','review_rolling_plan','review_training_block','select_quality_session','recalibrate_intensity','handle_goal_or_race_change')", name='ck_coach_proposals_escalation'))

class CoachProposalChange(Base):
    __tablename__ = 'coach_proposal_changes'
    id: Mapped[uuid.UUID] = uuid_pk()
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('coach_proposals.id'), nullable=False)
    change_id: Mapped[str] = mapped_column(String(12), nullable=False)
    op: Mapped[str] = mapped_column(String(10), nullable=False)
    session_uid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    __table_args__ = (UniqueConstraint('proposal_id','change_id'), CheckConstraint("op IN ('add','modify','move','delete')", name='ck_coach_proposal_changes_op'), CheckConstraint("decision IN ('pending','accepted','rejected')", name='ck_coach_proposal_changes_decision'),)

class CoachDecisionKey(Base):
    __tablename__ = 'coach_decision_keys'
    idempotency_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('coach_proposals.id'), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class DailyGuidance(Base):
    __tablename__ = 'daily_guidance'
    id: Mapped[uuid.UUID] = uuid_pk()
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    checkin_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    engine: Mapped[str] = mapped_column(String(20), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    session_uid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    missing_inputs: Mapped[list[Any]] = mapped_column(ARRAY(String(40)), nullable=False, default=list, server_default='{}')
    coach_review_suggested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default='false')
    trigger_codes: Mapped[list[Any]] = mapped_column(ARRAY(String(40)), nullable=False, default=list, server_default='{}')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint('local_date','input_hash'), CheckConstraint("decision IN ('proceed','modify','reschedule','rest','seek_clinical_input')", name='ck_daily_guidance_decision'),)
