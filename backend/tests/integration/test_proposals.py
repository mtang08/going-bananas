"""Proposal persistence and lineage on the guarded synthetic database."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.coach_v2_models import CoachDecisionKey, CoachProposal, CoachProposalChange, CoachSnapshot
from app.config import settings
from app.db import engine
from app.metrics.engine import install_triggers
from app.models import AppState, ProfileVersion
from app.models import Checkin as LegacyCheckin
from app.planning_models import Block, BlockDecision, BlockVersion, IntensityAnchor
from app.services import calendar
from app.services.decision_inputs import VerifiedKnowledge, collect_decision_inputs
from app.services.proposals import DecisionError, DecisionRequest, decide_proposal, submit_proposal

NOW = datetime(2026, 11, 16, 15, tzinfo=UTC)
TODAY = date(2026, 11, 16)
KB = VerifiedKnowledge("0" * 64, (), (), frozenset({"P001"}), frozenset({"REC001"}), frozenset({"E-AER-01"}))


def _resolve(selection: tuple[dict, ...]) -> VerifiedKnowledge:
    assert selection == ()
    return KB


@pytest.fixture
def proposal_session(monkeypatch):
    parsed = urlsplit(settings.database_url)
    assert settings.app_mode == "test"
    assert parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == 55439
    assert parsed.path == "/garmin_test"
    monkeypatch.setattr(calendar, "_today", lambda session, now=None: TODAY)
    install_triggers()
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                session.info["metrics_now"] = NOW
                session.execute(delete(CoachDecisionKey))
                session.execute(delete(CoachProposalChange))
                session.execute(delete(CoachProposal))
                session.execute(delete(CoachSnapshot))
                session.execute(delete(SessionCompletion))
                session.execute(delete(CalendarSessionRevision))
                session.execute(delete(CalendarVersion))
                session.execute(delete(BlockDecision))
                session.execute(delete(BlockVersion))
                session.execute(delete(Block))
                session.execute(delete(IntensityAnchor))
                state = session.get(AppState, 1, with_for_update=True)
                state.calendar_head_version = 0
                state.planning_authority = "calendar"
                version = (session.scalar(select(func.max(ProfileVersion.version))) or 0) + 1
                session.add(
                    ProfileVersion(
                        version=version,
                        effective_at=NOW - timedelta(days=1),
                        timezone="America/New_York",
                        cycle_anchor=TODAY,
                        anchor_confirmed=True,
                        strength_days_confirmed=True,
                        scheduled_strength_days=[0, 4],
                        strength_schedule_mode="weekly",
                        facts={},
                        preferences={},
                        unknowns=[],
                    )
                )
                session.flush()
                edits = [
                    {
                        "op": "add",
                        "fields": {
                            "local_date": date(2026, 11, day),
                            "kind": kind,
                            "intent": "Train",
                            **({"recipe_id": "REC001", "planned_duration_s": 1800} if kind == "run" else {}),
                        },
                    }
                    for day, kind in [
                        (16, "strength"),
                        (20, "strength"),
                        (23, "strength"),
                        (27, "strength"),
                        (18, "run"),
                    ]
                ]
                calendar.apply_edits(session, 0, edits, "Fixture")
                session.commit()
                yield session
        finally:
            outer.rollback()


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


def _req(head: int, key: str, accepted: list[str] | None = None, rejected: list[str] | None = None) -> DecisionRequest:
    return DecisionRequest(
        idempotency_key=key, expected_head=head, accept_change_ids=accepted or [], reject_change_ids=rejected or []
    )


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
    ("symptoms", "change", "gait"),
    [("none", None, "affected"), ("severe", None, "normal"), ("moderate", "worse", "normal")],
)
def test_legacy_categorical_safety_without_numeric_severity(
    proposal_session: Session, symptoms: str, change: str | None, gait: str
) -> None:
    session = proposal_session
    row = LegacyCheckin(
        idempotency_key=f"legacy-{uuid.uuid4()}",
        observed_at=NOW - timedelta(hours=1),
        symptoms=symptoms,
        change=change,
        gait=gait,
        feeling="okay",
        effort=None,
    )
    session.add(row)
    session.flush()
    result = collect_decision_inputs(session, "review_rolling_plan", TODAY, now=NOW, kb=KB)
    assert result["safety_guard"]["legacy_safety_active"] is True
    assert result["source_versions"]["legacy_checkins"][-1]["severity_numeric"] is None
    assert "note" not in result["source_versions"]["legacy_checkins"][-1]


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
    second = submit_proposal(session, other, now=NOW, resolve_kb=_resolve)
    assert first.status == second.status == "pending"
    result = decide_proposal(
        session,
        first.proposal_id,
        DecisionRequest(
            idempotency_key="decision-anchor",
            expected_head=1,
            accept_change_ids=[],
            reject_change_ids=[],
            accept_anchor_changes=["hr_threshold_lower-2026-11-16"],
        ),
        now=NOW,
        resolve_kb=_resolve,
    )
    assert result.status == "accepted" and result.calendar_version is None
    assert result.anchor_keys == ["hr_threshold_lower-2026-11-16"]
    assert second.proposal_id in result.stale_proposals
    stored = session.get(CoachProposal, second.proposal_id)
    assert stored is not None and stored.status == "stale"
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
        "eligible_recipe_ids": ["REC001"],
        "progression_dimension": "duration",
        "constraints": [],
        "start_date": "2026-11-16",
        "review_date": "2026-12-28",
        "completion_indicators": [],
        "early_review_triggers": [],
        "objective_status": "unresolved",
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
    second = submit_proposal(session, {**raw, "summary": "Other choice"}, now=NOW, resolve_kb=_resolve)
    rejected = decide_proposal(
        session, first.proposal_id, _req(1, "shared-decision-key", [], ["c1"]), now=NOW, resolve_kb=_resolve
    )
    assert rejected.status == "rejected" and rejected.calendar_version is None
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


def test_legacy_window_boundary_and_mild_v2_does_not_erase_guard(proposal_session: Session) -> None:
    from app.checkin_models import Checkin as CheckinV2

    session = proposal_session
    row = LegacyCheckin(
        idempotency_key=f"legacy-{uuid.uuid4()}",
        observed_at=NOW - timedelta(hours=72),
        symptoms="moderate",
        change="worse",
        gait="normal",
        feeling="okay",
    )
    session.add(row)
    mild = CheckinV2(
        idempotency_key=f"mild-{uuid.uuid4()}",
        version=1,
        kind="exception",
        observed_at=NOW - timedelta(minutes=1),
        fatigue=1,
        illness="none",
        gait_change="no",
        context_tags=[],
    )
    session.add(mild)
    session.flush()
    included = collect_decision_inputs(session, "review_rolling_plan", TODAY, now=NOW, kb=KB)
    assert included["safety_guard"]["legacy_safety_active"] is True
    assert included["safety_guard"]["max_symptom_severity"] is None
    assert any(item["id"] == str(row.id) for item in included["source_versions"]["legacy_checkins"])
    row.observed_at = NOW - timedelta(hours=72, microseconds=1)
    session.flush()
    excluded = collect_decision_inputs(session, "review_rolling_plan", TODAY, now=NOW, kb=KB)
    assert excluded["safety_guard"]["legacy_safety_active"] is False
    assert all(item["id"] != str(row.id) for item in excluded["source_versions"]["legacy_checkins"])
    row.observed_at = NOW + timedelta(microseconds=1)
    session.flush()
    future = collect_decision_inputs(session, "review_rolling_plan", TODAY, now=NOW, kb=KB)
    assert future["safety_guard"]["legacy_safety_active"] is False


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
    from app.services.proposals import _active_block

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
    assert _active_block(session) is None


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
