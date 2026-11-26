"""Typed HTTP response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict
from uuid import UUID

from sqlalchemy.orm import Session

from app.coach_v2_models import CoachProposal, ProposalStatus
from app.config import AppMode, settings
from app.db import get_revision


class Envelope[T](TypedDict):
    schema_version: Literal["v1"]
    data_revision: int
    mode: AppMode
    data: T


class ValidationField(TypedDict):
    field: str
    message: str


class ValidationErrorDetail(TypedDict):
    code: Literal["validation_error"]
    message: str
    retryable: Literal[False]
    request_id: str
    fields: list[ValidationField]


class ValidationErrorResponse(TypedDict):
    error: ValidationErrorDetail


def response_envelope[T](session: Session, data: T) -> Envelope[T]:
    return {
        "schema_version": "v1",
        "data_revision": get_revision(session),
        "mode": AppMode(settings.app_mode),
        "data": data,
    }


class ProposalSummary(TypedDict):
    id: UUID
    revision: int
    operation: str
    status: ProposalStatus
    submitted_at: datetime
    decided_at: datetime | None
    discarded_at: datetime | None
    headline: str
    base_calendar_version: int
    change_count: int


class ProposalList(TypedDict):
    items: list[ProposalSummary]


def proposal_summary(proposal: CoachProposal) -> ProposalSummary:
    return {
        "id": proposal.id,
        "revision": proposal.revision,
        "operation": proposal.operation,
        "status": proposal.status,
        "submitted_at": proposal.submitted_at,
        "decided_at": proposal.decided_at,
        "discarded_at": proposal.discarded_at,
        "headline": proposal.headline,
        "base_calendar_version": proposal.base_calendar_version,
        "change_count": len(proposal.payload.get("changes", [])),
    }
