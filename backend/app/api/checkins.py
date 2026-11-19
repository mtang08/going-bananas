"""Permanent v2 check-in, RPE and prompt routes."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.api.core import envelope
from app.checkin_models import Checkin
from app.db import get_session
from app.domain.local_time import date_in_zone
from app.errors import fail
from app.metric_models import Prompt
from app.services.calendar import lock_calendar
from app.services.checkins import (
    CheckinCreate,
    CheckinPatch,
    checkin_data,
    create_checkin,
    patch_checkin,
    save_manual_rpe,
)
from app.services.exceptions.detector import detection_payload, run_detection
from app.services.timezone import athlete_tz

router = APIRouter()


class RpeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rpe: float

    @field_validator("rpe", mode="before")
    @classmethod
    def valid_rpe(cls, value: object) -> float:
        from app.services.checkins import measurement

        return measurement(value)


@router.post("/v2/checkins")
def post_checkin(body: CheckinCreate, session: Session = Depends(get_session)) -> JSONResponse:
    result, created = create_checkin(session, body.model_dump())
    session.commit()
    detection = run_detection(session, datetime.now(UTC))
    session.commit()
    return JSONResponse(
        status_code=201 if created else 200,
        content=jsonable_encoder(envelope(session, {**result, "exceptions": detection_payload(detection)})),
    )


@router.patch("/v2/checkins/{checkin_id}")
def patch_checkin_route(checkin_id: uuid.UUID, body: CheckinPatch, session: Session = Depends(get_session)) -> dict:
    result = patch_checkin(session, checkin_id, body.model_dump(exclude_unset=True))
    session.commit()
    detection = run_detection(session, datetime.now(UTC))
    session.commit()
    return envelope(session, {**result, "exceptions": detection_payload(detection)})


@router.get("/v2/checkins")
def get_checkins(start: date | None = None, end: date | None = None, session: Session = Depends(get_session)) -> dict:
    zone = athlete_tz(session)
    rows = session.scalars(select(Checkin).order_by(desc(Checkin.observed_at), desc(Checkin.id))).all()
    return envelope(
        session,
        {
            "items": [
                checkin_data(session, row)
                for row in rows
                if (start is None or date_in_zone(row.observed_at, zone) >= start)
                and (end is None or date_in_zone(row.observed_at, zone) <= end)
            ]
        },
    )


@router.put("/activities/{activity_id}/rpe")
def put_activity_rpe(activity_id: uuid.UUID, body: RpeInput, session: Session = Depends(get_session)) -> dict:
    result = save_manual_rpe(session, activity_id=activity_id, rpe=body.rpe, now=datetime.now(UTC))
    session.commit()
    run_detection(session, datetime.now(UTC))
    session.commit()
    return envelope(session, result)


@router.put("/strength/history/{workout_id}/rpe")
def put_strong_rpe(workout_id: uuid.UUID, body: RpeInput, session: Session = Depends(get_session)) -> dict:
    result = save_manual_rpe(session, strong_workout_id=workout_id, rpe=body.rpe, now=datetime.now(UTC))
    session.commit()
    return envelope(session, result)


@router.get("/prompts")
def get_prompts(session: Session = Depends(get_session)) -> dict:
    now = datetime.now(UTC)
    rows = session.scalars(
        select(Prompt)
        .where(Prompt.status == "open", Prompt.opens_at <= now, or_(Prompt.closes_at.is_(None), Prompt.closes_at > now))
        .order_by(desc(Prompt.opens_at), desc(Prompt.id))
    ).all()
    return envelope(
        session,
        {
            "items": [
                {
                    key: getattr(row, key)
                    for key in ("id", "kind", "activity_id", "session_uid", "opens_at", "closes_at", "status")
                }
                for row in rows
            ]
        },
    )


@router.post("/prompts/{prompt_id}/dismiss")
def dismiss_prompt(prompt_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    lock_calendar(session)
    row = session.get(Prompt, prompt_id)
    if row is None:
        fail("prompt_not_found", "Prompt not found", 404)
    if row.status == "answered":
        fail("prompt_already_answered", "Answered prompt cannot be dismissed", 409)
    if row.status in {"open", "expired"}:
        row.status = "dismissed"
        session.commit()
    return envelope(
        session,
        {
            key: getattr(row, key)
            for key in ("id", "kind", "activity_id", "session_uid", "opens_at", "closes_at", "status")
        },
    )
