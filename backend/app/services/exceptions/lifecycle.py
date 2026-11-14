"""Single writer of exception finding and patch status changes."""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import object_session

from app.exception_models import ExceptionFinding, ExceptionPatch
from app.services.exceptions.vocab import NON_TERMINAL_FINDING, TERMINAL_FINDING, FindingStatus


def close_finding(finding: ExceptionFinding, status: FindingStatus, *, now: datetime, note: str | None = None,
                  proposal_id: uuid.UUID | None = None) -> None:
    if status not in TERMINAL_FINDING:
        raise ValueError(f"not a terminal finding status: {status}")
    finding.status = status
    finding.closed_at = now
    finding.close_note = note
    if proposal_id is not None:
        finding.reviewed_by_proposal_id = proposal_id
    finding.version += 1


def address_findings(findings: Iterable[ExceptionFinding], patch: ExceptionPatch) -> None:
    for finding in findings:
        finding.status = "addressed"
        finding.patch_id = patch.id
        finding.version += 1


def resolve_patch(patch: ExceptionPatch, status: Literal["resolved", "escalated"], *,
                  by: Literal["coach", "athlete"], now: datetime, note: str | None = None) -> None:
    patch.status = status
    patch.resolved_at = now
    patch.resolved_by = by
    patch.resolution_note = note
    patch.version += 1
    if status != "resolved":
        return
    session = object_session(patch)
    if session is None:
        raise ValueError("patch_not_attached")
    linked = session.scalars(select(ExceptionFinding).where(
        ExceptionFinding.patch_id == patch.id, ExceptionFinding.status.in_(NON_TERMINAL_FINDING)).with_for_update())
    for finding in linked:
        close_finding(finding, "resolved", now=now)


def supersede_patch(patch: ExceptionPatch, *, now: datetime) -> None:
    patch.status = "superseded"
    patch.resolved_at = now
    patch.resolved_by = "coach"
    patch.resolution_note = None
    patch.version += 1
