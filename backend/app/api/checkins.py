"""Permanent v2 check-in, RPE, prompt and daily guidance routes."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.api.core import current_profile, envelope, fail
from app.checkin_models import Checkin
from app.coach_v2_models import DailyGuidance
from app.db import get_session
from app.metric_models import Prompt
from app.services.calendar import _lock
from app.services.checkins import (
    CheckinCreate,
    CheckinPatch,
    checkin_data,
    create_checkin,
    patch_checkin,
    save_manual_rpe,
)
from app.services.daily_guidance import guidance_data, persist_daily_guidance

router = APIRouter()


class RpeInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    rpe: float

    @field_validator('rpe', mode='before')
    @classmethod
    def valid_rpe(cls, value: object) -> float:
        from app.services.checkins import _measurement
        return _measurement(value)


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')


def _today(session: Session) -> date:
    profile = current_profile(session)
    return datetime.now(UTC).astimezone(ZoneInfo(profile.timezone if profile else 'America/New_York')).date()


@router.post('/v2/checkins')
def post_checkin(body: CheckinCreate, session: Session = Depends(get_session)) -> JSONResponse:
    result, created = create_checkin(session, body.model_dump())
    session.commit()
    return JSONResponse(status_code=201 if created else 200,
        content=jsonable_encoder(envelope(session, result)))


@router.patch('/v2/checkins/{checkin_id}')
def patch_checkin_route(checkin_id: uuid.UUID, body: CheckinPatch,
                        session: Session = Depends(get_session)) -> dict:
    result = patch_checkin(session, checkin_id, body.model_dump(exclude_unset=True))
    session.commit()
    return envelope(session, result)


@router.get('/v2/checkins')
def get_checkins(start: date | None = None, end: date | None = None,
                 session: Session = Depends(get_session)) -> dict:
    profile = current_profile(session)
    zone = ZoneInfo(profile.timezone if profile else 'America/New_York')
    rows = session.scalars(select(Checkin).order_by(desc(Checkin.observed_at), desc(Checkin.id))).all()
    return envelope(session, {'items': [checkin_data(session, row) for row in rows
        if (start is None or row.observed_at.astimezone(zone).date() >= start)
        and (end is None or row.observed_at.astimezone(zone).date() <= end)]})


@router.get('/coach/v2/daily')
def get_daily(session: Session = Depends(get_session)) -> dict:
    row = session.scalar(select(DailyGuidance).where(DailyGuidance.local_date == _today(session))
        .order_by(desc(DailyGuidance.created_at), desc(DailyGuidance.id)).limit(1))
    return envelope(session, guidance_data(row) if row else None)


@router.post('/coach/v2/daily/request')
def request_daily(body: EmptyRequest, session: Session = Depends(get_session)) -> dict:
    now = datetime.now(UTC)
    result = persist_daily_guidance(session, today=_today(session), now=now)
    session.commit()
    return envelope(session, result)


@router.put('/activities/{activity_id}/rpe')
def put_activity_rpe(activity_id: uuid.UUID, body: RpeInput,
                     session: Session = Depends(get_session)) -> dict:
    result = save_manual_rpe(session, activity_id=activity_id, rpe=body.rpe, now=datetime.now(UTC))
    session.commit()
    return envelope(session, result)


@router.put('/strength/history/{workout_id}/rpe')
def put_strong_rpe(workout_id: uuid.UUID, body: RpeInput,
                   session: Session = Depends(get_session)) -> dict:
    result = save_manual_rpe(session, strong_workout_id=workout_id, rpe=body.rpe, now=datetime.now(UTC))
    session.commit()
    return envelope(session, result)


@router.get('/prompts')
def get_prompts(session: Session = Depends(get_session)) -> dict:
    now = datetime.now(UTC)
    rows = session.scalars(select(Prompt).where(Prompt.status == 'open',
        Prompt.opens_at <= now, or_(Prompt.closes_at.is_(None), Prompt.closes_at > now))
        .order_by(desc(Prompt.opens_at), desc(Prompt.id))).all()
    return envelope(session, {'items': [{key: getattr(row, key) for key in
        ('id', 'kind', 'activity_id', 'session_uid', 'opens_at', 'closes_at', 'status')} for row in rows]})


@router.post('/prompts/{prompt_id}/dismiss')
def dismiss_prompt(prompt_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    _lock(session)
    row = session.get(Prompt, prompt_id)
    if row is None:
        fail('prompt_not_found', 'Prompt not found', 404)
    if row.status == 'answered':
        fail('prompt_already_answered', 'Answered prompt cannot be dismissed', 409)
    if row.status in {'open', 'expired'}:
        row.status = 'dismissed'
        session.commit()
    return envelope(session, {key: getattr(row, key) for key in
        ('id', 'kind', 'activity_id', 'session_uid', 'opens_at', 'closes_at', 'status')})
