from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
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


class Block(Base):
    __tablename__ = 'blocks'
    id: Mapped[uuid.UUID] = uuid_pk()
    block_uid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class BlockVersion(Base):
    __tablename__ = 'block_versions'
    id: Mapped[uuid.UUID] = uuid_pk()
    block_uid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('blocks.block_uid'), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    maintained_qualities: Mapped[list[Any]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default='{}')
    non_goals: Mapped[list[Any]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default='{}')
    eligible_recipe_ids: Mapped[list[Any]] = mapped_column(ARRAY(String(10)), nullable=False, default=list, server_default='{}')
    progression_dimension: Mapped[str] = mapped_column(String(40), nullable=False)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    review_date: Mapped[date] = mapped_column(Date, nullable=False)
    completion_indicators: Mapped[list[Any]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default='{}')
    early_review_triggers: Mapped[list[Any]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default='{}')
    objective_status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (UniqueConstraint('block_uid','version'), CheckConstraint("status IN ('draft','active','consolidating','completed','replaced','ended')", name='ck_block_versions_status'), CheckConstraint("progression_dimension IN ('duration','frequency','long_run','quality_volume','intensity','none')", name='ck_block_versions_progression_dimension'), CheckConstraint("objective_status IN ('unresolved','partially_achieved','achieved','not_achieved')", name='ck_block_versions_objective_status'),)

class BlockDecision(Base):
    __tablename__ = 'block_decisions'
    id: Mapped[uuid.UUID] = uuid_pk()
    block_uid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('blocks.block_uid'))
    decision: Mapped[str] = mapped_column(String(12), nullable=False)
    from_version: Mapped[int | None] = mapped_column(Integer)
    to_version: Mapped[int | None] = mapped_column(Integer)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids: Mapped[list[Any]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default='{}')
    policy_ids: Mapped[list[Any]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default='{}')
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (CheckConstraint("decision IN ('start','continue','extend','consolidate','transition','replace','end')", name='ck_block_decisions_decision'),)

class Goal(Base):
    __tablename__ = 'goals'
    id: Mapped[uuid.UUID] = uuid_pk()
    text: Mapped[str] = mapped_column(Text, nullable=False)
    horizon: Mapped[str] = mapped_column(String(12), nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default='1')
    __table_args__ = (CheckConstraint("horizon IN ('3_6_months','season','long_term')", name='ck_goals_horizon'), CheckConstraint("status IN ('active','paused','done','dropped')", name='ck_goals_status'),)

class Event(Base):
    __tablename__ = 'events'
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    distance_m: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    result_s: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default='1')
    __table_args__ = (CheckConstraint("priority IN ('target','supported_exposure','benchmark','optional')", name='ck_events_priority'), CheckConstraint("status IN ('planned','registered','completed','cancelled')", name='ck_events_status'),)

class StrengthRoutineSlot(Base):
    __tablename__ = 'strength_routine_slots'
    id: Mapped[uuid.UUID] = uuid_pk()
    label: Mapped[str] = mapped_column(String(40), nullable=False)
    default_weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    lower_body_cost: Mapped[str] = mapped_column(String(10), nullable=False)
    typical_duration_s: Mapped[int | None] = mapped_column(Integer)
    main_lower_body_lifts: Mapped[list[Any]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default='{}')
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default='true')
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default='1')
    __table_args__ = (CheckConstraint("lower_body_cost IN ('low','moderate','high')", name='ck_strength_routine_slots_lower_body_cost'), CheckConstraint('default_weekday BETWEEN 0 AND 6', name='ck_strength_routine_slots_default_weekday'),)

class IntensityAnchor(Base):
    __tablename__ = 'intensity_anchors'
    id: Mapped[uuid.UUID] = uuid_pk()
    anchor_key: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    value_low: Mapped[float] = mapped_column(Float, nullable=False)
    value_high: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(8), nullable=False)
    protocol: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    calibrated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    review_after: Mapped[date] = mapped_column(Date, nullable=False)
    source_activity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('activities.id'))
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('events.id'))
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    conditions: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    supersedes_key: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (CheckConstraint('value_high IS NULL OR value_low <= value_high', name='ck_intensity_anchors_value_high'), CheckConstraint("(kind LIKE 'hr_%' AND unit='bpm') OR (kind LIKE 'speed_%' AND unit='mps') OR (kind IN ('performance_5k','performance_1mile') AND unit='s') OR (kind='performance_3min' AND unit='m') OR (kind='performance_20_30min' AND unit='mps')", name='ck_intensity_anchors_unit_kind'), CheckConstraint("kind IN ('hr_aerobic_upper','hr_threshold_lower','speed_aerobic_upper','speed_threshold_lower','performance_5k','performance_1mile','performance_3min','performance_20_30min')", name='ck_intensity_anchors_kind'), CheckConstraint("unit IN ('bpm','mps','s','m')", name='ck_intensity_anchors_unit'), CheckConstraint("protocol IN ('race_5k','time_trial_5k','time_trial_1mile','time_trial_3min','time_trial_20_30min','workout_derived','lab_test','manual')", name='ck_intensity_anchors_protocol'), CheckConstraint("confidence IN ('high','moderate','low','insufficient')", name='ck_intensity_anchors_confidence'), CheckConstraint("status IN ('provisional','active','expired','invalid')", name='ck_intensity_anchors_status'))
