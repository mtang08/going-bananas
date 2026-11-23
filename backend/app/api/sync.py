from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.core import envelope
from app.config import settings
from app.db import get_session
from app.errors import fail
from app.models import SyncJob, SyncState
from app.services.sync import enqueue_requested_sync
from app.services.treadmill_review import confirm_treadmill, pending_treadmill_runs, treadmill_preview

router = APIRouter(prefix="/sync", tags=["sync"])


class SyncRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def range_valid(self):
        if (
            self.start_date
            and self.end_date
            and (self.start_date > self.end_date or (self.end_date - self.start_date).days > 366)
        ):
            raise ValueError("invalid_sync_range")
        return self


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict:
    states = session.scalars(select(SyncState).order_by(SyncState.dataset)).all()
    jobs = session.scalars(
        select(SyncJob).where(SyncJob.status.in_(("queued", "running", "retry_wait"))).order_by(SyncJob.created_at)
    ).all()
    return envelope(
        session,
        {
            "datasets": [
                {
                    "dataset": s.dataset,
                    "status": s.status,
                    "reason": s.reason,
                    "last_attempt_at": s.last_attempt_at,
                    "last_success_at": s.last_success_at,
                    "newest_observation_at": s.newest_observation_at,
                    "requested_start": s.requested_start,
                    "requested_end": s.requested_end,
                    "fully_enumerated": s.fully_enumerated,
                }
                for s in states
            ],
            "active_jobs": [_job(j) for j in jobs],
            "pending_treadmill_runs": pending_treadmill_runs(session),
        },
    )


def _job(job: SyncJob) -> dict:
    return {
        "id": str(job.id),
        "dataset": job.dataset,
        "status": job.status,
        "start_date": job.start_date,
        "end_date": job.end_date,
        "checkpoint": {
            key: value
            for key, value in job.checkpoint.items()
            if key not in {"pending_treadmill", "pending_coverage_id"}
        },
        "counters": job.counters,
        "next_attempt_at": job.next_attempt_at,
        "error_code": job.error_code,
    }


@router.post("", status_code=202)
def request_sync(body: SyncRequest, session: Session = Depends(get_session)) -> dict:
    if settings.app_mode != "real":
        fail("real_mode_required", "Real mode required", 409)
    try:
        jobs = enqueue_requested_sync(session, body.start_date, body.end_date)
    except ValueError as exc:
        if str(exc) != "invalid_sync_range":
            raise
        fail("invalid_sync_range", "Sync dates must be in order and at most 366 days apart.", 422)
    session.commit()
    return envelope(session, {"jobs": [_job(job) for job in jobs]})


@router.get("/jobs/{job_id}")
def job_detail(job_id: UUID, session: Session = Depends(get_session)) -> dict:
    job = session.get(SyncJob, job_id)
    if job is None:
        fail("job_not_found", "Sync job not found", 404)
    return envelope(session, _job(job))


class TreadmillPace(BaseModel):
    lap_index: int = Field(ge=0)
    pace_seconds_per_mile: float = Field(ge=1, allow_inf_nan=False)


class TreadmillConfirmation(BaseModel):
    preview_token: str = Field(min_length=1, max_length=64)
    paces: list[TreadmillPace]

    @model_validator(mode="after")
    def unique_laps(self):
        if len({pace.lap_index for pace in self.paces}) != len(self.paces):
            raise ValueError("duplicate_treadmill_lap")
        return self


@router.get("/treadmill-review/{remote_id}")
def review_treadmill(remote_id: str, session: Session = Depends(get_session)) -> dict:
    if settings.app_mode != "real":
        fail("real_mode_required", "Real mode required", 409)
    return envelope(session, treadmill_preview(session, settings.private_dir, remote_id))


@router.post("/treadmill-review/{remote_id}")
def save_treadmill(remote_id: str, body: TreadmillConfirmation, session: Session = Depends(get_session)) -> dict:
    if settings.app_mode != "real":
        fail("real_mode_required", "Real mode required", 409)
    paces = {pace.lap_index: pace.pace_seconds_per_mile for pace in body.paces}
    activity_id = confirm_treadmill(session, settings.private_dir, remote_id, body.preview_token, paces)
    return envelope(session, {"activity_id": str(activity_id)})
