"""Strength templates and planning registries; block mutations belong to proposals."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.api.core import envelope, fail
from app.db import get_session
from app.models import AppState
from app.planning_models import Block, BlockVersion, Event, Goal
from app.services.strength_routine import LOCK_ID, replace_routine, routine_view

router = APIRouter()


class SlotInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    label: str
    default_weekday: int
    lower_body_cost: Literal['low', 'moderate', 'high']
    typical_duration_s: int | None = None
    main_lower_body_lifts: list[str] = Field(default_factory=list)
    active: bool = True


class RoutineInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=0)
    slots: list[SlotInput]


class GoalInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str
    horizon: Literal['3_6_months', 'season', 'long_term']
    priority: int = Field(ge=1)

    @field_validator('text')
    @classmethod
    def text_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('Goal text must be nonblank')
        return value.strip()


class GoalPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)
    text: str | None = None
    horizon: Literal['3_6_months', 'season', 'long_term'] | None = None
    priority: int | None = Field(default=None, ge=1)
    status: Literal['active', 'paused', 'done', 'dropped'] | None = None

    @field_validator('text')
    @classmethod
    def text_nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError('Goal text must be nonblank')
        return value.strip() if value is not None else None


class EventInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str
    event_date: date
    distance_m: int | None = Field(default=None, gt=0)
    priority: Literal['target', 'supported_exposure', 'benchmark', 'optional']
    status: Literal['planned', 'registered', 'completed', 'cancelled'] = 'planned'
    result_s: int | None = Field(default=None, gt=0)

    @field_validator('name')
    @classmethod
    def name_nonblank(cls, value: str) -> str:
        if not value.strip() or len(value.strip()) > 100:
            raise ValueError('Event name must be 1–100 characters')
        return value.strip()


class EventPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)
    name: str | None = None
    event_date: date | None = None
    distance_m: int | None = Field(default=None, gt=0)
    priority: Literal['target', 'supported_exposure', 'benchmark', 'optional'] | None = None
    status: Literal['planned', 'registered', 'completed', 'cancelled'] | None = None
    result_s: int | None = Field(default=None, gt=0)

    @field_validator('name')
    @classmethod
    def name_nonblank(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or len(value.strip()) > 100):
            raise ValueError('Event name must be 1–100 characters')
        return value.strip() if value is not None else None


def _writer_lock(session: Session) -> None:
    session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': LOCK_ID})
    state = session.get(AppState, 1, with_for_update=True)
    if state is None or state.planning_authority != 'calendar':
        fail('planning_not_active', 'Calendar planning is not active', 409)


def _goal(row: Goal) -> dict:
    return {key: getattr(row, key) for key in ('id', 'text', 'horizon', 'priority', 'status', 'version')}


def _event(row: Event) -> dict:
    return {key: getattr(row, key) for key in ('id', 'name', 'event_date', 'distance_m',
            'priority', 'status', 'result_s', 'version')}


def _block(row: BlockVersion) -> dict:
    return {key: getattr(row, key) for key in ('id', 'block_uid', 'version', 'status',
        'objective', 'rationale', 'maintained_qualities', 'non_goals', 'eligible_recipe_ids',
        'progression_dimension', 'constraints', 'start_date', 'review_date',
        'completion_indicators', 'early_review_triggers', 'objective_status', 'created_at',
        'proposal_id')}


@router.get('/strength-routine')
def get_strength_routine(session: Session = Depends(get_session)) -> dict:
    return envelope(session, routine_view(session))


@router.put('/strength-routine')
def put_strength_routine(body: RoutineInput, session: Session = Depends(get_session)) -> dict:
    data = replace_routine(session, body.expected_version,
        [slot.model_dump() for slot in body.slots])
    session.commit()
    return envelope(session, data)


@router.get('/goals')
def get_goals(session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(select(Goal).order_by(Goal.priority, Goal.id)).all()
    return envelope(session, {'items': [_goal(row) for row in rows]})


@router.post('/goals', status_code=201)
def post_goal(body: GoalInput, session: Session = Depends(get_session)) -> dict:
    _writer_lock(session)
    row = Goal(**body.model_dump(), status='active', version=1)
    session.add(row)
    session.commit()
    return envelope(session, _goal(row))


@router.patch('/goals/{goal_id}')
def patch_goal(goal_id: uuid.UUID, body: GoalPatch, session: Session = Depends(get_session)) -> dict:
    _writer_lock(session)
    row = session.get(Goal, goal_id)
    if row is None:
        fail('goal_not_found', 'Goal not found', 404)
    if row.version != body.expected_version:
        fail('version_conflict', 'Goal changed; reload before editing', 409)
    for key, value in body.model_dump(exclude={'expected_version'}, exclude_unset=True).items():
        if value is None:
            fail('invalid_goal', 'Goal fields cannot be null')
        setattr(row, key, value)
    row.version += 1
    session.commit()
    return envelope(session, _goal(row))


@router.get('/events')
def get_events(session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(select(Event).order_by(Event.event_date, Event.id)).all()
    return envelope(session, {'items': [_event(row) for row in rows]})


@router.post('/events', status_code=201)
def post_event(body: EventInput, session: Session = Depends(get_session)) -> dict:
    _writer_lock(session)
    row = Event(**body.model_dump(), version=1)
    session.add(row)
    session.commit()
    return envelope(session, _event(row))


@router.patch('/events/{event_id}')
def patch_event(event_id: uuid.UUID, body: EventPatch, session: Session = Depends(get_session)) -> dict:
    _writer_lock(session)
    row = session.get(Event, event_id)
    if row is None:
        fail('event_not_found', 'Event not found', 404)
    if row.version != body.expected_version:
        fail('version_conflict', 'Event changed; reload before editing', 409)
    for key, value in body.model_dump(exclude={'expected_version'}, exclude_unset=True).items():
        setattr(row, key, value)
    if not row.name or not row.name.strip() or row.event_date is None or row.priority is None or row.status is None:
        fail('invalid_event', 'Required event fields cannot be null')
    row.version += 1
    session.commit()
    return envelope(session, _event(row))


@router.get('/blocks/active')
def get_active_block(session: Session = Depends(get_session)) -> dict:
    latest = select(BlockVersion.block_uid, func.max(BlockVersion.version).label('version'))\
        .group_by(BlockVersion.block_uid).subquery()
    row = session.scalar(select(BlockVersion).join(latest,
        (BlockVersion.block_uid == latest.c.block_uid) & (BlockVersion.version == latest.c.version))
        .where(BlockVersion.status.in_(('active', 'consolidating')))
        .order_by(desc(BlockVersion.created_at), desc(BlockVersion.version), desc(BlockVersion.id)).limit(1))
    return envelope(session, _block(row) if row else None)


@router.get('/blocks/{block_uid}/history')
def get_block_history(block_uid: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    block = session.scalar(select(Block).where(Block.block_uid == block_uid))
    if block is None:
        fail('block_not_found', 'Block not found', 404)
    rows = session.scalars(select(BlockVersion).where(BlockVersion.block_uid == block_uid)
        .order_by(BlockVersion.version, BlockVersion.id)).all()
    return envelope(session, {'items': [_block(row) for row in rows]})
