from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.core import envelope
from app.db import get_session
from app.metrics.anchors import anchor_data, create_anchor
from app.planning_models import IntensityAnchor

router = APIRouter()


class AnchorInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: str
    value_low: float
    value_high: float | None = None
    unit: str
    protocol: str
    confidence: str
    calibrated_at: datetime
    valid_from: date
    review_after: date | None = None
    source_activity_id: UUID | None = None
    source_event_id: UUID | None = None
    proposal_id: UUID | None = None
    conditions: str | None = None
    notes: str | None = None
    supersedes_key: str | None = None


@router.get('/anchors')
def get_anchors(session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(select(IntensityAnchor).order_by(
        IntensityAnchor.kind, IntensityAnchor.valid_from,
        IntensityAnchor.calibrated_at, IntensityAnchor.anchor_key)).all()
    return envelope(session, {'items': [anchor_data(row) for row in rows]})


@router.post('/anchors')
def post_anchor(body: AnchorInput, session: Session = Depends(get_session)) -> dict:
    data = create_anchor(session, body.model_dump(exclude_none=True))
    session.commit()
    return envelope(session, data)
