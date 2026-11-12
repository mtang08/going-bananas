"""Calendar API. Mounted with the assessment engine in TASK-030."""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, timedelta
from importlib import import_module
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.core import envelope
from app.calendar_models import CalendarVersion
from app.db import get_session
from app.services import calendar

router = APIRouter()


class BootstrapInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    anchor_date: date
    start_date: date
    pattern: dict[str, int]


class EditInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    op: Literal['add', 'modify', 'move', 'delete']
    session_uid: uuid.UUID | None = None
    fields: dict | None = None


class EditsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_head: int = Field(ge=0)
    edits: list[EditInput]
    reason: str | None = None


class RollbackInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_head: int = Field(ge=0)
    to_version: int = Field(ge=0)
    reason: str | None = None


class CompletionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int | None = Field(default=None, ge=0)
    activity_id: uuid.UUID | None = None
    strong_workout_id: uuid.UUID | None = None
    manual_session_id: uuid.UUID | None = None
    status: Literal['skipped', 'unknown'] | None = None
    modification_reason: Literal['symptom_onset', 'fatigue', 'illness', 'schedule',
                                 'weather', 'equipment', 'other'] | None = None
    reason_note: str | None = None


def get_completion_assessor() -> Callable[[Session, uuid.UUID], None]:
    # The router remains unmounted until TASK-030 provides this module.
    assessor = getattr(import_module('app.metrics.engine'), 'assess_completion', None)
    if not callable(assessor):
        raise RuntimeError('completion_assessor_missing')
    return assessor


@router.get('/calendar')
def get_calendar(start: date | None = None, end: date | None = None,
                 version: int | None = None, session: Session = Depends(get_session)) -> dict:
    today = calendar._today(session)
    return envelope(session, calendar.calendar_view(session,
        start or today - timedelta(days=7), end or today + timedelta(days=13), version))


@router.get('/calendar/versions')
def get_versions(limit: int = Query(50, ge=1, le=50),
                 session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(select(CalendarVersion).order_by(desc(CalendarVersion.number)).limit(limit)).all()
    return envelope(session, {'items': [{key: getattr(row, key) for key in
        ('id', 'number', 'parent_number', 'kind', 'actor', 'reason', 'proposal_id',
         'restored_from_number', 'block_version_id', 'created_at')} for row in rows]})


@router.get('/calendar/diff')
def get_diff(from_version: Annotated[int, Query(alias='from')],
             to_version: Annotated[int, Query(alias='to')],
             session: Session = Depends(get_session)) -> dict:
    return envelope(session, calendar.calendar_diff(session, from_version, to_version))


@router.post('/calendar/bootstrap', status_code=201)
def post_bootstrap(body: BootstrapInput, session: Session = Depends(get_session)) -> dict:
    if body.pattern != {'quality': 1, 'long': 1}:
        from app.api.core import fail
        fail('invalid_bootstrap_pattern', 'Bootstrap pattern must have one quality and one long run')
    result = calendar.write_bootstrap(session, body.anchor_date, body.start_date)
    session.commit()
    return envelope(session, result)


@router.post('/calendar/edits', status_code=201)
def post_edits(body: EditsInput, session: Session = Depends(get_session)) -> dict:
    result = calendar.apply_edits(session, body.expected_head,
        [edit.model_dump(exclude_unset=True) for edit in body.edits], body.reason)
    session.commit()
    return envelope(session, result)


@router.post('/calendar/rollback', status_code=201)
def post_rollback(body: RollbackInput, session: Session = Depends(get_session)) -> dict:
    result = calendar.rollback_calendar(session, body.expected_head, body.to_version, body.reason)
    session.commit()
    return envelope(session, result)


@router.put('/calendar/completions/{session_uid}')
def put_completion(session_uid: uuid.UUID, body: CompletionInput,
                   assess: Callable[[Session, uuid.UUID], None] = Depends(get_completion_assessor),
                   session: Session = Depends(get_session)) -> dict:
    row = calendar.put_completion(session, session_uid, body.model_dump(exclude_unset=True), assess=assess)
    session.commit()
    session.refresh(row)
    return envelope(session, calendar.completion_data(session, row))
