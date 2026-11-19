"""Strength templates and planning registries; block mutations belong to proposals."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.core import envelope
from app.db import bump_data_revision, get_session, global_write_lock
from app.errors import fail
from app.models import Activity
from app.planning_models import Block, BlockBenchmarkResult, BlockVersion, Event, Goal
from app.services.block_benchmark import RUN_SPORTS, active_block_version, benchmark_spec, benchmark_status, status_data
from app.services.strength_routine import replace_routine, routine_view
from app.services.timezone import athlete_today, athlete_tz

router = APIRouter()


class BenchmarkActivityInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    activity_id: uuid.UUID | None


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
    global_write_lock(session)


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
        'proposal_id', 'benchmark')}


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
    row = active_block_version(session)
    return envelope(session, {**_block(row), 'benchmark_status': status_data(
        benchmark_status(session, row, athlete_today(session)))} if row else None)


@router.get('/blocks/benchmarks')
def get_block_benchmarks(session: Session = Depends(get_session)) -> dict:
    rows = session.execute(select(BlockBenchmarkResult, BlockVersion.objective).join(BlockVersion,
        (BlockVersion.block_uid == BlockBenchmarkResult.block_uid)
        & (BlockVersion.version == BlockBenchmarkResult.block_version))
        .where(BlockBenchmarkResult.outcome.is_not(None))
        .order_by(desc(BlockBenchmarkResult.local_date).nulls_last(), desc(BlockBenchmarkResult.updated_at))).all()
    keys = ('id', 'block_uid', 'block_version', 'protocol', 'distance_m', 'local_date', 'result_s', 'outcome',
            'compared_with', 'match_method', 'activity_id', 'event_id')
    return envelope(session, {'items': [{**{key: getattr(row, key) for key in keys}, 'objective': objective}
                                        for row, objective in rows]})


@router.put('/blocks/{block_uid}/benchmark-activity')
def put_benchmark_activity(block_uid: uuid.UUID, body: BenchmarkActivityInput,
                           session: Session = Depends(get_session)) -> dict:
    _writer_lock(session)
    version = active_block_version(session)
    if version is None or version.block_uid != block_uid:
        fail('block_not_found', 'Block not found', 404)
    spec = benchmark_spec(version)
    if spec is None:
        fail('benchmark_not_set', 'The active block has no benchmark', 409)
    activity = session.get(Activity, body.activity_id) if body.activity_id else None
    if body.activity_id and (activity is None or activity.sport not in RUN_SPORTS):
        fail('activity_not_found', 'Activity not found', 404)
    row = session.scalar(select(BlockBenchmarkResult).where(BlockBenchmarkResult.block_uid == version.block_uid,
                                                            BlockBenchmarkResult.block_version == version.version))
    now = datetime.now(UTC)
    if activity is not None:
        if row is None:
            row = BlockBenchmarkResult(block_uid=version.block_uid, block_version=version.version)
            session.add(row)
        row.match_method = 'manual'
        row.activity_id = activity.id
        row.event_id = spec.event_id
        row.protocol = spec.protocol
        row.distance_m = round(activity.distance_m) if activity.distance_m is not None else None
        row.local_date = activity.start_at.astimezone(athlete_tz(session)).date()
        row.result_s = round(activity.timer_s) if activity.timer_s is not None else None
        row.updated_at = now
    elif row is not None:
        row.match_method = 'auto'
        row.activity_id = None
        row.distance_m = None
        row.local_date = None
        row.result_s = None
        row.updated_at = now
    bump_data_revision(session)
    session.commit()
    return envelope(session, {'benchmark': version.benchmark,
                              'benchmark_status': status_data(benchmark_status(session, version, athlete_today(session)))})


@router.get('/blocks/{block_uid}/history')
def get_block_history(block_uid: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    block = session.scalar(select(Block).where(Block.block_uid == block_uid))
    if block is None:
        fail('block_not_found', 'Block not found', 404)
    rows = session.scalars(select(BlockVersion).where(BlockVersion.block_uid == block_uid)
        .order_by(BlockVersion.version, BlockVersion.id)).all()
    return envelope(session, {'items': [_block(row) for row in rows]})
