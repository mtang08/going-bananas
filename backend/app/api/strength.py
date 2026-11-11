"""Bounded, descriptive Strong workout history."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_revision, get_session
from app.services.strength_history import strong_history, strong_workout_detail, strong_yearly_summary

router = APIRouter()


@router.get("/strength/history")
def history(start_date: date | None = None, end_date: date | None = None,
            offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
            session: Session = Depends(get_session)) -> dict:
    end = end_date or date.today()
    start = start_date or end - timedelta(days=27)
    if start > end or (end - start).days > 365:
        raise HTTPException(status_code=422, detail={"code": "invalid_date_window", "message": "Select at most 366 dates."})
    data = strong_history(session, start, end)
    sessions = data["sessions"]
    data["total_sessions_in_window"] = len(sessions)
    data["sessions"] = sessions[offset:offset + limit]
    data["next_offset"] = offset + limit if offset + limit < len(sessions) else None
    return {"schema_version": "v1", "data_revision": get_revision(session), "mode": settings.app_mode, "data": data}


@router.get("/strength/years")
def years(session: Session = Depends(get_session)) -> dict:
    return {"schema_version": "v1", "data_revision": get_revision(session), "mode": settings.app_mode,
            "data": strong_yearly_summary(session)}


@router.get("/strength/history/{workout_id}")
def workout_detail(workout_id: UUID, session: Session = Depends(get_session)) -> dict:
    data = strong_workout_detail(session, workout_id)
    if data is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Workout not found."})
    return {"schema_version": "v1", "data_revision": get_revision(session), "mode": settings.app_mode, "data": data}
