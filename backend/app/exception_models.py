from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import uuid_pk

EMPTY_LIST = text("'[]'::jsonb")


class ExceptionPatch(Base):
    __tablename__ = "exception_patches"
    id: Mapped[uuid.UUID] = uuid_pk()
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coach_proposals.id"), nullable=False, unique=True
    )
    calendar_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    ladder_level: Mapped[str] = mapped_column(String(20), nullable=False)
    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    window_end: Mapped[date] = mapped_column(Date, nullable=False)
    reassess_on: Mapped[date] = mapped_column(Date, nullable=False)
    monitor: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=EMPTY_LIST)
    return_criteria: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=EMPTY_LIST)
    escalate_criteria: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=EMPTY_LIST)
    unchanged: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=EMPTY_LIST)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open", server_default="open")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(8))
    resolution_note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    __table_args__ = (
        CheckConstraint(
            "category IN ('symptoms_illness','training_response','accumulated_fatigue','calendar_disruption','post_event')",
            name="ck_exception_patches_category",
        ),
        CheckConstraint("severity IN ('observe','caution','hold','escalate')", name="ck_exception_patches_severity"),
        CheckConstraint(
            "ladder_level IN ('current_session','next_session','next_days','committed_window','block')",
            name="ck_exception_patches_ladder_level",
        ),
        CheckConstraint("status IN ('open','resolved','escalated','superseded')", name="ck_exception_patches_status"),
        CheckConstraint("resolved_by IN ('coach','athlete')", name="ck_exception_patches_resolved_by"),
    )


class ExceptionFinding(Base):
    __tablename__ = "exception_findings"
    id: Mapped[uuid.UUID] = uuid_pk()
    rule_code: Mapped[str] = mapped_column(String(40), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open", server_default="open")
    summary: Mapped[str] = mapped_column(String(240), nullable=False)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    evidence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    patch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("exception_patches.id"))
    reviewed_by_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coach_proposals.id")
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_note: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    __table_args__ = (
        CheckConstraint(
            "category IN ('symptoms_illness','training_response','accumulated_fatigue','calendar_disruption','post_event')",
            name="ck_exception_findings_category",
        ),
        CheckConstraint("severity IN ('observe','caution','hold','escalate')", name="ck_exception_findings_severity"),
        CheckConstraint(
            "status IN ('open','addressed','reviewed','resolved','dismissed','expired')",
            name="ck_exception_findings_status",
        ),
        Index(
            "uq_exception_findings_active",
            "rule_code",
            "entity_key",
            unique=True,
            postgresql_where=text("status IN ('open','addressed')"),
        ),
    )
