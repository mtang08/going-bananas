"""Exception findings and tracked patches."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.core import envelope
from app.db import bump_data_revision, get_session, global_write_lock
from app.errors import fail
from app.exception_models import ExceptionFinding, ExceptionPatch
from app.services.exceptions.detector import exceptions_view, finding_data, last_review_at, patch_data, run_detection
from app.services.exceptions.lifecycle import close_finding, resolve_patch
from app.services.timezone import athlete_today

router = APIRouter()


class DismissInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=500)


class ResolveInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)
    status: Literal['resolved', 'escalated']
    note: str | None = Field(default=None, max_length=500)


@router.get('/exceptions')
def get_exceptions(include: Literal['active', 'recent'] = 'active', session: Session = Depends(get_session)) -> dict:
    now = datetime.now(UTC)
    run_detection(session, now)
    data = exceptions_view(session, now, include)
    session.commit()
    return envelope(session, data)


@router.post('/exceptions/{finding_id}/dismiss')
def dismiss_finding_route(finding_id: uuid.UUID, body: DismissInput, session: Session = Depends(get_session)) -> dict:
    global_write_lock(session)
    row = session.get(ExceptionFinding, finding_id, with_for_update=True)
    if row is None:
        fail('finding_not_found', 'Finding not found', 404)
    if row.version != body.expected_version:
        fail('version_conflict', 'Finding changed; reload before editing', 409)
    if row.status != 'open':
        fail('finding_closed', 'Finding is no longer open', 409)
    close_finding(row, 'dismissed', now=datetime.now(UTC), note=body.note)
    bump_data_revision(session)
    session.flush()
    data = finding_data(row, last_review_at(session))
    session.commit()
    return envelope(session, data)


@router.post('/exception-patches/{patch_id}/resolve')
def resolve_patch_route(patch_id: uuid.UUID, body: ResolveInput, session: Session = Depends(get_session)) -> dict:
    global_write_lock(session)
    row = session.get(ExceptionPatch, patch_id, with_for_update=True)
    if row is None:
        fail('patch_not_found', 'Patch not found', 404)
    if row.version != body.expected_version:
        fail('version_conflict', 'Patch changed; reload before editing', 409)
    if not (row.status == 'open' or (row.status == 'escalated' and body.status == 'resolved')):
        fail('patch_closed', 'Patch is no longer open', 409)
    resolve_patch(row, body.status, by='athlete', now=datetime.now(UTC), note=body.note)
    bump_data_revision(session)
    session.flush()
    data = patch_data(session, row, athlete_today(session))
    session.commit()
    return envelope(session, data)
