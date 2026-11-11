"""Strong-specific canonical records; deliberately separate from Garmin activities."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class StrongWorkoutRow(Base):
    __tablename__ = "strong_workouts"
    __table_args__ = (UniqueConstraint("source_account_id", "source_identity"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_accounts.id"), nullable=False)
    source_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    source_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_records.id"), nullable=False)
    raw_object_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_objects.id"), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    local_start: Mapped[str] = mapped_column(String(19), nullable=False)
    workout_name: Mapped[str] = mapped_column(Text, nullable=False)
    duration_s: Mapped[float | None] = mapped_column(Float)
    sets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    resolution_state: Mapped[str] = mapped_column(String(30), nullable=False, default="resolved")
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
