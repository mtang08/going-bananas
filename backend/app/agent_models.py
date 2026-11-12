"""Append-only audit of externally authored coaching decisions."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CoachPlanRevision(Base):
    __tablename__ = 'coach_plan_revisions'
    __table_args__ = (UniqueConstraint('idempotency_key'), UniqueConstraint('workflow', 'as_of', 'evidence_hash'))
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('coach_plan_revisions.id'))
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('plan_versions.id'))
    workflow: Mapped[str] = mapped_column(String(12), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
