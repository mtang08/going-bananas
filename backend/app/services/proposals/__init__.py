"""Validation and atomic acceptance of reviewed coaching proposals."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.local_time import date_in_zone
from app.services.decision_inputs import (
    KnowledgeResolver,
    digest,
)
from app.services.exceptions.vocab import NON_TERMINAL_FINDING
from app.services.knowledge import KnowledgeIntegrityError
from app.services.proposals.context import load_context, lock_planning, snapshot_ref
from app.services.proposals.lifecycle import mark_pending_stale

# isort: split

# TRANSITIONAL (ARCH-08e2): tests move to proposals.lifecycle, then this import is deleted
from app.services.proposals.lifecycle import (  # noqa: F401
    RevisionRequest,
    discard_proposal,
    revise_proposal,
    submit_proposal,
)
from app.services.proposals.schema import (
    DecisionError,
    ProposalDoc,
    Strict,
    ValidationContext,
    anchor_key,
)
from app.services.proposals.validation import FreshnessReason, proposal_freshness, validate_subset


class DecisionRequest(Strict):
    idempotency_key: str = Field(min_length=8, max_length=100)
    expected_head: int = Field(ge=0)
    expected_revision: int = Field(ge=1)
    accept_change_ids: list[str]
    reject_change_ids: list[str]
    accept_block_change: bool = False
    accept_anchor_changes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class DecisionResult:
    proposal_id: uuid.UUID
    status: str
    calendar_version: int | None
    block_version_id: uuid.UUID | None
    anchor_keys: list[str]
    stale_proposals: list[uuid.UUID]


def _selection(proposal_id: uuid.UUID, req: DecisionRequest) -> dict:
    accepted, rejected, anchors = req.accept_change_ids, req.reject_change_ids, req.accept_anchor_changes
    if len(set(accepted)) != len(accepted) or len(set(rejected)) != len(rejected) or len(set(anchors)) != len(anchors):
        raise DecisionError("invalid_decision", "Duplicate selected IDs", 422)
    return {
        "proposal_id": str(proposal_id),
        "revision": req.expected_revision,
        "accept_change_ids": sorted(accepted),
        "reject_change_ids": sorted(rejected),
        "accept_block_change": req.accept_block_change,
        "accept_anchor_changes": sorted(anchors),
    }


def _store_alias(session: Session, key: str, proposal_id: uuid.UUID, decision_hash: str, result: dict) -> None:
    from app.coach_v2_models import CoachDecisionKey

    session.add(
        CoachDecisionKey(idempotency_key=key, proposal_id=proposal_id, decision_hash=decision_hash, result=result)
    )
    session.flush()


def _save_block(
    session: Session, doc: ProposalDoc, proposal_id: uuid.UUID, ctx: ValidationContext, now: datetime
) -> tuple[uuid.UUID, bool]:
    from app.planning_models import Block, BlockDecision, BlockVersion

    change = doc.block_change
    assert change is not None
    old = ctx.active_block
    block_uid = change.block_uid if old else uuid.uuid4()
    if not old:
        session.add(Block(block_uid=block_uid))
        session.flush()
    fields = change.version_fields.model_dump(mode="python")
    fields["constraints"] = [item.model_dump() for item in change.version_fields.constraints]
    fields["benchmark"] = change.version_fields.benchmark.model_dump(mode="json") if change.version_fields.benchmark else None
    if old:
        previous = session.get(BlockVersion, old.version_id)
        assert previous is not None
        if all(getattr(previous, key) == value for key, value in fields.items()):
            return previous.id, False
    version = BlockVersion(
        block_uid=block_uid, version=(old.version + 1 if old else 1), proposal_id=proposal_id, **fields
    )
    session.add(version)
    session.flush()
    session.add(
        BlockDecision(
            block_uid=block_uid,
            decision=change.decision,
            from_version=old.version if old else None,
            to_version=version.version,
            rationale=doc.rationale,
            evidence_ids=doc.evidence_ids,
            policy_ids=doc.policy_ids,
            confidence=doc.confidence.decision,
            proposal_id=proposal_id,
            decided_at=now,
        )
    )
    return version.id, True


def _apply_exception_effects(session: Session, doc: ProposalDoc, proposal_id: uuid.UUID, snapshot_at: datetime,
                             status: str, calendar_version: int | None, now: datetime) -> None:
    from app.exception_models import ExceptionFinding, ExceptionPatch
    from app.services.exceptions.lifecycle import address_findings, close_finding, resolve_patch, supersede_patch

    if status not in {"accepted", "partially_accepted"}:
        return

    def findings(*conditions: Any) -> list[Any]:
        return list(session.scalars(select(ExceptionFinding).where(*conditions).with_for_update()))

    def review(rows: list[Any]) -> None:
        for row in rows:
            close_finding(row, "reviewed", now=now, proposal_id=proposal_id)

    active = ExceptionFinding.status.in_(NON_TERMINAL_FINDING)
    exc = doc.exception
    if doc.operation == "exception_review" and exc is not None:
        listed = findings(ExceptionFinding.id.in_(exc.finding_ids), active) if exc.finding_ids else []
        if calendar_version is not None:
            patch = ExceptionPatch(
                proposal_id=proposal_id, calendar_version_number=calendar_version, category=exc.category,
                severity=exc.severity, ladder_level=exc.ladder_level, status="open",
                window_start=exc.patch_window.start, window_end=exc.patch_window.end, reassess_on=exc.reassess_on,
                monitor=list(exc.monitor), return_criteria=list(exc.return_criteria),
                escalate_criteria=list(exc.escalate_criteria),
                unchanged=[{"session_uid": str(item.session_uid), "reason": item.reason} for item in exc.unchanged],
            )
            session.add(patch)
            session.flush()
            address_findings(listed, patch)
        else:
            review(listed)
    handled: set[uuid.UUID] = set()
    for item in doc.patch_resolutions:
        existing = session.get(ExceptionPatch, item.patch_id, with_for_update=True)
        if existing is None or existing.status not in {"open", "escalated"}:
            continue
        resolve_patch(existing, item.status, by="coach", now=now, note=item.note)
        handled.add(existing.id)
    if doc.operation == "review_rolling_plan":
        review(findings(ExceptionFinding.status == "open", ExceptionFinding.severity != "escalate",
                        ExceptionFinding.evidence_at <= snapshot_at))
    elif doc.operation == "review_training_block":
        review(findings(active))
        query = select(ExceptionPatch).where(ExceptionPatch.status.in_(("open", "escalated")))
        if handled:
            query = query.where(ExceptionPatch.id.not_in(handled))
        for live in session.scalars(query.with_for_update()):
            supersede_patch(live, now=now)
    elif doc.operation == "post_event_review" and doc.event_review is not None:
        review(findings(ExceptionFinding.rule_code == "POST_EVENT_REVIEW_DUE",
                        ExceptionFinding.entity_key == f"event:{doc.event_review.event_id}", active))
    session.flush()


def _apply_benchmark_effects(session: Session, doc: ProposalDoc, proposal_id: uuid.UUID, status: str,
                             ctx: ValidationContext) -> None:
    from app.planning_models import BlockBenchmarkResult, BlockVersion

    reviewed, bench, review = ctx.active_block, ctx.benchmark, doc.event_review
    if (status not in {"accepted", "partially_accepted"} or doc.operation != "review_training_block" or review is None
            or reviewed is None or bench is None or bench.status != "completed"):
        return
    row = session.scalar(select(BlockBenchmarkResult).where(
        BlockBenchmarkResult.block_uid == reviewed.block_uid,
        BlockBenchmarkResult.block_version == reviewed.version).with_for_update())
    if row is None:
        row = BlockBenchmarkResult(block_uid=reviewed.block_uid, block_version=reviewed.version,
                                   match_method=bench.match_method or "auto")
        session.add(row)
    version_row = session.get(BlockVersion, reviewed.version_id)
    assert version_row is not None
    row.protocol = (version_row.benchmark or {}).get("protocol", "")
    row.activity_id, row.event_id, row.distance_m = bench.activity_id, bench.event_id, bench.distance_m
    row.local_date, row.result_s = bench.local_date, bench.result_s
    row.outcome, row.compared_with, row.proposal_id = review.outcome, review.compared_with, proposal_id
    session.flush()


_DECISION_STALE: dict[FreshnessReason, tuple[str, str]] = {
    "snapshot_expired": ("proposal_stale", "Proposal expired"),
    "stale_base_calendar": ("proposal_stale", "Proposal base changed"),
    "stale_base_block": ("proposal_stale", "Proposal base changed"),
    "stale_sources": ("stale_evidence", "Decision evidence changed"),
}


def decide_proposal(
    session: Session, proposal_id: uuid.UUID, req: DecisionRequest, *, now: datetime, resolve_kb: KnowledgeResolver
) -> DecisionResult:
    from app.coach_v2_models import CoachDecisionKey, CoachProposal, CoachProposalChange, CoachSnapshot
    from app.metrics.anchors import create_anchor
    from app.services.calendar import apply_edits

    state = lock_planning(session)
    proposal = session.scalar(select(CoachProposal).where(CoachProposal.id == proposal_id).with_for_update().execution_options(populate_existing=True))
    if proposal is None:
        raise DecisionError("proposal_not_found", "Proposal not found", 404)
    if proposal.status == "discarded":
        raise DecisionError("proposal_discarded", "Discarded proposals cannot be decided", 409)
    if req.expected_revision != proposal.revision:
        raise DecisionError("proposal_revision_conflict", "This proposal was revised. Reload and review the latest revision.", 409)
    selection = _selection(proposal_id, req)
    decision_hash = digest(selection)
    key = session.get(CoachDecisionKey, req.idempotency_key)
    if key and key.proposal_id != proposal_id:
        raise DecisionError("idempotency_conflict", "Key belongs to another proposal", 409)
    if key and key.decision_hash != decision_hash:
        raise DecisionError("decision_conflict", "Decision selection changed", 409)
    if proposal.status in {"accepted", "partially_accepted", "rejected"}:
        if proposal.decision_hash != decision_hash or not proposal.decision_result:
            raise DecisionError("decision_conflict", "Decision selection changed", 409)
        if key is None:
            _store_alias(session, req.idempotency_key, proposal_id, decision_hash, proposal.decision_result)
        stored = proposal.decision_result
        return DecisionResult(
            proposal_id,
            stored["status"],
            stored["calendar_version"],
            uuid.UUID(stored["block_version_id"]) if stored["block_version_id"] else None,
            list(stored["anchor_keys"]),
            [uuid.UUID(value) for value in stored["stale_proposals"]],
        )
    if proposal.status != "pending":
        raise DecisionError("proposal_stale", "Proposal is no longer pending", 409)
    if req.expected_head != state.calendar_head_version:
        raise DecisionError("calendar_head_moved", "Calendar changed", 409)
    doc = ProposalDoc.model_validate(proposal.payload)
    snapshot = session.get(CoachSnapshot, proposal.snapshot_id)
    if snapshot is None:
        proposal.status = "stale"
        raise DecisionError("proposal_stale", "Proposal expired", 409, commit=True)
    ref = snapshot_ref(snapshot)
    try:
        kb = resolve_kb(ref.kb_routes)
    except KnowledgeIntegrityError as exc:
        raise DecisionError("knowledge_unavailable", "Verified knowledge is unavailable", 503) from exc
    ctx = load_context(session, proposal.snapshot_id, now=now, kb=kb)
    reasons = proposal_freshness(
        ref, ctx, base_calendar_version=proposal.base_calendar_version, base_block_version_id=proposal.base_block_version_id
    )
    if reasons:
        proposal.status = "stale"
        code, message = _DECISION_STALE[reasons[0]]
        raise DecisionError(code, message, 409, commit=True)
    accepted, rejected, anchors = set(req.accept_change_ids), set(req.reject_change_ids), set(req.accept_anchor_changes)
    required = {change.change_id for change in doc.changes}
    known_anchors = {anchor_key(item, ctx.tz) for item in doc.anchor_changes}
    if (
        accepted & rejected
        or accepted | rejected != required
        or not anchors <= known_anchors
        or (req.accept_block_change and doc.block_change is None)
    ):
        raise DecisionError("decision_incomplete", "Selection must partition all changes", 422)
    issues = validate_subset(doc, accepted, req.accept_block_change, anchors, ctx)
    if issues:
        raise DecisionError("proposal_invalid_subset", "Accepted subset is invalid", 422, issues)
    block_id = ctx.active_block.version_id if ctx.active_block else None
    changed = False
    if req.accept_block_change:
        block_id, block_changed = _save_block(session, doc, proposal_id, ctx, now)
        if block_changed:
            changed = True
    anchor_keys: list[str] = []
    for item in doc.anchor_changes:
        if anchor_key(item, ctx.tz) in anchors:
            fields = item.model_dump(mode="python")
            fields.update(
                proposal_id=proposal_id,
                valid_from=ctx.today,
                review_after=date_in_zone(item.calibrated_at, ctx.tz) + timedelta(days=84),
            )
            anchor_keys.append(create_anchor(session, fields)["anchor_key"])
            changed = True
    edits = []
    for change in doc.changes:
        if change.change_id not in accepted:
            continue
        edit_fields: dict[str, Any] | None = (
            change.after.model_dump(mode="python", exclude_unset=True) if change.after else None
        )
        head = ctx.head_sessions.get(change.session_uid) if change.session_uid else None
        if (
            change.op in {"modify", "move"}
            and head
            and edit_fields
            and all(getattr(head, key) == value for key, value in edit_fields.items())
        ):
            continue
        edits.append({"op": change.op, "session_uid": change.session_uid, "fields": edit_fields})
    calendar_version = None
    stale: list[uuid.UUID] = []
    if edits:
        result = apply_edits(
            session,
            state.calendar_head_version,
            edits,
            doc.summary,
            kind="proposal_accept",
            actor="coach",
            proposal_id=proposal_id,
            block_version_id=block_id,
        )
        calendar_version = result["version"]
        stale = result["stale_proposals"]
        changed = True
        from app.calendar_models import CalendarSessionRevision

        created = list(
            session.scalars(
                select(CalendarSessionRevision)
                .where(
                    CalendarSessionRevision.calendar_version_number == calendar_version,
                    CalendarSessionRevision.revision == 1,
                )
                .order_by(CalendarSessionRevision.session_uid)
            )
        )
        for change in doc.changes:
            if change.change_id not in accepted or change.op != "add" or change.after is None:
                continue
            supplied = change.after.model_dump(mode="python", exclude_unset=True)
            match = next(
                (row for row in created if all(getattr(row, key) == value for key, value in supplied.items())), None
            )
            if match is None:
                raise RuntimeError("accepted_add_not_found")
            created.remove(match)
            proposal_change = session.scalar(
                select(CoachProposalChange).where(
                    CoachProposalChange.proposal_id == proposal_id,
                    CoachProposalChange.change_id == change.change_id,
                )
            )
            assert proposal_change is not None
            proposal_change.session_uid = match.session_uid
    for row in session.scalars(select(CoachProposalChange).where(CoachProposalChange.proposal_id == proposal_id)):
        row.decision = "accepted" if row.change_id in accepted else "rejected"
    accepted_count = len(accepted) + int(req.accept_block_change) + len(anchors)
    total_count = len(required) + int(doc.block_change is not None) + len(known_anchors)
    status = (
        "accepted"
        if total_count == 0 or accepted_count == total_count
        else "rejected"
        if accepted_count == 0
        else "partially_accepted"
    )
    proposal.status = status
    proposal.decided_at = now
    proposal.decision_idempotency_key = req.idempotency_key
    proposal.decision_hash = decision_hash
    _apply_exception_effects(session, doc, proposal_id, snapshot.generated_at, status, calendar_version, now)
    _apply_benchmark_effects(session, doc, proposal_id, status, ctx)
    if changed:
        stale = list(dict.fromkeys([*stale, *mark_pending_stale(session, except_id=proposal_id)]))
    decision_result = DecisionResult(
        proposal_id, status, calendar_version, block_id if req.accept_block_change else None, anchor_keys, stale
    )
    stored = {
        "status": status,
        "calendar_version": calendar_version,
        "block_version_id": str(decision_result.block_version_id) if decision_result.block_version_id else None,
        "anchor_keys": anchor_keys,
        "stale_proposals": [str(uid) for uid in stale],
    }
    proposal.decision_result = stored
    _store_alias(session, req.idempotency_key, proposal_id, decision_hash, stored)
    return decision_result
