"""Coach proposal lifecycle."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast

from pydantic import Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.services.decision_inputs import (
    KnowledgeResolver,
    canonical_json,
    digest,
)
from app.services.proposals.context import load_context, lock_planning, snapshot_ref
from app.services.proposals.schema import (
    DecisionError,
    ProposalDoc,
    Strict,
    ValidationContext,
    ValidationIssue,
    parse_document,
)
from app.services.proposals.validation import validate_parsed


@dataclass(frozen=True)
class SubmitResult:
    proposal_id: uuid.UUID
    revision: int
    status: str
    issues: list[ValidationIssue]


def submit_proposal(session: Session, raw: dict, *, now: datetime, resolve_kb: KnowledgeResolver) -> SubmitResult:
    from app.coach_v2_models import CoachProposal, CoachSnapshot

    lock_planning(session)
    input_hash = digest(raw)
    existing = session.scalar(
        select(CoachProposal).where(CoachProposal.input_hash == input_hash).execution_options(populate_existing=True)
    )
    if existing:
        return SubmitResult(
            existing.id,
            existing.revision,
            existing.status,
            [
                ValidationIssue(item["code"], item["path"], item["message"])
                for item in cast(list[dict], existing.validation_errors or [])
            ],
        )
    active = session.scalar(
        select(CoachProposal)
        .where(CoachProposal.status.in_(("pending", "stale", "invalid")))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if active is not None:
        raise DecisionError(
            "active_proposal_exists",
            f"Proposal {active.id} is still open. Review or discard it before submitting another.",
            409,
            [
                ValidationIssue("active_proposal_id", "active_proposal_id", str(active.id)),
                ValidationIssue("active_revision", "active_revision", str(active.revision)),
            ],
        )
    doc, issues = parse_document(raw)
    if doc is None:
        raise DecisionError("invalid_proposal", "Proposal schema invalid", 422, issues)
    snapshot = session.get(CoachSnapshot, doc.snapshot_id)
    if snapshot is None:
        raise DecisionError("snapshot_not_found", "Snapshot not found", 404)
    kb = resolve_kb(snapshot_ref(snapshot).kb_routes)
    ctx = load_context(session, doc.snapshot_id, now=now, kb=kb)
    result = validate_parsed(doc, ctx)
    proposal = CoachProposal(
        operation=doc.operation,
        snapshot_id=doc.snapshot_id,
        base_calendar_version=doc.base_calendar_version,
        base_block_version_id=doc.base_block_version_id,
        status=result.status,
        submitted_at=now,
        headline=doc.headline,
        why=[item.model_dump() for item in doc.why],
        uncertainty=list(doc.uncertainty),
        change_triggers=[item.model_dump() for item in doc.change_triggers],
        next_check=doc.next_check.model_dump(mode="json"),
        coach_note=doc.coach_note,
        legacy_text=None,
        confidence=doc.confidence.model_dump(),
        evidence_ids=doc.evidence_ids,
        policy_ids=doc.policy_ids,
        recipe_ids=doc.recipe_ids,
        escalation=doc.escalation,
        block_change=doc.block_change.model_dump(mode="json") if doc.block_change else None,
        anchor_changes=[item.model_dump(mode="json") for item in doc.anchor_changes],
        payload=doc.model_dump(mode="json", exclude_unset=True),
        validation_errors=[issue.to_json() for issue in result.issues],
        skill_version=doc.skill_version,
        input_hash=input_hash,
    )
    session.add(proposal)
    session.flush()
    _store_changes(session, proposal.id, doc, ctx)
    _store_revision(session, proposal, now, "Original proposal", [], [], None)
    return SubmitResult(proposal.id, proposal.revision, result.status, result.issues)


def _store_changes(session: Session, proposal_id: uuid.UUID, doc: ProposalDoc, ctx: ValidationContext) -> None:
    from app.coach_v2_models import CoachProposalChange

    for change in doc.changes:
        before = ctx.head_sessions.get(change.session_uid) if change.session_uid else None
        after = change.after.model_dump(mode="json", exclude_unset=True) if change.after else None
        if after and change.is_unplanned_strength_omission and after.get("local_date"):
            slot = ctx.confirmed_strength_slot_ids.get(date.fromisoformat(after["local_date"]))
            if slot:
                after["strength_slot_id"] = str(slot)
        session.add(
            CoachProposalChange(
                proposal_id=proposal_id,
                change_id=change.change_id,
                op=change.op,
                session_uid=change.session_uid,
                before=canonical_json(vars(before))
                if False
                else (
                    {
                        key: str(value)
                        if isinstance(value, uuid.UUID)
                        else value.isoformat()
                        if isinstance(value, date)
                        else value
                        for key, value in vars(before).items()
                    }
                    if before
                    else None
                ),
                after=after,
                reason=change.reason,
                decision="pending",
            )
        )
    session.flush()


class RevisionRequest(Strict):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
    document: dict[str, Any]


def _store_revision(
    session: Session,
    proposal: Any,
    now: datetime,
    reason: str,
    changed_ids: list[str],
    changed_fields: list[str],
    request_hash: str | None,
) -> None:
    from app.coach_v2_models import CoachProposalRevision

    session.add(
        CoachProposalRevision(
            proposal_id=proposal.id,
            revision=proposal.revision,
            saved_at=now,
            reason=reason,
            payload=proposal.payload,
            changed_change_ids=changed_ids,
            changed_fields=changed_fields,
            request_hash=request_hash,
        )
    )
    session.flush()


def revise_proposal(
    session: Session, proposal_id: uuid.UUID, req: RevisionRequest, *, now: datetime, resolve_kb: KnowledgeResolver
) -> SubmitResult:
    """Replace a draft atomically; keep its identity, prior versions and calendar untouched."""
    from app.coach_v2_models import CoachProposal, CoachProposalChange, CoachProposalRevision, CoachSnapshot

    lock_planning(session)
    proposal = session.scalar(
        select(CoachProposal)
        .where(CoachProposal.id == proposal_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if proposal is None:
        raise DecisionError("proposal_not_found", "Proposal not found", 404)
    if proposal.status in {"accepted", "partially_accepted", "rejected", "discarded"}:
        raise DecisionError(
            "proposal_decided", "This proposal has a decision. Propose changes to the current calendar instead.", 409
        )
    if not req.reason.strip():
        raise DecisionError("invalid_revision", "Explain the requested revision", 422)
    request_hash = digest(req.model_dump(mode="json"))
    if req.expected_revision != proposal.revision:
        # A retry of the immediately preceding successful edit must not create another revision.
        latest = session.get(CoachProposalRevision, (proposal_id, proposal.revision))
        if req.expected_revision + 1 == proposal.revision and latest and latest.request_hash == request_hash:
            return SubmitResult(proposal.id, proposal.revision, proposal.status, [])
        raise DecisionError(
            "proposal_revision_conflict", "This proposal was revised. Read the latest draft before editing.", 409
        )
    doc, issues = parse_document(req.document)
    if doc is None:
        raise DecisionError("invalid_proposal", "Revision schema invalid; existing draft unchanged", 422, issues)
    snapshot = session.get(CoachSnapshot, doc.snapshot_id)
    if snapshot is None:
        raise DecisionError("snapshot_not_found", "Snapshot not found", 404)
    kb = resolve_kb(snapshot_ref(snapshot).kb_routes)
    ctx = load_context(session, doc.snapshot_id, now=now, kb=kb)
    validated = validate_parsed(doc, ctx)
    if validated.status != "pending":
        raise DecisionError(
            "stale_evidence" if validated.status == "stale" else "invalid_proposal",
            "Revision failed validation; existing draft unchanged",
            409 if validated.status == "stale" else 422,
            validated.issues,
        )
    payload = doc.model_dump(mode="json", exclude_unset=True)
    if payload == proposal.payload and proposal.status == "pending":
        return SubmitResult(proposal.id, proposal.revision, proposal.status, [])
    old_changes = {item["change_id"]: item for item in proposal.payload.get("changes", [])}
    new_changes = {item["change_id"]: item for item in payload.get("changes", [])}
    changed_ids = sorted(
        key for key in old_changes.keys() | new_changes.keys() if old_changes.get(key) != new_changes.get(key)
    )
    changed_fields = sorted(
        key
        for key in proposal.payload.keys() | payload.keys()
        if key != "changes" and proposal.payload.get(key) != payload.get(key)
    )
    # Retain input_hash as the identity of the original submit, including its retries.
    for name in (
        "operation",
        "snapshot_id",
        "base_calendar_version",
        "base_block_version_id",
        "headline",
        "coach_note",
        "evidence_ids",
        "policy_ids",
        "recipe_ids",
        "escalation",
        "skill_version",
    ):
        setattr(proposal, name, getattr(doc, name))
    proposal.confidence = doc.confidence.model_dump()
    proposal.why = [item.model_dump() for item in doc.why]
    proposal.uncertainty = list(doc.uncertainty)
    proposal.change_triggers = [item.model_dump() for item in doc.change_triggers]
    proposal.next_check = doc.next_check.model_dump(mode="json")
    proposal.legacy_text = None
    proposal.block_change = doc.block_change.model_dump(mode="json") if doc.block_change else None
    proposal.anchor_changes = [item.model_dump(mode="json") for item in doc.anchor_changes]
    proposal.payload = payload
    proposal.status = "pending"
    proposal.validation_errors = []
    proposal.revision += 1
    session.execute(delete(CoachProposalChange).where(CoachProposalChange.proposal_id == proposal_id))
    _store_changes(session, proposal_id, doc, ctx)
    _store_revision(session, proposal, now, req.reason.strip(), changed_ids, changed_fields, request_hash)
    return SubmitResult(proposal.id, proposal.revision, proposal.status, [])


def discard_proposal(
    session: Session, proposal_id: uuid.UUID, expected_revision: int, *, now: datetime
) -> SubmitResult:
    """Close an open proposal without changing calendar or source state."""
    from app.coach_v2_models import CoachProposal

    lock_planning(session)
    proposal = session.scalar(
        select(CoachProposal)
        .where(CoachProposal.id == proposal_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if proposal is None:
        raise DecisionError("proposal_not_found", "Proposal not found", 404)
    if expected_revision != proposal.revision:
        raise DecisionError("proposal_revision_conflict", "Proposal revision changed. Reload before discarding.", 409)
    if proposal.status == "discarded":
        return SubmitResult(proposal.id, proposal.revision, proposal.status, [])
    if proposal.status not in {"pending", "stale", "invalid"}:
        raise DecisionError("proposal_decided", "A decided proposal cannot be discarded", 409)
    proposal.status = "discarded"
    proposal.discarded_at = now
    session.flush()
    return SubmitResult(proposal.id, proposal.revision, proposal.status, [])


def mark_pending_stale(session: Session, *, except_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    from app.coach_v2_models import CoachProposal

    query = select(CoachProposal).where(CoachProposal.status == "pending")
    if except_id:
        query = query.where(CoachProposal.id != except_id)
    rows = list(session.scalars(query))
    for row in rows:
        row.status = "stale"
    return [row.id for row in rows]
