from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import uuid_pk


class MetricConfig(Base):
    __tablename__ = 'metric_configs'
    id: Mapped[uuid.UUID] = uuid_pk()
    metric_id: Mapped[str] = mapped_column(String(60), nullable=False)
    method_version: Mapped[str] = mapped_column(String(40), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint('metric_id','method_version','config_hash'),)

class MetricResult(Base):
    __tablename__ = 'metric_results'
    id: Mapped[uuid.UUID] = uuid_pk()
    metric_id: Mapped[str] = mapped_column(String(60), nullable=False)
    method_version: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(12), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(120), nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_label: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    quality_status: Mapped[str | None] = mapped_column(String(14))
    value: Mapped[Any | None] = mapped_column(JSONB)
    unit: Mapped[str | None] = mapped_column(String(16))
    reason_codes: Mapped[list[Any]] = mapped_column(ARRAY(String(40)), nullable=False, default=list, server_default='{}')
    quality_flags: Mapped[list[Any]] = mapped_column(ARRAY(String(40)), nullable=False, default=list, server_default='{}')
    source_refs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    anchor_keys: Mapped[list[Any]] = mapped_column(ARRAY(String(40)), nullable=False, default=list, server_default='{}')
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    anchor_set_hash: Mapped[str | None] = mapped_column(String(64))
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dependency_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default='true')
    __table_args__ = (CheckConstraint("subject_type IN ('activity','session','window','night','report')", name='ck_metric_results_subject_type'), CheckConstraint("status IN ('available','partial','missing','invalid','not_applicable','not_assessable')", name='ck_metric_results_status'), CheckConstraint("quality_status IN ('good','limited','insufficient')", name='ck_metric_results_quality_status'), Index('uq_metric_results_identity', 'metric_id','method_version','subject_key','config_hash', text("coalesce(anchor_set_hash, '')"),'dependency_hash', unique=True), Index('uq_metric_results_current','metric_id','method_version','subject_key', unique=True, postgresql_where=text('is_current')),)

class Prompt(Base):
    __tablename__ = 'prompts'
    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    activity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('activities.id'))
    session_uid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    __table_args__ = (CheckConstraint("kind IN ('rpe','delayed_symptom','unmatched_session','missing_activity')", name='ck_prompts_kind'), CheckConstraint("status IN ('open','answered','dismissed','expired')", name='ck_prompts_status'), Index('uq_prompts_kind_activity_session','kind','activity_id','session_uid', unique=True, postgresql_nulls_not_distinct=True),)
