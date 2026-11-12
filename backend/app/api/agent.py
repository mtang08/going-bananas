"""Local handoff between the Codex coaching skill and the training calendar."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.agent_models import CoachPlanRevision
from app.api.core import envelope, tz
from app.db import get_session
from app.services.agent_plans import Proposal, agent_context, format_revision, latest, revertible, rollback, submit

router = APIRouter(prefix='/coach/agent', tags=['agent coaching'])


@router.get('/schema')
def schema(session: Session = Depends(get_session)) -> dict:
    return envelope(session, {'proposal': Proposal.model_json_schema(), 'engine': 'codex_skill.v1',
        'activation': 'Validated proposals activate automatically; no model runs in the server.'})


@router.get('/context')
def context(workflow: Literal['daily', 'weekly'] = 'daily', as_of: date | None = None,
            session: Session = Depends(get_session)) -> dict:
    day = as_of or datetime.now(ZoneInfo(tz(session))).date()
    return envelope(session, agent_context(session, workflow, day))


@router.get('/revisions')
def revisions(session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(select(CoachPlanRevision).order_by(desc(CoachPlanRevision.created_at), desc(CoachPlanRevision.id)).limit(100)).all()
    current = latest(session)
    undo = revertible(session, current)
    return envelope(session, {'items': [format_revision(row) for row in rows],
                              'current_revision_id': current.id if current else None,
                              'revertible_revision_id': undo.id if undo else None})


@router.post('/proposals')
def proposals(body: Proposal, session: Session = Depends(get_session)) -> dict:
    return envelope(session, submit(session, body))


class RollbackRequest(BaseModel):
    expected_revision_id: uuid.UUID
    reason: str = Field(min_length=5, max_length=2000)


@router.post('/revisions/{revision_id}/rollback')
def rollback_revision(revision_id: uuid.UUID, body: RollbackRequest, session: Session = Depends(get_session)) -> dict:
    return envelope(session, rollback(session, revision_id, body.expected_revision_id, body.reason))
