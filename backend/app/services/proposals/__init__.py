"""Validation and atomic acceptance of reviewed coaching proposals."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, cast

from pydantic import Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import global_write_lock
from app.domain.local_time import date_in_zone
from app.read.calendar import head_version
from app.services.block_benchmark import active_block_version
from app.services.decision_inputs import (
    KnowledgeResolver,
    VerifiedKnowledge,
    canonical_json,
    collect_decision_inputs,
    digest,
)
from app.services.exceptions.vocab import NON_TERMINAL_FINDING
from app.services.knowledge import KnowledgeIntegrityError
from app.services.profile import current_profile
from app.services.proposals.schema import (
    ActiveBlock,
    DecisionError,
    HeadSession,
    ProposalDoc,
    SnapshotRef,
    Strict,
    ValidationContext,
    ValidationIssue,
    anchor_key,
    parse_document,
)
from app.services.proposals.validation import FreshnessReason, proposal_freshness, validate_parsed, validate_subset


def _lock(session: Session) -> Any:
    from app.models import AppState

    global_write_lock(session)
    state = session.get(AppState, 1, with_for_update=True, populate_existing=True)
    assert state is not None
    return state


def _snapshot_ref(row: Any) -> SnapshotRef:
    meta = (row.payload or {}).get("snapshot_meta") or {}
    routes = row.kb_routes
    selection = routes.get("selection", []) if isinstance(routes, dict) else routes
    return SnapshotRef(
        row.id,
        row.operation,
        row.as_of,
        row.generated_at,
        row.source_fingerprint,
        tuple(selection),
        row.kb_digest,
        meta.get("safety_guard"),
    )


def _active_block(session: Session) -> ActiveBlock | None:
    row = active_block_version(session)
    return ActiveBlock(row.block_uid, row.id, row.version, tuple(row.eligible_recipe_ids)) if row else None


def load_context(
    session: Session, snapshot_id: uuid.UUID, *, now: datetime, kb: VerifiedKnowledge
) -> ValidationContext:
    from app.coach_v2_models import CoachSnapshot
    from app.exception_models import ExceptionFinding, ExceptionPatch
    from app.planning_models import BlockVersion, Event
    from app.services.block_benchmark import benchmark_status
    from app.services.calendar import state_at
    from app.services.timezone import athlete_tz

    snapshot = session.get(CoachSnapshot, snapshot_id)
    tz = athlete_tz(session)
    today = date_in_zone(now, tz)
    head = head_version(session)
    rows = state_at(session, head)
    head_sessions = {
        row["session_uid"]: HeadSession(
            row["session_uid"],
            row["revision"],
            row["local_date"],
            row["slot"],
            row["kind"],
            row.get("recipe_id"),
            row.get("custom", False),
            row.get("placeholder", False),
            row.get("locked", False),
            row.get("legacy_unstructured", False),
            row.get("intent", ""),
            row.get("certainty", ""),
            row.get("planned_duration_s"),
            row.get("planned_distance_m"),
            row.get("structure"),
            row.get("strength_slot_id"),
            row.get("notes"),
        )
        for row in rows
    }
    profile = current_profile(session)
    anchor = profile.cycle_anchor if profile and profile.anchor_confirmed else None
    inputs = (
        collect_decision_inputs(session, snapshot.operation, snapshot.as_of, now=now, kb=kb)
        if snapshot
        else {"source_fingerprint": "", "safety_guard": None}
    )
    active = _active_block(session)
    active_row = session.get(BlockVersion, active.version_id) if active else None
    return ValidationContext(
        now,
        today,
        tz,
        _snapshot_ref(snapshot) if snapshot else None,
        head,
        head_sessions,
        active,
        anchor,
        inputs["safety_guard"] if isinstance(inputs["safety_guard"], dict) else None,
        str(inputs["source_fingerprint"]),
        kb.digest,
        kb,
        findings={fid: status for fid, status in session.execute(select(ExceptionFinding.id, ExceptionFinding.status))},
        patches={pid: status for pid, status in session.execute(select(ExceptionPatch.id, ExceptionPatch.status))},
        events={eid: (status, day) for eid, status, day in session.execute(select(Event.id, Event.status, Event.event_date))},
        open_rule_codes=frozenset(session.scalars(select(ExceptionFinding.rule_code).where(ExceptionFinding.status == "open"))),
        benchmark=benchmark_status(session, active_row, today) if active_row else None,
    )


@dataclass(frozen=True)
class SubmitResult:
    proposal_id: uuid.UUID
    revision: int
    status: str
    issues: list[ValidationIssue]


def submit_proposal(session: Session, raw: dict, *, now: datetime, resolve_kb: KnowledgeResolver) -> SubmitResult:
    from app.coach_v2_models import CoachProposal, CoachSnapshot

    _lock(session)
    input_hash = digest(raw)
    existing = session.scalar(select(CoachProposal).where(CoachProposal.input_hash == input_hash)
        .execution_options(populate_existing=True))
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
    active = session.scalar(select(CoachProposal).where(
        CoachProposal.status.in_(("pending", "stale", "invalid")))
        .with_for_update().execution_options(populate_existing=True))
    if active is not None:
        raise DecisionError("active_proposal_exists",
            f"Proposal {active.id} is still open. Review or discard it before submitting another.",
            409, [ValidationIssue("active_proposal_id", "active_proposal_id", str(active.id)),
                ValidationIssue("active_revision", "active_revision", str(active.revision))])
    doc, issues = parse_document(raw)
    if doc is None:
        raise DecisionError("invalid_proposal", "Proposal schema invalid", 422, issues)
    snapshot = session.get(CoachSnapshot, doc.snapshot_id)
    if snapshot is None:
        raise DecisionError("snapshot_not_found", "Snapshot not found", 404)
    kb = resolve_kb(_snapshot_ref(snapshot).kb_routes)
    ctx = load_context(session, doc.snapshot_id, now=now, kb=kb)
    result = validate_parsed(doc, ctx)
    proposal = CoachProposal(
        operation=doc.operation,
        snapshot_id=doc.snapshot_id,
        base_calendar_version=doc.base_calendar_version,
        base_block_version_id=doc.base_block_version_id,
        status=result.status,
        submitted_at=now,
        summary=doc.summary,
        rationale=doc.rationale,
        confidence=doc.confidence.model_dump(),
        evidence_ids=doc.evidence_ids,
        policy_ids=doc.policy_ids,
        recipe_ids=doc.recipe_ids,
        follow_up=doc.follow_up,
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
                after=change.after.model_dump(mode="json", exclude_unset=True) if change.after else None,
                reason=change.reason,
                decision="pending",
            )
        )
    session.flush()


class RevisionRequest(Strict):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
    document: dict[str, Any]


def _store_revision(session: Session, proposal: Any, now: datetime, reason: str,
                    changed_ids: list[str], changed_fields: list[str], request_hash: str | None) -> None:
    from app.coach_v2_models import CoachProposalRevision

    session.add(CoachProposalRevision(proposal_id=proposal.id, revision=proposal.revision,
        saved_at=now, reason=reason, payload=proposal.payload,
        changed_change_ids=changed_ids, changed_fields=changed_fields, request_hash=request_hash))
    session.flush()


def revise_proposal(session: Session, proposal_id: uuid.UUID, req: RevisionRequest,
                    *, now: datetime, resolve_kb: KnowledgeResolver) -> SubmitResult:
    """Replace a draft atomically; keep its identity, prior versions and calendar untouched."""
    from app.coach_v2_models import CoachProposal, CoachProposalChange, CoachProposalRevision, CoachSnapshot

    _lock(session)
    proposal = session.scalar(select(CoachProposal).where(CoachProposal.id == proposal_id)
        .with_for_update().execution_options(populate_existing=True))
    if proposal is None:
        raise DecisionError("proposal_not_found", "Proposal not found", 404)
    if proposal.status in {"accepted", "partially_accepted", "rejected", "discarded"}:
        raise DecisionError("proposal_decided", "This proposal has a decision. Propose changes to the current calendar instead.", 409)
    if not req.reason.strip():
        raise DecisionError("invalid_revision", "Explain the requested revision", 422)
    request_hash = digest(req.model_dump(mode="json"))
    if req.expected_revision != proposal.revision:
        # A retry of the immediately preceding successful edit must not create another revision.
        latest = session.get(CoachProposalRevision, (proposal_id, proposal.revision))
        if (req.expected_revision + 1 == proposal.revision and latest
                and latest.request_hash == request_hash):
            return SubmitResult(proposal.id, proposal.revision, proposal.status, [])
        raise DecisionError("proposal_revision_conflict", "This proposal was revised. Read the latest draft before editing.", 409)
    doc, issues = parse_document(req.document)
    if doc is None:
        raise DecisionError("invalid_proposal", "Revision schema invalid; existing draft unchanged", 422, issues)
    snapshot = session.get(CoachSnapshot, doc.snapshot_id)
    if snapshot is None:
        raise DecisionError("snapshot_not_found", "Snapshot not found", 404)
    kb = resolve_kb(_snapshot_ref(snapshot).kb_routes)
    ctx = load_context(session, doc.snapshot_id, now=now, kb=kb)
    validated = validate_parsed(doc, ctx)
    if validated.status != "pending":
        raise DecisionError("stale_evidence" if validated.status == "stale" else "invalid_proposal",
            "Revision failed validation; existing draft unchanged", 409 if validated.status == "stale" else 422,
            validated.issues)
    payload = doc.model_dump(mode="json", exclude_unset=True)
    if payload == proposal.payload and proposal.status == "pending":
        return SubmitResult(proposal.id, proposal.revision, proposal.status, [])
    old_changes = {item["change_id"]: item for item in proposal.payload.get("changes", [])}
    new_changes = {item["change_id"]: item for item in payload.get("changes", [])}
    changed_ids = sorted(key for key in old_changes.keys() | new_changes.keys()
        if old_changes.get(key) != new_changes.get(key))
    changed_fields = sorted(key for key in proposal.payload.keys() | payload.keys()
        if key != "changes" and proposal.payload.get(key) != payload.get(key))
    # Retain input_hash as the identity of the original submit, including its retries.
    for name in ("operation", "snapshot_id", "base_calendar_version", "base_block_version_id", "summary",
                 "rationale", "evidence_ids", "policy_ids", "recipe_ids", "follow_up", "escalation", "skill_version"):
        setattr(proposal, name, getattr(doc, name))
    proposal.confidence = doc.confidence.model_dump()
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


def discard_proposal(session: Session, proposal_id: uuid.UUID, expected_revision: int,
                     *, now: datetime) -> SubmitResult:
    """Close an open proposal without changing calendar or source state."""
    from app.coach_v2_models import CoachProposal

    _lock(session)
    proposal = session.scalar(select(CoachProposal).where(CoachProposal.id == proposal_id)
        .with_for_update().execution_options(populate_existing=True))
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

    state = _lock(session)
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
    ref = _snapshot_ref(snapshot)
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
