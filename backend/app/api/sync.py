from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_revision, get_session
from app.models import SyncJob, SyncState
from app.services.sync import enqueue_sync

router = APIRouter(prefix="/sync", tags=["sync"])


def _envelope(session: Session, data: object) -> dict:
    return {"schema_version": "v1", "data_revision": get_revision(session),
            "mode": settings.app_mode, "data": data}


class SyncRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def range_valid(self):
        if self.start_date and self.end_date and (self.start_date > self.end_date or
                                                   (self.end_date - self.start_date).days > 366):
            raise ValueError("invalid_sync_range")
        return self


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict:
    states = session.scalars(select(SyncState).order_by(SyncState.dataset)).all()
    jobs = session.scalars(select(SyncJob).where(SyncJob.status.in_(("queued", "running", "retry_wait")))
        .order_by(SyncJob.created_at)).all()
    return _envelope(session, {"datasets": [{
        "dataset": s.dataset, "status": s.status, "reason": s.reason,
        "last_attempt_at": s.last_attempt_at, "last_success_at": s.last_success_at,
        "newest_observation_at": s.newest_observation_at,
        "requested_start": s.requested_start, "requested_end": s.requested_end,
        "fully_enumerated": s.fully_enumerated,
    } for s in states], "active_jobs": [_job(j) for j in jobs]})


def _job(job: SyncJob) -> dict:
    return {"id": str(job.id), "dataset": job.dataset, "status": job.status,
            "start_date": job.start_date, "end_date": job.end_date,
            "checkpoint": job.checkpoint, "counters": job.counters,
            "next_attempt_at": job.next_attempt_at, "error_code": job.error_code}


@router.post("", status_code=202)
def request_sync(body: SyncRequest, session: Session = Depends(get_session)) -> dict:
    if settings.app_mode != "real":
        raise HTTPException(409, detail="real_mode_required")
    end = body.end_date or date.today()
    start = body.start_date or end - timedelta(days=13)
    jobs = [enqueue_sync(session, start, end, "activities")]
    recovery_start = start if body.start_date else end - timedelta(days=6)
    jobs += [enqueue_sync(session, recovery_start, end, dataset)
             for dataset in ("sleep", "hrv", "resting_hr")]
    session.commit()
    return _envelope(session, {"jobs": [_job(job) for job in jobs]})


@router.get("/jobs/{job_id}")
def job_detail(job_id: UUID, session: Session = Depends(get_session)) -> dict:
    job = session.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(404, detail="job_not_found")
    return _envelope(session, _job(job))
