"""Proposal persistence and lineage on the guarded synthetic database."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.coach import resolve_kb
from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.coach_v2_models import CoachDecisionKey, CoachProposal, CoachProposalChange, CoachSnapshot
from app.domain.session_class import classify
from app.exception_models import ExceptionFinding, ExceptionPatch
from app.models import Activity, AppState, ProfileVersion
from app.planning_models import Block, BlockBenchmarkResult, BlockVersion, Event, IntensityAnchor
from app.services import calendar
from app.services.decision_inputs import VerifiedKnowledge, collect_decision_inputs
from app.services.proposals.context import load_context
from app.services.proposals.decision import DecisionRequest, decide_proposal
from app.services.proposals.lifecycle import SubmitResult, discard_proposal, submit_proposal
from app.services.proposals.schema import DecisionError
from app.services.snapshot.build import build_snapshot

NOW = datetime(2026, 11, 16, 15, tzinfo=UTC)
TODAY = date(2026, 11, 16)
KB = VerifiedKnowledge("0" * 64, (), (), frozenset({"P001"}), frozenset({"REC001"}), frozenset({"E-AER-01"}))


def _resolve(selection: tuple[dict, ...]) -> VerifiedKnowledge:
    assert selection == ()
    return KB


def _snapshot(session: Session, operation: str = "review_rolling_plan") -> tuple[CoachSnapshot, uuid.UUID]:
    state = session.get(AppState, 1)
    assert state is not None
    rows = calendar.state_at(session, state.calendar_head_version)
    run_uid = next(row["session_uid"] for row in rows if row["kind"] == "run")
    inputs = collect_decision_inputs(session, operation, TODAY, now=NOW, kb=KB)
    active = session.scalars(
        select(BlockVersion).where(BlockVersion.status == "active").order_by(BlockVersion.version.desc()).limit(1)
    ).first()
    snapshot = CoachSnapshot(
        operation=operation,
        as_of=TODAY,
        generated_at=NOW - timedelta(hours=1),
        calendar_version_number=state.calendar_head_version,
        block_version_id=active.id if active else None,
        data_revision=state.data_revision,
        payload={"snapshot_meta": {"safety_guard": inputs["safety_guard"], "knowledge": {"selected_records": []}}},
        source_fingerprint=inputs["source_fingerprint"],
        source_versions=inputs["source_versions"],
        kb_digest=KB.digest,
        payload_sha256="0" * 64,
        kb_package_version="test",
        kb_routes=[],  # type: ignore[arg-type]
        approx_tokens=0,
    )
    session.add(snapshot)
    session.flush()
    return snapshot, run_uid


def _doc(snapshot: CoachSnapshot, uid: uuid.UUID) -> dict:
    return {
        "schema_version": "coach_proposal.v1",
        "operation": snapshot.operation,
        "snapshot_id": str(snapshot.id),
        "base_calendar_version": snapshot.calendar_version_number,
        "base_block_version_id": str(snapshot.block_version_id) if snapshot.block_version_id else None,
        "summary": "Add easy time",
        "rationale": "Ready for a small increase",
        "confidence": {"decision": "moderate", "evidence": "moderate", "data": "moderate"},
        "changes": [
            {
                "change_id": "c1",
                "op": "modify",
                "session_uid": str(uid),
                "after": {"planned_duration_s": 2400},
                "reason": "Progression",
            }
        ],
        "preserved": [],
        "evidence_ids": ["E-AER-01"],
        "policy_ids": ["P001"],
        "recipe_ids": ["REC001"],
        "skill_version": "running-coach.v1",
    }


def _block_fields(review_date: str, benchmark_date: str) -> dict:
    return {
        "status": "active",
        "objective": "Build",
        "rationale": "Ready",
        "maintained_qualities": [],
        "non_goals": [],
        "eligible_recipe_ids": ["REC001", "REC009"],
        "progression_dimension": "duration",
        "constraints": [],
        "start_date": "2026-11-16",
        "review_date": review_date,
        "completion_indicators": [],
        "early_review_triggers": [],
        "objective_status": "unresolved",
        "benchmark": {
            "kind": "time_trial",
            "protocol": "5 km solo time trial",
            "planned_date": benchmark_date,
            "progress_if": "Under 22:00",
            "consolidate_if": "Over 22:30",
        },
    }


def _strength_adds(*dates: str) -> list[dict]:
    return [
        {
            "change_id": f"c{i}",
            "op": "add",
            "after": {"local_date": day, "kind": "strength", "intent": "Full body"},
            "reason": "Plan the week",
        }
        for i, day in enumerate(dates, start=1)
    ]


def _block_review(session: Session, review_date: str, benchmark_date: str, adds: tuple[str, ...]):
    snapshot, uid = _snapshot(session, "review_training_block")
    raw = _doc(snapshot, uid)
    raw["changes"] = _strength_adds(*adds)
    raw["block_change"] = {
        "decision": "start",
        "block_uid": None,
        "version_fields": _block_fields(review_date, benchmark_date),
    }
    proposal = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    assert proposal.status == "pending", [(i.code, i.path) for i in proposal.issues]
    return proposal


def _block_req(key: str, accepted: list[str], rejected: list[str], *, block: bool) -> DecisionRequest:
    return DecisionRequest(
        idempotency_key=key,
        expected_head=1,
        expected_revision=1,
        accept_change_ids=accepted,
        reject_change_ids=rejected,
        accept_block_change=block,
    )


OUTLINE = [
    {"emphasis": "threshold durability", "weeks": 4},
    {"emphasis": "half-marathon-specific endurance", "weeks": 5},
    {"emphasis": "race-specific sharpening, taper, race", "weeks": 4},
]


def _goal_event(session: Session, day: date, *, status: str = "registered") -> Event:
    event = Event(
        name="Synthetic half marathon",
        event_date=day,
        distance_m=21097,
        purpose="pr",
        goal_time_s=6000,
        rank=1,
        status=status,
    )
    session.add(event)
    session.flush()
    return event


def _target_review(
    session: Session,
    *,
    decision: str = "start",
    block_uid: uuid.UUID | None = None,
    target: Event | None = None,
    outline: list[dict] | None = None,
    **fields: object,
) -> SubmitResult:
    snapshot, uid = _snapshot(session, "review_training_block")
    raw = _doc(snapshot, uid)
    raw["changes"] = []
    raw["block_change"] = {
        "decision": decision,
        "block_uid": str(block_uid) if block_uid else None,
        "version_fields": {
            **_block_fields("2026-12-14", "2026-12-05"),
            "target_event_id": str(target.id) if target else None,
            "build_outline": outline if outline is not None else [],
            **fields,
        },
    }
    return submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)


def _issues(proposal: SubmitResult) -> list[tuple[str, str]]:
    return [(issue.code, issue.path) for issue in proposal.issues]


def _accept_block(session: Session, proposal: SubmitResult, key: str) -> BlockVersion:
    result = decide_proposal(
        session, proposal.proposal_id, _block_req(key, [], [], block=True), now=NOW, resolve_kb=_resolve
    )
    assert result.status == "accepted" and result.block_version_id is not None
    block = session.get(BlockVersion, result.block_version_id)
    assert block is not None
    return block


def _decide_block(session, proposal, key, accepted, rejected, *, block):
    return decide_proposal(
        session, proposal.proposal_id, _block_req(key, accepted, rejected, block=block), now=NOW, resolve_kb=_resolve
    )


def _req(head: int, key: str, accepted: list[str] | None = None, rejected: list[str] | None = None) -> DecisionRequest:
    return DecisionRequest(
        idempotency_key=key,
        expected_head=head,
        expected_revision=1,
        accept_change_ids=accepted or [],
        reject_change_ids=rejected or [],
    )


def _finding(
    session: Session,
    rule_code: str = "FATIGUE_PERSISTING",
    *,
    category: str = "accumulated_fatigue",
    severity: str = "caution",
    entity_key: str | None = None,
    evidence_at: datetime = NOW - timedelta(hours=2),
) -> ExceptionFinding:
    finding = ExceptionFinding(
        rule_code=rule_code,
        rule_version="exceptions.v1",
        category=category,
        severity=severity,
        entity_key=entity_key or rule_code.lower(),
        status="open",
        summary="Synthetic",
        evidence=[],
        evidence_at=evidence_at,
        first_seen_at=evidence_at,
        last_seen_at=evidence_at,
    )
    session.add(finding)
    session.flush()
    return finding


def _exception_doc(
    snapshot: CoachSnapshot,
    uid: uuid.UUID,
    finding_ids: list[uuid.UUID],
    *,
    changes: bool = True,
    ladder: str = "next_session",
) -> dict:
    raw = _doc(snapshot, uid)
    raw["changes"] = (
        [
            {
                "change_id": "c1",
                "op": "modify",
                "session_uid": str(uid),
                "after": {"planned_duration_s": 1200},
                "reason": "Fatigue",
            }
        ]
        if changes
        else []
    )
    raw["exception"] = {
        "finding_ids": [str(fid) for fid in finding_ids],
        "category": "accumulated_fatigue",
        "severity": "caution",
        "confidence": "moderate",
        "triggering_evidence": "Fatigue 8 on two mornings",
        "relevant_context": None,
        "ladder_level": ladder,
        "patch_window": {"start": "2026-11-16", "end": "2026-11-18"},
        "unchanged": [],
        "reassess_on": "2026-11-19",
        "monitor": ["Morning fatigue"],
        "return_criteria": ["Usual fatigue twice"],
        "escalate_criteria": ["High through Saturday"],
    }
    return raw


def _accepted_patch(session: Session) -> tuple[ExceptionPatch, ExceptionFinding, uuid.UUID]:
    finding = _finding(session)
    snapshot, uid = _snapshot(session, "exception_review")
    submitted = submit_proposal(session, _exception_doc(snapshot, uid, [finding.id]), now=NOW, resolve_kb=_resolve)
    assert submitted.status == "pending", submitted.issues
    result = decide_proposal(
        session, submitted.proposal_id, _req(1, "exc-accept", ["c1"]), now=NOW, resolve_kb=_resolve
    )
    assert result.calendar_version == 2
    patch = session.scalar(select(ExceptionPatch).where(ExceptionPatch.proposal_id == submitted.proposal_id))
    assert patch is not None
    return patch, finding, submitted.proposal_id


def test_submit_retry_acceptance_and_terminal_alias(proposal_session: Session) -> None:
    session = proposal_session
    snapshot, uid = _snapshot(session)
    raw = _doc(snapshot, uid)
    baseline = collect_decision_inputs(session, snapshot.operation, TODAY, now=NOW, kb=KB)["source_fingerprint"]
    first = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    second = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    assert first == second and first.status == "pending"
    assert session.scalar(select(func.count(CoachProposal.id))) == 1
    assert collect_decision_inputs(session, snapshot.operation, TODAY, now=NOW, kb=KB)["source_fingerprint"] == baseline
    state_before = session.get(AppState, 1)
    assert state_before is not None
    revision_before = state_before.data_revision
    accepted = decide_proposal(
        session, first.proposal_id, _req(1, "decision-key-1", ["c1"]), now=NOW, resolve_kb=_resolve
    )
    assert accepted.status == "accepted" and accepted.calendar_version == 2
    version = session.scalar(select(CalendarVersion).where(CalendarVersion.number == 2))
    assert version is not None
    assert (version.kind, version.actor, version.proposal_id) == ("proposal_accept", "coach", first.proposal_id)
    assert (
        len(session.scalars(select(CalendarSessionRevision).where(CalendarSessionRevision.session_uid == uid)).all())
        == 2
    )
    session.commit()
    state_after = session.get(AppState, 1, populate_existing=True)
    assert state_after is not None and state_after.data_revision == revision_before + 1
    replay = decide_proposal(
        session,
        first.proposal_id,
        _req(999, "decision-key-2", ["c1"]),
        now=NOW + timedelta(days=2),
        resolve_kb=_resolve,
    )
    assert replay == accepted
    assert session.scalar(select(func.count(CoachDecisionKey.idempotency_key))) == 2
    with pytest.raises(DecisionError, match="Decision selection changed"):
        decide_proposal(session, first.proposal_id, _req(2, "decision-key-2", [], ["c1"]), now=NOW, resolve_kb=_resolve)


def test_source_only_drift_marks_pending_stale(proposal_session: Session) -> None:
    session = proposal_session
    snapshot, uid = _snapshot(session)
    proposal = submit_proposal(session, _doc(snapshot, uid), now=NOW, resolve_kb=_resolve)
    profile = session.scalars(select(ProfileVersion).order_by(ProfileVersion.version.desc()).limit(1)).one()
    profile.scheduled_strength_days = [1, 5]
    session.flush()
    with pytest.raises(DecisionError) as caught:
        decide_proposal(session, proposal.proposal_id, _req(1, "decision-key-3", ["c1"]), now=NOW, resolve_kb=_resolve)
    assert (caught.value.code, caught.value.commit) == ("stale_evidence", True)
    stored = session.get(CoachProposal, proposal.proposal_id)
    assert stored is not None and stored.status == "stale"
    assert session.scalar(select(func.count(CalendarVersion.number))) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [("sport", "treadmill_running"), ("avg_hr_bpm", 150.0), ("moving_s", 1750.0), ("workout_rpe", 6.0)],
)
def test_key_run_activity_fact_drift_marks_pending_stale(proposal_session: Session, field: str, value: object) -> None:
    session = proposal_session
    head_rows = calendar.state_at(session, 1)
    easy_uid = next(row["session_uid"] for row in head_rows if row["kind"] == "run")
    key_uid = uuid.uuid4()
    finished_at = NOW - timedelta(days=1)
    session.add(
        CalendarSessionRevision(
            session_uid=key_uid,
            revision=1,
            calendar_version_number=1,
            local_date=finished_at.date(),
            slot=0,
            kind="run",
            recipe_id="REC002",
            intent="Long run",
            certainty="committed",
            planned_duration_s=1800,
        )
    )
    activity = Activity(
        start_at=finished_at,
        original_start=finished_at.isoformat(),
        local_date=finished_at.date(),
        sport="running",
        distance_m=4000.0,
        moving_s=1800.0,
        timer_s=1800.0,
        resolution_state="resolved",
    )
    session.add(activity)
    session.flush()
    session.add(
        SessionCompletion(
            session_uid=key_uid,
            activity_id=activity.id,
            status="completed_as_planned",
            match_method="explicit",
            updated_at=NOW,
        )
    )
    snapshot, _ = _snapshot(session)
    proposal = submit_proposal(session, _doc(snapshot, easy_uid), now=NOW, resolve_kb=_resolve)

    setattr(activity, field, value)
    session.flush()
    with pytest.raises(DecisionError) as caught:
        decide_proposal(session, proposal.proposal_id, _req(1, "fact-drift", ["c1"]), now=NOW, resolve_kb=_resolve)
    assert (caught.value.code, caught.value.commit) == ("stale_evidence", True)


def test_accepted_add_records_server_session_uid(proposal_session: Session) -> None:
    session = proposal_session
    snapshot, uid = _snapshot(session)
    raw = _doc(snapshot, uid)
    raw["changes"] = [
        {
            "change_id": "c1",
            "op": "add",
            "after": {
                "local_date": "2026-11-22",
                "kind": "run",
                "intent": "Easy",
                "custom": True,
                "structure": [{"type": "work", "duration_type": "time", "duration_value": 600}],
            },
            "reason": "Add easy run",
        }
    ]
    proposal = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    assert proposal.status == "pending", [(item.code, item.path) for item in proposal.issues]
    result = decide_proposal(
        session, proposal.proposal_id, _req(1, "decision-key-add", ["c1"]), now=NOW, resolve_kb=_resolve
    )
    assert result.calendar_version == 2
    row = session.scalar(select(CoachProposalChange).where(CoachProposalChange.proposal_id == proposal.proposal_id))
    assert row is not None and row.session_uid is not None
    created = session.scalar(
        select(CalendarSessionRevision).where(CalendarSessionRevision.session_uid == row.session_uid)
    )
    assert created is not None and (created.local_date, created.recipe_id) == (date(2026, 11, 22), None)


def test_anchor_only_acceptance_stales_other_pending(proposal_session: Session) -> None:
    session = proposal_session
    snapshot, uid = _snapshot(session, "recalibrate_intensity")
    raw = _doc(snapshot, uid)
    raw["changes"] = []
    raw["anchor_changes"] = [
        {
            "kind": "hr_threshold_lower",
            "value_low": 165,
            "unit": "bpm",
            "protocol": "manual",
            "confidence": "moderate",
            "calibrated_at": NOW.isoformat(),
        }
    ]
    first = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    other = {**raw, "summary": "Another pending proposal"}
    with pytest.raises(DecisionError) as conflict:
        submit_proposal(session, other, now=NOW, resolve_kb=_resolve)
    assert conflict.value.code == "active_proposal_exists"
    assert [(field.path, field.message) for field in conflict.value.fields] == [
        ("active_proposal_id", str(first.proposal_id)),
        ("active_revision", "1"),
    ]
    result = decide_proposal(
        session,
        first.proposal_id,
        DecisionRequest(
            idempotency_key="decision-anchor",
            expected_head=1,
            expected_revision=1,
            accept_change_ids=[],
            reject_change_ids=[],
            accept_anchor_changes=["hr_threshold_lower-2026-11-16"],
        ),
        now=NOW,
        resolve_kb=_resolve,
    )
    assert result.status == "accepted" and result.calendar_version is None
    assert result.anchor_keys == ["hr_threshold_lower-2026-11-16"]
    assert result.stale_proposals == []
    assert (session.scalar(select(func.count(IntensityAnchor.id))) or 0) >= 1


def test_block_same_state_acceptance_is_noop(proposal_session: Session) -> None:
    session = proposal_session
    snapshot, uid = _snapshot(session, "review_training_block")
    fields = {
        "status": "active",
        "objective": "Build",
        "rationale": "Ready",
        "maintained_qualities": [],
        "non_goals": [],
        "eligible_recipe_ids": ["REC001", "REC009"],
        "progression_dimension": "duration",
        "constraints": [],
        "start_date": "2026-11-16",
        "review_date": "2026-12-28",
        "completion_indicators": [],
        "early_review_triggers": [],
        "objective_status": "unresolved",
        "benchmark": {
            "kind": "time_trial",
            "protocol": "5 km solo time trial",
            "planned_date": "2026-12-20",
            "progress_if": "Under 22:00",
            "consolidate_if": "Over 22:30",
        },
    }
    raw = _doc(snapshot, uid)
    raw["changes"] = []
    raw["block_change"] = {"decision": "start", "block_uid": None, "version_fields": fields}
    first = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    assert first.status == "pending"
    started = decide_proposal(
        session,
        first.proposal_id,
        DecisionRequest(
            idempotency_key="decision-block1",
            expected_head=1,
            expected_revision=1,
            accept_change_ids=[],
            reject_change_ids=[],
            accept_block_change=True,
        ),
        now=NOW,
        resolve_kb=_resolve,
    )
    assert started.block_version_id is not None and started.calendar_version is None
    block = session.get(BlockVersion, started.block_version_id)
    assert block is not None
    count = session.scalar(select(func.count(BlockVersion.id)))
    next_snapshot, uid = _snapshot(session, "review_training_block")
    raw = _doc(next_snapshot, uid)
    raw["changes"] = []
    raw["block_change"] = {"decision": "continue", "block_uid": str(block.block_uid), "version_fields": fields}
    second = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    assert second.status == "pending"
    continued = decide_proposal(
        session,
        second.proposal_id,
        DecisionRequest(
            idempotency_key="decision-block2",
            expected_head=1,
            expected_revision=1,
            accept_change_ids=[],
            reject_change_ids=[],
            accept_block_change=True,
        ),
        now=NOW,
        resolve_kb=_resolve,
    )
    assert continued.block_version_id == started.block_version_id
    assert session.scalar(select(func.count(BlockVersion.id))) == count
    assert continued.stale_proposals == []


def test_derived_completion_status_is_not_decision_source(proposal_session: Session) -> None:
    session = proposal_session
    uid = next(row["session_uid"] for row in calendar.state_at(session, 1) if row["kind"] == "run")
    completion = SessionCompletion(
        session_uid=uid, status="unknown", match_method="none", version=1, input_version=1, updated_at=NOW
    )
    session.add(completion)
    session.flush()
    before = collect_decision_inputs(session, "review_rolling_plan", TODAY, now=NOW, kb=KB)["source_fingerprint"]
    completion.status = "skipped"
    completion.version = 2
    session.flush()
    after = collect_decision_inputs(session, "review_rolling_plan", TODAY, now=NOW, kb=KB)["source_fingerprint"]
    assert after == before


def test_head_drift_and_cross_proposal_key_conflict(proposal_session: Session) -> None:
    session = proposal_session
    snapshot, uid = _snapshot(session)
    raw = _doc(snapshot, uid)
    first = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    with pytest.raises(DecisionError) as active:
        submit_proposal(session, {**raw, "summary": "Other choice"}, now=NOW, resolve_kb=_resolve)
    assert active.value.code == "active_proposal_exists"
    rejected = decide_proposal(
        session, first.proposal_id, _req(1, "shared-decision-key", [], ["c1"]), now=NOW, resolve_kb=_resolve
    )
    assert rejected.status == "rejected" and rejected.calendar_version is None
    second = submit_proposal(session, {**raw, "summary": "Other choice"}, now=NOW, resolve_kb=_resolve)
    with pytest.raises(DecisionError) as conflict:
        decide_proposal(
            session, second.proposal_id, _req(1, "shared-decision-key", [], ["c1"]), now=NOW, resolve_kb=_resolve
        )
    assert conflict.value.code == "idempotency_conflict"
    state = session.get(AppState, 1)
    assert state is not None
    state.calendar_head_version = 2
    session.add(CalendarVersion(number=2, parent_number=1, kind="manual_edit", actor="user"))
    session.flush()
    with pytest.raises(DecisionError) as moved:
        decide_proposal(
            session, second.proposal_id, _req(2, "other-decision-key", [], ["c1"]), now=NOW, resolve_kb=_resolve
        )
    assert (moved.value.code, moved.value.commit) == ("proposal_stale", True)


@pytest.mark.parametrize("status", ["pending", "stale", "invalid"])
def test_discard_closes_open_proposal_without_calendar_change(proposal_session: Session, status: str) -> None:
    session = proposal_session
    snapshot, uid = _snapshot(session)
    raw = _doc(snapshot, uid)
    first = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    stored = session.get(CoachProposal, first.proposal_id)
    stored.status = status
    session.flush()
    head = session.get(AppState, 1).calendar_head_version
    discarded = discard_proposal(session, first.proposal_id, 1, now=NOW)
    assert discarded.status == "discarded"
    assert discard_proposal(session, first.proposal_id, 1, now=NOW) == discarded
    assert stored.discarded_at == NOW
    assert session.get(AppState, 1).calendar_head_version == head
    assert submit_proposal(session, raw, now=NOW, resolve_kb=_resolve).status == "discarded"
    assert submit_proposal(session, {**raw, "summary": "Replacement"}, now=NOW, resolve_kb=_resolve).status == "pending"
    with pytest.raises(DecisionError, match="Discarded"):
        decide_proposal(
            session, first.proposal_id, _req(head, "discarded-key", ["c1"], []), now=NOW, resolve_kb=_resolve
        )


def test_discard_rejects_revision_race_and_decided_proposal(proposal_session: Session) -> None:
    session = proposal_session
    snapshot, uid = _snapshot(session)
    first = submit_proposal(session, _doc(snapshot, uid), now=NOW, resolve_kb=_resolve)
    with pytest.raises(DecisionError) as conflict:
        discard_proposal(session, first.proposal_id, 2, now=NOW)
    assert conflict.value.code == "proposal_revision_conflict"
    decide_proposal(
        session, first.proposal_id, _req(1, "reject-before-discard", [], ["c1"]), now=NOW, resolve_kb=_resolve
    )
    with pytest.raises(DecisionError) as decided:
        discard_proposal(session, first.proposal_id, 1, now=NOW)
    assert decided.value.code == "proposal_decided"


def test_verified_knowledge_content_drift_is_stale_evidence(proposal_session: Session) -> None:
    from dataclasses import replace

    session = proposal_session
    snapshot, uid = _snapshot(session)
    proposal = submit_proposal(session, _doc(snapshot, uid), now=NOW, resolve_kb=_resolve)
    changed = replace(
        KB,
        digest="1" * 64,
        selected_records=(
            {
                "path": "recipes/running_session_families.json",
                "record_id": "REC001",
                "content": {"title": "Easy revised"},
            },
        ),
    )
    with pytest.raises(DecisionError) as caught:
        decide_proposal(
            session,
            proposal.proposal_id,
            _req(1, "knowledge-drift-key", ["c1"]),
            now=NOW,
            resolve_kb=lambda selection: changed,
        )
    assert (caught.value.code, caught.value.commit) == ("stale_evidence", True)
    assert session.scalar(select(func.count(CalendarVersion.id))) == 1


def test_reject_all_anchor_only_creates_no_source(proposal_session: Session) -> None:
    session = proposal_session
    snapshot, uid = _snapshot(session, "recalibrate_intensity")
    raw = _doc(snapshot, uid)
    raw["changes"] = []
    raw["anchor_changes"] = [
        {
            "kind": "hr_threshold_lower",
            "value_low": 165,
            "unit": "bpm",
            "protocol": "manual",
            "confidence": "moderate",
            "calibrated_at": NOW.isoformat(),
        }
    ]
    proposal = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    before = session.scalar(select(func.count(IntensityAnchor.id)))
    result = decide_proposal(session, proposal.proposal_id, _req(1, "reject-anchor-key"), now=NOW, resolve_kb=_resolve)
    assert result.status == "rejected" and result.calendar_version is None and result.anchor_keys == []
    assert session.scalar(select(func.count(IntensityAnchor.id))) == before


def test_failure_after_anchor_write_rolls_back_entire_decision(proposal_session: Session, monkeypatch) -> None:
    session = proposal_session
    snapshot, uid = _snapshot(session, "recalibrate_intensity")
    raw = _doc(snapshot, uid)
    raw["changes"] = [
        {
            "change_id": "c1",
            "op": "modify",
            "session_uid": str(uid),
            "after": {"intent": "Revised easy"},
            "reason": "Recalibrate",
        }
    ]
    raw["anchor_changes"] = [
        {
            "kind": "hr_threshold_lower",
            "value_low": 165,
            "unit": "bpm",
            "protocol": "manual",
            "confidence": "moderate",
            "calibrated_at": NOW.isoformat(),
        }
    ]
    proposal = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    assert proposal.status == "pending"
    before = (
        session.scalar(select(func.count(IntensityAnchor.id))),
        session.scalar(select(func.count(CalendarVersion.id))),
    )

    def fail_after_anchor(*args, **kwargs):
        assert session.scalar(select(func.count(IntensityAnchor.id))) == before[0] + 1
        raise RuntimeError("injected_calendar_failure")

    monkeypatch.setattr(calendar, "apply_edits", fail_after_anchor)
    with pytest.raises(RuntimeError, match="injected_calendar_failure"):
        with session.begin_nested():
            decide_proposal(
                session,
                proposal.proposal_id,
                DecisionRequest(
                    idempotency_key="rollback-decision-key",
                    expected_head=1,
                    expected_revision=1,
                    accept_change_ids=["c1"],
                    reject_change_ids=[],
                    accept_anchor_changes=["hr_threshold_lower-2026-11-16"],
                ),
                now=NOW,
                resolve_kb=_resolve,
            )
    assert (
        session.scalar(select(func.count(IntensityAnchor.id))),
        session.scalar(select(func.count(CalendarVersion.id))),
    ) == before
    stored = session.get(CoachProposal, proposal.proposal_id, populate_existing=True)
    assert stored is not None and stored.status == "pending" and stored.decision_hash is None
    assert session.get(CoachDecisionKey, "rollback-decision-key") is None


def test_ended_block_latest_version_is_not_active(proposal_session: Session) -> None:
    from app.services.proposals.context import active_block

    session = proposal_session
    block = Block(block_uid=uuid.uuid4())
    session.add(block)
    session.flush()
    fields = {
        "objective": "Build",
        "rationale": "Ready",
        "maintained_qualities": [],
        "non_goals": [],
        "eligible_recipe_ids": ["REC001"],
        "progression_dimension": "duration",
        "constraints": [],
        "start_date": TODAY,
        "review_date": date(2026, 12, 28),
        "completion_indicators": [],
        "early_review_triggers": [],
        "objective_status": "unresolved",
    }
    session.add(BlockVersion(block_uid=block.block_uid, version=1, status="active", **fields))
    session.add(BlockVersion(block_uid=block.block_uid, version=2, status="ended", **fields))
    session.flush()
    assert active_block(session) is None


def test_manual_session_rpe_changes_fingerprint(proposal_session: Session) -> None:
    from app.checkin_models import SessionRpe
    from app.models import ManualSession

    session = proposal_session
    manual = ManualSession(date=TODAY, kind="run", duration_s=1800, effort=4)
    session.add(manual)
    session.flush()
    rpe = SessionRpe(manual_session_id=manual.id, rpe=4.0, source="manual", collected_at=NOW, collection_delay_s=0)
    session.add(rpe)
    session.flush()
    before = collect_decision_inputs(session, "review_rolling_plan", TODAY, now=NOW, kb=KB)["source_fingerprint"]
    rpe.rpe = 6.0
    session.flush()
    after = collect_decision_inputs(session, "review_rolling_plan", TODAY, now=NOW, kb=KB)["source_fingerprint"]
    assert before != after


def test_revise_preserves_identity_history_and_rejects_old_acceptance(proposal_session):
    from copy import deepcopy

    from app.coach_v2_models import CoachProposalRevision
    from app.services.proposals.lifecycle import RevisionRequest, revise_proposal

    session = proposal_session
    snapshot, uid = _snapshot(session)
    raw = _doc(snapshot, uid)
    initial = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    state = session.get(AppState, 1)
    baseline = (state.calendar_head_version, state.data_revision)
    fingerprint = collect_decision_inputs(session, snapshot.operation, TODAY, now=NOW, kb=KB)["source_fingerprint"]
    edited = deepcopy(raw)
    edited["changes"][0]["after"]["planned_duration_s"] = 2100
    edited["changes"][0]["reason"] = "Use the shorter duration requested by the athlete"
    edited["summary"] = "Shorten the planned run"
    request = RevisionRequest(expected_revision=1, reason="Shorter run requested", document=edited)
    result = revise_proposal(session, initial.proposal_id, request, now=NOW, resolve_kb=_resolve)
    assert result.proposal_id == initial.proposal_id and result.revision == 2
    assert revise_proposal(session, initial.proposal_id, request, now=NOW, resolve_kb=_resolve) == result
    assert submit_proposal(session, raw, now=NOW, resolve_kb=_resolve).proposal_id == result.proposal_id
    assert session.scalar(select(func.count()).select_from(CoachProposal)) == 1
    history = session.scalars(select(CoachProposalRevision).order_by(CoachProposalRevision.revision)).all()
    assert len(history) == 2
    assert history[0].payload["changes"][0]["after"]["planned_duration_s"] == 2400
    assert history[1].payload["changes"][0]["after"]["planned_duration_s"] == 2100
    assert history[1].changed_change_ids == ["c1"] and history[1].changed_fields == ["summary"]
    assert (
        collect_decision_inputs(session, snapshot.operation, TODAY, now=NOW, kb=KB)["source_fingerprint"] == fingerprint
    )
    session.refresh(state)
    assert (state.calendar_head_version, state.data_revision) == baseline
    with pytest.raises(DecisionError) as conflict:
        decide_proposal(session, result.proposal_id, _req(1, "old-review-key", ["c1"]), now=NOW, resolve_kb=_resolve)
    assert conflict.value.code == "proposal_revision_conflict"
    accepted = decide_proposal(
        session,
        result.proposal_id,
        _req(1, "new-review-key", ["c1"]).model_copy(update={"expected_revision": 2}),
        now=NOW,
        resolve_kb=_resolve,
    )
    assert accepted.status == "accepted"
    assert next(row for row in calendar.state_at(session, 2) if row["session_uid"] == uid)["planned_duration_s"] == 2100
    with pytest.raises(DecisionError) as decided:
        revise_proposal(session, result.proposal_id, request, now=NOW, resolve_kb=_resolve)
    assert decided.value.code == "proposal_decided"


def test_invalid_or_conflicting_revision_does_not_replace_draft(proposal_session):
    from copy import deepcopy

    from app.coach_v2_models import CoachProposalRevision
    from app.services.proposals.lifecycle import RevisionRequest, revise_proposal

    session = proposal_session
    snapshot, uid = _snapshot(session)
    raw = _doc(snapshot, uid)
    initial = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    invalid = deepcopy(raw)
    invalid["changes"][0]["after"]["local_date"] = "2027-01-01"
    for document, expected, code in [(invalid, 1, "invalid_proposal"), (raw, 9, "proposal_revision_conflict")]:
        with pytest.raises(DecisionError) as caught:
            revise_proposal(
                session,
                initial.proposal_id,
                RevisionRequest(expected_revision=expected, reason="Attempted edit", document=document),
                now=NOW,
                resolve_kb=_resolve,
            )
        assert caught.value.code == code
    row = session.get(CoachProposal, initial.proposal_id)
    assert row.revision == 1 and row.payload["changes"][0]["after"] == {"planned_duration_s": 2400}
    assert session.scalar(select(func.count()).select_from(CoachProposalRevision)) == 1
    same = revise_proposal(
        session,
        initial.proposal_id,
        RevisionRequest(expected_revision=1, reason="No actual change", document=raw),
        now=NOW,
        resolve_kb=_resolve,
    )
    assert same.revision == 1


def test_revise_stale_draft_requires_fresh_context_and_keeps_link(proposal_session):
    from app.services.proposals.lifecycle import RevisionRequest, revise_proposal

    session = proposal_session
    snapshot, uid = _snapshot(session)
    raw = _doc(snapshot, uid)
    initial = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    calendar.apply_edits(
        session, 1, [{"op": "modify", "session_uid": uid, "fields": {"intent": "Updated schedule"}}], "User edit"
    )
    with pytest.raises(DecisionError) as caught:
        revise_proposal(
            session,
            initial.proposal_id,
            RevisionRequest(expected_revision=1, reason="Refresh", document=raw),
            now=NOW,
            resolve_kb=_resolve,
        )
    assert caught.value.code == "stale_evidence"
    fresh, uid = _snapshot(session)
    result = revise_proposal(
        session,
        initial.proposal_id,
        RevisionRequest(expected_revision=1, reason="Use updated calendar", document=_doc(fresh, uid)),
        now=NOW,
        resolve_kb=_resolve,
    )
    assert result.proposal_id == initial.proposal_id and result.revision == 2 and result.status == "pending"
    row = session.get(CoachProposal, initial.proposal_id)
    assert row.base_calendar_version == 2 and row.snapshot_id == fresh.id
    change = session.scalar(select(CoachProposalChange).where(CoachProposalChange.proposal_id == row.id))
    assert change.before["intent"] == "Updated schedule"


def test_exception_accept_creates_patch_and_addresses_findings(proposal_session: Session) -> None:
    session = proposal_session
    patch, finding, proposal_id = _accepted_patch(session)
    assert session.scalar(select(func.count(ExceptionPatch.id)).where(ExceptionPatch.proposal_id == proposal_id)) == 1
    assert (patch.calendar_version_number, patch.status, patch.window_start, patch.window_end, patch.reassess_on) == (
        2,
        "open",
        date(2026, 11, 16),
        date(2026, 11, 18),
        date(2026, 11, 19),
    )
    assert patch.monitor == ["Morning fatigue"]
    assert (finding.status, finding.patch_id, finding.version) == ("addressed", patch.id, 2)


def test_exception_no_change_accept_reviews_findings(proposal_session: Session) -> None:
    session = proposal_session
    finding = _finding(session)
    snapshot, uid = _snapshot(session, "exception_review")
    raw = _exception_doc(snapshot, uid, [finding.id], changes=False, ladder="next_days")
    submitted = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    assert submitted.status == "pending", submitted.issues
    result = decide_proposal(session, submitted.proposal_id, _req(1, "exc-nochange"), now=NOW, resolve_kb=_resolve)
    assert (result.status, result.calendar_version) == ("accepted", None)
    assert session.scalar(select(func.count(ExceptionPatch.id))) == 0
    assert (finding.status, finding.reviewed_by_proposal_id, finding.closed_at) == (
        "reviewed",
        submitted.proposal_id,
        NOW,
    )


def test_exception_reject_has_no_effects(proposal_session: Session) -> None:
    session = proposal_session
    finding = _finding(session)
    snapshot, uid = _snapshot(session, "exception_review")
    raw = _exception_doc(snapshot, uid, [finding.id], ladder="current_session")
    submitted = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    assert submitted.status == "pending", submitted.issues
    result = decide_proposal(
        session, submitted.proposal_id, _req(1, "exc-reject", [], ["c1"]), now=NOW, resolve_kb=_resolve
    )
    assert result.status == "rejected"
    assert session.scalar(select(func.count(ExceptionPatch.id))) == 0
    assert (finding.status, finding.version) == ("open", 1)


def test_rolling_accept_resolves_patch_and_reviews_old_open_findings(proposal_session: Session) -> None:
    session = proposal_session
    patch, addressed, _ = _accepted_patch(session)
    old = _finding(session, "FATIGUE_HIGH", severity="observe", entity_key="fatigue")
    esc = _finding(
        session, "SYM_MULTIWEEK", category="symptoms_illness", severity="escalate", entity_key="site:ankle|left"
    )
    late = _finding(
        session,
        "TRAVEL_REPORTED",
        category="calendar_disruption",
        severity="observe",
        entity_key="travel",
        evidence_at=NOW - timedelta(minutes=30),
    )
    snapshot, uid = _snapshot(session)
    raw = _doc(snapshot, uid)
    raw["patch_resolutions"] = [{"patch_id": str(patch.id), "status": "resolved", "note": "Settled"}]
    submitted = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    assert submitted.status == "pending", submitted.issues
    decide_proposal(session, submitted.proposal_id, _req(2, "roll-accept", ["c1"]), now=NOW, resolve_kb=_resolve)
    assert (patch.status, patch.resolved_by, patch.resolution_note, patch.resolved_at) == (
        "resolved",
        "coach",
        "Settled",
        NOW,
    )
    assert addressed.status == "resolved"
    assert old.status == "reviewed"
    assert (esc.status, late.status) == ("open", "open")


def test_block_accept_reviews_all_and_supersedes_patches(proposal_session: Session) -> None:
    session = proposal_session
    patch, addressed, _ = _accepted_patch(session)
    observe = _finding(session, "FATIGUE_HIGH", severity="observe", entity_key="fatigue")
    escalate = _finding(
        session, "SYM_MULTIWEEK", category="symptoms_illness", severity="escalate", entity_key="site:ankle|left"
    )
    snapshot, uid = _snapshot(session, "review_training_block")
    raw = _doc(snapshot, uid)
    raw["changes"] = []
    submitted = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    assert submitted.status == "pending", submitted.issues
    result = decide_proposal(session, submitted.proposal_id, _req(2, "block-accept"), now=NOW, resolve_kb=_resolve)
    assert result.status == "accepted"
    assert [row.status for row in (addressed, observe, escalate)] == ["reviewed", "reviewed", "reviewed"]
    assert (patch.status, patch.resolved_by) == ("superseded", "coach")


def test_post_event_accept_reviews_only_that_event(proposal_session: Session) -> None:
    session = proposal_session
    first = Event(
        name="Synthetic 10K",
        event_date=TODAY - timedelta(days=2),
        distance_m=10000,
        purpose="pr",
        status="completed",
    )
    second = Event(
        name="Synthetic 5K",
        event_date=TODAY - timedelta(days=3),
        distance_m=5000,
        purpose="pr",
        status="completed",
    )
    session.add_all([first, second])
    session.flush()
    due = [
        _finding(
            session, "POST_EVENT_REVIEW_DUE", category="post_event", severity="observe", entity_key=f"event:{event.id}"
        )
        for event in (first, second)
    ]
    snapshot, uid = _snapshot(session, "post_event_review")
    raw = _doc(snapshot, uid)
    raw["changes"] = []
    raw["event_review"] = {
        "event_id": str(first.id),
        "activity_id": None,
        "pacing": "Even",
        "effort_and_limiter": "RPE 9, breathing",
        "conditions": None,
        "symptoms": None,
        "recovery_observation": "Normal walking",
        "recalibration": "defer",
        "training_implication": "Easy until fresh",
    }
    submitted = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    assert submitted.status == "pending", submitted.issues
    result = decide_proposal(session, submitted.proposal_id, _req(1, "post-accept"), now=NOW, resolve_kb=_resolve)
    assert result.status == "accepted"
    assert (due[0].status, due[1].status) == ("reviewed", "open")


def test_block_review_accept_upserts_benchmark_row(proposal_session: Session, monkeypatch) -> None:
    from app.services import block_benchmark

    session = proposal_session
    snapshot, uid = _snapshot(session, "review_training_block")
    fields = {
        "status": "active",
        "objective": "Build",
        "rationale": "Ready",
        "maintained_qualities": [],
        "non_goals": [],
        "eligible_recipe_ids": ["REC001", "REC009"],
        "progression_dimension": "duration",
        "constraints": [],
        "start_date": "2026-11-16",
        "review_date": "2026-12-28",
        "completion_indicators": [],
        "early_review_triggers": [],
        "objective_status": "unresolved",
        "benchmark": {
            "kind": "time_trial",
            "protocol": "5 km solo time trial",
            "planned_date": "2026-12-20",
            "progress_if": "Under 22:00",
            "consolidate_if": "Over 22:30",
        },
    }
    raw = _doc(snapshot, uid)
    raw["changes"] = []
    raw["block_change"] = {"decision": "start", "block_uid": None, "version_fields": fields}
    first = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    assert first.status == "pending", first.issues
    started = decide_proposal(
        session,
        first.proposal_id,
        DecisionRequest(
            idempotency_key="bench-block-start",
            expected_head=1,
            expected_revision=1,
            accept_change_ids=[],
            reject_change_ids=[],
            accept_block_change=True,
        ),
        now=NOW,
        resolve_kb=_resolve,
    )
    block = session.get(BlockVersion, started.block_version_id)
    assert block is not None
    event = Event(
        name="Benchmark 5K",
        event_date=TODAY - timedelta(days=1),
        distance_m=5000,
        purpose="benchmark",
        status="completed",
    )
    session.add(event)
    session.flush()
    monkeypatch.setattr(
        block_benchmark,
        "benchmark_status",
        lambda session, version, today: block_benchmark.BenchmarkStatus(
            status="completed",
            match_method="auto",
            activity_id=None,
            event_id=event.id,
            local_date=TODAY - timedelta(days=1),
            distance_m=5000,
            result_s=1300,
            rpe=9.0,
            scheduled_date=None,
            evidence_at=NOW,
        ),
    )
    review = {
        "event_id": str(event.id),
        "outcome": "progress",
        "compared_with": "Prior 5K 22:10",
        "pacing": "Even",
        "effort_and_limiter": "RPE 9",
        "recovery_observation": "Normal",
        "recalibration": "defer",
        "training_implication": "Progress",
    }
    for key in ("bench-review-1", "bench-review-2"):
        snapshot, uid = _snapshot(session, "review_training_block")
        raw = _doc(snapshot, uid)
        raw["changes"] = []
        raw["event_review"] = review
        submitted = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
        assert submitted.status == "pending", submitted.issues
        decide_proposal(session, submitted.proposal_id, _req(1, key), now=NOW, resolve_kb=_resolve)
        rows = session.scalars(
            select(BlockBenchmarkResult).where(BlockBenchmarkResult.block_uid == block.block_uid)
        ).all()
        assert len(rows) == 1
        row = rows[0]
        assert (
            row.block_version,
            row.match_method,
            row.event_id,
            row.distance_m,
            row.result_s,
            row.outcome,
            row.compared_with,
            row.proposal_id,
            row.protocol,
        ) == (
            1,
            "auto",
            event.id,
            5000,
            1300,
            "progress",
            "Prior 5K 22:10",
            submitted.proposal_id,
            "5 km solo time trial",
        )


def test_block_review_can_design_future_runs_from_verified_recipes(proposal_session):
    session = proposal_session
    benchmark = session.scalars(select(CalendarSessionRevision).filter_by(kind="run")).one()
    benchmark.recipe_id = "REC009"
    benchmark.intent = "Time trial"
    benchmark.local_date = date(2026, 11, 24)
    for day, intent in [(19, "Easy aerobic"), (22, "Tempo")]:
        session.add(
            CalendarSessionRevision(
                session_uid=uuid.uuid4(),
                revision=1,
                calendar_version_number=1,
                local_date=date(2026, 11, day),
                kind="run",
                custom=True,
                structure=[{"type": "work", "duration_type": "time", "duration_value": 1800}],
                planned_duration_s=1800,
                intent=intent,
                certainty="committed",
            )
        )
    session.flush()
    result = build_snapshot(session, "review_training_block", TODAY, now=NOW)
    recipes = {e["record_id"] for e in result["kb"]["excerpts"] if e.get("record_id", "").startswith("REC")}
    assert {"REC001", "REC002", "REC003", "REC009"} <= recipes

    snapshot = session.get(CoachSnapshot, uuid.UUID(result["snapshot_id"]))
    raw = _doc(snapshot, benchmark.session_uid)
    fields = _block_fields("2026-12-06", "2026-11-24")
    fields["eligible_recipe_ids"] = ["REC001", "REC002", "REC003", "REC009"]
    raw.update(
        block_change={"decision": "start", "block_uid": None, "version_fields": fields},
        policy_ids=[],
        evidence_ids=[],
        recipe_ids=fields["eligible_recipe_ids"],
        changes=_strength_adds("2026-12-01", "2026-12-04"),
    )
    runs = [
        ("easy", "2026-11-30", "REC001", 1800),
        ("quality", "2026-12-02", "REC003", 2400),
        ("long", "2026-12-06", "REC002", 3600),
    ]
    for i, (intent, day, recipe, duration) in enumerate(runs, start=3):
        raw["changes"].append(
            {
                "change_id": f"c{i}",
                "op": "add",
                "reason": "Plan the block",
                "after": {
                    "local_date": day,
                    "kind": "run",
                    "intent": intent,
                    "recipe_id": recipe,
                    "planned_duration_s": duration,
                    "structure": None,
                },
            }
        )
    proposal = submit_proposal(session, raw, now=NOW, resolve_kb=resolve_kb)
    assert proposal.status == "pending", [(issue.code, issue.path) for issue in proposal.issues]
    assert session.get(AppState, 1).calendar_head_version == 1
    assert session.scalar(select(BlockVersion.id)) is None

    accepted = decide_proposal(
        session,
        proposal.proposal_id,
        _block_req("accept-verified-runs", [c["change_id"] for c in raw["changes"]], [], block=True),
        now=NOW,
        resolve_kb=resolve_kb,
    )
    assert accepted.status == "accepted"
    rows = {r["local_date"]: r for r in calendar.state_at(session, accepted.calendar_version) if r["kind"] == "run"}
    for intent, day, recipe, duration in runs:
        row = rows[date.fromisoformat(day)]
        assert row["recipe_id"] == recipe and classify(row["kind"], row["recipe_id"], row["intent"]) == intent
        assert row["structure"] is None and row["certainty"] == "provisional"
        assert row["planned_duration_s"] == duration


def test_block_review_accepts_sessions_through_review_date(proposal_session):
    session = proposal_session
    days = ("2026-12-08", "2026-12-11")
    prop = _block_review(session, "2026-12-14", "2026-12-05", days)
    result = _decide_block(session, prop, "accept-horizon", ["c1", "c2"], [], block=True)
    assert result.status == "accepted" and result.calendar_version == 2
    assert session.get(BlockVersion, result.block_version_id).review_date == date(2026, 12, 14)
    dates = session.scalars(select(CalendarSessionRevision.local_date)).all()
    assert {date.fromisoformat(day) for day in days}.issubset(dates)


def test_rolling_change_on_day_twenty_is_accepted(proposal_session):
    session = proposal_session
    prop = _block_review(session, "2026-12-14", "2026-12-05", ())
    _decide_block(session, prop, "start-horizon", [], [], block=True)
    snapshot, uid = _snapshot(session)
    raw = _doc(snapshot, uid)
    raw["changes"] = _strength_adds("2026-12-02", "2026-12-06")
    prop = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    assert prop.status == "pending"
    assert _decide_block(session, prop, "roll-horizon", ["c1", "c2"], [], block=False).status == "accepted"


def test_rejected_block_change_keeps_later_session_out_of_scope(proposal_session):
    session = proposal_session
    prop = _block_review(session, "2026-12-14", "2026-12-05", ("2026-12-08", "2026-12-11"))
    with pytest.raises(DecisionError) as caught:
        _decide_block(session, prop, "reject-horizon", ["c1", "c2"], [], block=False)
    assert caught.value.code == "proposal_invalid_subset"
    assert ("V5.out_of_scope", "changes.0") in [(i.code, i.path) for i in caught.value.fields]


def test_empty_week_four_is_accepted_after_partial_rejection(proposal_session):
    session = proposal_session
    prop = _block_review(session, "2026-12-14", "2026-12-05", ("2026-12-08", "2026-12-11"))
    result = _decide_block(session, prop, "empty-horizon", [], ["c1", "c2"], block=True)
    assert result.status == "partially_accepted"
    assert session.get(BlockVersion, result.block_version_id).review_date == date(2026, 12, 14)


def test_block_handoff_plans_past_the_old_review_date(proposal_session):
    session = proposal_session
    first = _block_review(session, "2026-11-23", "2026-11-16", ())
    result = _decide_block(session, first, "handoff-start", [], [], block=True)
    block = session.get(BlockVersion, result.block_version_id)
    snapshot, uid = _snapshot(session, "review_training_block")
    raw = _doc(snapshot, uid)
    raw["changes"] = _strength_adds("2026-12-01", "2026-12-03", "2026-12-08", "2026-12-10")
    raw["block_change"] = {
        "decision": "transition",
        "block_uid": str(block.block_uid),
        "version_fields": {
            **_block_fields("2026-12-22", "2026-12-12"),
            "start_date": "2026-11-24",
            "objective": "Next block",
        },
    }
    prop = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    assert prop.status == "pending"
    result = _decide_block(session, prop, "handoff-accept", ["c1", "c2", "c3", "c4"], [], block=True)
    assert result.status == "accepted" and result.calendar_version == 2
    versions = session.scalars(
        select(BlockVersion).where(BlockVersion.block_uid == block.block_uid).order_by(BlockVersion.version)
    ).all()
    assert len(versions) == 2 and versions[-1].version == 2
    assert versions[-1].start_date == date(2026, 11, 24)
    assert date(2026, 12, 10) in session.scalars(select(CalendarSessionRevision.local_date)).all()


def test_block_may_skip_benchmark_after_recent_credible_result(proposal_session):
    session = proposal_session
    old, other = uuid.uuid4(), uuid.uuid4()
    session.add_all([Block(block_uid=old), Block(block_uid=other)])
    session.flush()
    session.add_all(
        [
            BlockBenchmarkResult(
                block_uid=old,
                block_version=1,
                match_method="manual",
                protocol="5 km solo time trial",
                local_date=date(2026, 10, 20),
                outcome="progress",
            ),
            BlockBenchmarkResult(
                block_uid=other,
                block_version=1,
                match_method="manual",
                protocol="5 km solo time trial",
                local_date=date(2026, 11, 14),
                outcome="inconclusive",
            ),
        ]
    )
    session.flush()
    snapshot, uid = _snapshot(session, "review_training_block")
    assert load_context(session, snapshot.id, now=NOW, kb=KB).last_benchmark_date == date(2026, 10, 20)
    raw = _doc(snapshot, uid)
    raw["changes"] = []
    raw["block_change"] = {
        "decision": "start",
        "block_uid": None,
        "version_fields": {
            **_block_fields("2026-12-06", "2026-11-23"),
            "benchmark": None,
            "completion_indicators": ["Quality reps hold at RPE 7 or lower"],
        },
    }
    proposal = submit_proposal(session, raw, now=NOW, resolve_kb=_resolve)
    assert proposal.status == "pending", [(i.code, i.path) for i in proposal.issues]
    result = decide_proposal(
        session, proposal.proposal_id, _block_req("cadence-accept", [], [], block=True), now=NOW, resolve_kb=_resolve
    )
    assert result.status == "accepted"
    assert session.get(BlockVersion, result.block_version_id).benchmark is None


def test_block_review_stores_target_and_outline(proposal_session: Session) -> None:
    session = proposal_session
    goal = _goal_event(session, date(2027, 3, 14))
    proposal = _target_review(session, target=goal, outline=OUTLINE)
    assert proposal.status == "pending", _issues(proposal)
    block = _accept_block(session, proposal, "rg-start")
    assert block.target_event_id == goal.id and block.build_outline == OUTLINE


def test_continue_adds_the_target_to_an_untargeted_block(proposal_session: Session) -> None:
    session = proposal_session
    started = _accept_block(session, _target_review(session), "rg-first")
    assert started.target_event_id is None and started.build_outline == []
    goal = _goal_event(session, date(2027, 3, 14))
    proposal = _target_review(session, decision="continue", block_uid=started.block_uid, target=goal, outline=OUTLINE)
    assert proposal.status == "pending", _issues(proposal)
    continued = _accept_block(session, proposal, "rg-continue")
    assert continued.version == 2 and continued.target_event_id == goal.id and continued.build_outline == OUTLINE


def test_goal_race_on_the_block_start_day_needs_an_empty_outline(proposal_session: Session) -> None:
    session = proposal_session
    goal = _goal_event(session, TODAY)
    invalid = _target_review(session, target=goal, outline=OUTLINE)
    assert invalid.status == "invalid"
    assert ("V23.build_outline_span", "block_change.version_fields.build_outline") in _issues(invalid)
    discard_proposal(session, invalid.proposal_id, invalid.revision, now=NOW)
    proposal = _target_review(session, target=goal, outline=[])
    assert proposal.status == "pending", _issues(proposal)
    assert _accept_block(session, proposal, "rg-race-day").target_event_id == goal.id


def test_cancelled_goal_race_invalidates_a_block_that_targets_it(proposal_session: Session) -> None:
    session = proposal_session
    goal = _goal_event(session, date(2027, 3, 14))
    started = _accept_block(session, _target_review(session, target=goal, outline=OUTLINE), "rg-before")
    goal.status = "cancelled"
    session.flush()
    proposal = _target_review(session, decision="continue", block_uid=started.block_uid, target=goal, outline=OUTLINE)
    assert proposal.status == "invalid"
    assert ("V23.target_event_invalid", "block_change.version_fields.target_event_id") in _issues(proposal)


def test_block_starting_after_its_goal_race_is_invalid(proposal_session: Session) -> None:
    session = proposal_session
    goal = _goal_event(session, date(2026, 12, 20))
    proposal = _target_review(
        session,
        target=goal,
        start_date="2026-12-21",
        review_date="2027-01-11",
        benchmark=_block_fields("2027-01-11", "2027-01-02")["benchmark"],
    )
    assert proposal.status == "invalid"
    assert _issues(proposal) == [("V23.target_event_date", "block_change.version_fields.target_event_id")]


def test_consolidating_block_must_still_target_the_goal_race(proposal_session: Session) -> None:
    session = proposal_session
    goal = _goal_event(session, date(2027, 3, 14))
    started = _accept_block(session, _target_review(session, target=goal, outline=OUTLINE), "rg-consolidate-start")
    block_fields = {
        "decision": "consolidate",
        "block_uid": started.block_uid,
        "status": "consolidating",
        "outline": OUTLINE,
    }
    invalid = _target_review(session, **block_fields)
    assert invalid.status == "invalid"
    assert ("V23.target_event_required", "block_change.version_fields.target_event_id") in _issues(invalid)
    discard_proposal(session, invalid.proposal_id, invalid.revision, now=NOW)
    proposal = _target_review(session, target=goal, **block_fields)
    assert proposal.status == "pending", _issues(proposal)
    block = _accept_block(session, proposal, "rg-consolidate")
    assert block.status == "consolidating" and block.target_event_id == goal.id
