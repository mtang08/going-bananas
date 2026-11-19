"""Bounded, source-aware coach snapshot projections."""

from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.calendar_models import SessionCompletion
from app.checkin_models import Checkin as CheckinV2
from app.checkin_models import SessionRpe, SymptomReport
from app.coach_v2_models import CoachProposal, CoachProposalChange, CoachSnapshot
from app.db import global_write_lock
from app.domain.athlete_facts import clinical_restriction
from app.domain.local_time import date_in_zone
from app.metric_models import MetricResult, Prompt
from app.models import Activity, AppState
from app.planning_models import (
    BlockBenchmarkResult,
    BlockDecision,
    BlockVersion,
    Event,
    Goal,
    IntensityAnchor,
    StrengthRoutineSlot,
)
from app.read.calendar import head_version
from app.services.block_benchmark import active_block_version
from app.services.calendar import state_at
from app.services.coverage import coverage
from app.services.decision_inputs import VerifiedKnowledge, canonical_json, collect_decision_inputs
from app.services.exceptions.vocab import NON_TERMINAL_FINDING
from app.services.knowledge import load_route, verify_selection
from app.services.profile import current_profile
from app.services.proposals.schema import derive_certainty
from app.services.run_rpe import effective_run_rpe
from app.services.snapshot.common import (
    BENCHMARK_HISTORY_MAX,
    BLOCK,
    DAILY,
    EXCEPTION,
    LIVE_PATCH,
    MISSING,
    POST_EVENT,
    QUALITY_OP,
    ROLLING,
    SUMMARY_DAYS,
    SnapshotInputs,
    row_view,
    source_provenance,
)
from app.services.snapshot.payload import build_payload
from app.services.snapshot.topics import select_conditional_topics, select_recipe_ids
from app.services.timezone import athlete_tz
from app.services.weekly_digest import load_week, week_bounds
from app.strong_models import StrongWorkoutRow


def _effective_rpe(rpe_rows: Sequence[SessionRpe], strong_id: Any) -> Any:
    matched = [r for r in rpe_rows if r.strong_workout_id == strong_id]
    preferred = next((r for r in reversed(matched) if r.source == "manual"), None) or next(
        (r for r in reversed(matched) if r.source == "garmin_fit"), None
    )
    return preferred.rpe if preferred else None


def _load_sessions(session: Session, head: int, first: date, as_of: date) -> list[dict]:
    sessions = [
        dict(
            row_view(
                row,
                (
                    "session_uid",
                    "revision",
                    "local_date",
                    "slot",
                    "kind",
                    "recipe_id",
                    "custom",
                    "placeholder",
                    "intent",
                    "certainty",
                    "planned_duration_s",
                    "planned_distance_m",
                    "structure",
                    "strength_slot_id",
                ),
            ),
            certainty=derive_certainty(row["local_date"], as_of),
        )
        for row in state_at(session, head)
        if first <= row["local_date"] <= as_of + timedelta(days=13)
    ]
    return sessions


def _load_completions(session: Session) -> list[dict]:
    completion_rows = session.scalars(select(SessionCompletion)).all()
    completions = [
        row_view(row, ("session_uid", "status", "activity_id", "strong_workout_id", "manual_session_id", "modification_reason"))
        for row in completion_rows
    ]
    return completions


def _load_strength_slots(session: Session) -> list[dict]:
    slots = [
        row_view(
            row,
            ("id", "label", "default_weekday", "lower_body_cost", "typical_duration_s", "main_lower_body_lifts"),
            names={"id": "slot_id"},
        )
        for row in session.scalars(
            select(StrengthRoutineSlot)
            .where(StrengthRoutineSlot.active.is_(True))
            .order_by(StrengthRoutineSlot.default_weekday, StrengthRoutineSlot.id)
        )
    ]
    return slots


def _load_strong_workouts(strong_rows: Sequence[StrongWorkoutRow], rpe_rows: Sequence[SessionRpe]) -> list[dict]:
    strong = [
        dict(
            row_view(row, ("local_date", "workout_name", "duration_s")),
            strong_workout_id=row.id,
            rpe=_effective_rpe(rpe_rows, row.id),
        )
        for row in strong_rows
    ]
    return strong


def _load_runs(session: Session, first: date, as_of: date, rpe_rows: Sequence[SessionRpe]) -> list[dict]:
    from app.metrics.engine import load_runs

    run_facts = load_runs(session, first, as_of + timedelta(days=1))
    activities = (
        {
            row.id: row
            for row in session.scalars(select(Activity).where(Activity.id.in_([run.activity_id for run in run_facts])))
        }
        if run_facts
        else {}
    )
    rpe_by_activity: dict[Any, list[Any]] = {}
    for rpe_row in rpe_rows:
        if rpe_row.activity_id is not None:
            rpe_by_activity.setdefault(rpe_row.activity_id, []).append(rpe_row)
    run_rpe = {
        f.activity_id: effective_run_rpe(rpe_by_activity.get(f.activity_id, []), activities[f.activity_id].workout_rpe)
        for f in run_facts
    }
    runs = [
        dict(
            activity_id=f.activity_id,
            local_date=f.local_date,
            sport=f.sport,
            timer_s=f.timer_s,
            distance_m=f.distance_m,
            rpe=run_rpe[f.activity_id][0],
            rpe_source=run_rpe[f.activity_id][1],
            start_at=f.start_at,
        )
        for f in run_facts
    ]
    return runs


def _load_checkins(session: Session, now: datetime, zone: ZoneInfo) -> list[dict]:
    checkin_rows = session.scalars(
        select(CheckinV2)
        .where(CheckinV2.observed_at >= now - timedelta(days=120), CheckinV2.observed_at <= now)
        .order_by(CheckinV2.observed_at, CheckinV2.id)
    ).all()
    symptom_rows = (
        session.scalars(
            select(SymptomReport)
            .where(SymptomReport.checkin_id.in_([row.id for row in checkin_rows]))
            .order_by(SymptomReport.checkin_id, SymptomReport.id)
        ).all()
        if checkin_rows
        else []
    )
    symptoms: dict[uuid.UUID, list[dict]] = {}
    for row in symptom_rows:
        symptoms.setdefault(row.checkin_id, []).append(row_view(row, ("site", "side", "severity", "timing")))
    checkins = [
        dict(
            row_view(row, ("kind", "observed_at", "fatigue", "illness", "gait_change", "activity_id")),
            checkin_id=row.id,
            local_date=date_in_zone(row.observed_at, zone),
            symptoms=symptoms.get(row.id, []),
        )
        for row in checkin_rows
    ]
    return checkins


def _load_prompts(session: Session, now: datetime) -> list[dict]:
    prompt_rows = session.scalars(
        select(Prompt)
        .where(Prompt.opens_at >= now - timedelta(days=120), Prompt.opens_at <= now)
        .order_by(Prompt.opens_at, Prompt.id)
    ).all()
    prompts = [
        row_view(row, ("id", "kind", "activity_id", "status", "opens_at", "closes_at"), names={"id": "prompt_id"})
        for row in prompt_rows
    ]
    return prompts


def _load_metrics(session: Session, as_of: date, runs: list[dict]) -> list[dict]:
    from app.metrics.engine import current_result_filter

    metric_keys = (
        {f"w{n}:{as_of.isoformat()}" for n in (7, 14, 28, 56, 84)}
        | {f"w{n}:{as_of.isoformat()}:{kind}" for n in (7, 14, 28, 56, 84) for kind in ("run", "strength")}
        | {f"night:{(as_of - timedelta(days=n)).isoformat()}" for n in range(120)}
        | {str(row["activity_id"]) for row in runs}
    )
    metric_rows = session.scalars(
        select(MetricResult)
        .where(current_result_filter(), MetricResult.subject_key.in_(metric_keys))
        .order_by(MetricResult.metric_id, MetricResult.subject_key, MetricResult.id)
    ).all()
    metrics = [
        row_view(
            row,
            (
                "id",
                "metric_id",
                "method_version",
                "subject_type",
                "subject_key",
                "window_label",
                "status",
                "quality_status",
                "value",
                "unit",
                "reason_codes",
                "quality_flags",
                "anchor_keys",
                "calculated_at",
            ),
            names={"id": "result_id"},
        )
        for row in metric_rows
    ]
    return metrics


def _load_anchors(session: Session) -> list[dict]:
    anchor_rows = session.scalars(
        select(IntensityAnchor).order_by(
            IntensityAnchor.valid_from, IntensityAnchor.calibrated_at, IntensityAnchor.anchor_key
        )
    ).all()
    anchors = [
        row_view(
            row,
            (
                "anchor_key",
                "kind",
                "value_low",
                "value_high",
                "unit",
                "protocol",
                "confidence",
                "status",
                "calibrated_at",
                "valid_from",
                "review_after",
                "supersedes_key",
            ),
        )
        for row in anchor_rows
    ]
    return anchors


def _load_active_block(session: Session, as_of: date) -> tuple[Sequence[BlockVersion], dict | None]:
    block_rows = session.scalars(
        select(BlockVersion).order_by(BlockVersion.block_uid, BlockVersion.version.desc())
    ).all()
    active_row = active_block_version(session)
    block_keys = (
        "status",
        "objective",
        "rationale",
        "maintained_qualities",
        "non_goals",
        "eligible_recipe_ids",
        "progression_dimension",
        "constraints",
        "start_date",
        "review_date",
        "completion_indicators",
        "early_review_triggers",
        "objective_status",
        "benchmark",
    )
    from app.services.block_benchmark import benchmark_status, status_data

    active_block = (
        dict(
            row_view(active_row, block_keys),
            block_uid=active_row.block_uid,
            version_id=active_row.id,
            version=active_row.version,
            benchmark_status=status_data(benchmark_status(session, active_row, as_of)),
        )
        if active_row
        else None
    )
    return block_rows, active_block


def _load_block_decisions(session: Session) -> list[dict]:
    decisions = [
        row_view(
            row,
            (
                "decision",
                "from_version",
                "to_version",
                "rationale",
                "confidence",
                "decided_at",
                "proposal_id",
                "block_uid",
            ),
        )
        for row in session.scalars(select(BlockDecision).order_by(BlockDecision.decided_at, BlockDecision.id))
    ]
    return decisions


def _load_proposals(session: Session) -> list[dict]:
    proposal_rows = session.scalars(
        select(CoachProposal)
        .where(CoachProposal.status != "invalid")
        .order_by(CoachProposal.submitted_at.desc(), CoachProposal.id.desc())
        .limit(20)
    ).all()
    changes = (
        session.scalars(
            select(CoachProposalChange)
            .where(CoachProposalChange.proposal_id.in_([p.id for p in proposal_rows]))
            .order_by(CoachProposalChange.proposal_id, CoachProposalChange.change_id)
        ).all()
        if proposal_rows
        else []
    )
    by_proposal: dict[uuid.UUID, list[dict]] = {}
    for change_row in changes:
        by_proposal.setdefault(change_row.proposal_id, []).append(
            row_view(change_row, ("change_id", "op", "session_uid", "decision", "before", "after"))
        )
    proposals = [
        dict(
            row_view(row, ("operation", "status", "submitted_at", "decided_at", "summary", "follow_up")),
            proposal_id=row.id,
            changes=by_proposal.get(row.id, []),
        )
        for row in proposal_rows
    ]
    return proposals


def _load_goals(session: Session) -> list[dict]:
    goals = [
        row_view(row, ("id", "text", "horizon", "priority", "status"), names={"id": "goal_id"})
        for row in session.scalars(select(Goal).where(Goal.status == "active").order_by(Goal.priority, Goal.id))
    ]
    return goals


def _load_events(session: Session, as_of: date) -> list[dict]:
    events = [
        row_view(
            row, ("id", "name", "event_date", "distance_m", "priority", "status", "result_s"), names={"id": "event_id"}
        )
        for row in session.scalars(
            select(Event).where(Event.event_date >= as_of - timedelta(days=28)).order_by(Event.event_date, Event.id)
        )
    ]
    return events


def _load_exception_state(session: Session, as_of: date, now: datetime) -> tuple[list[dict], list[dict]]:
    from app.exception_models import ExceptionFinding, ExceptionPatch
    from app.services.exceptions.detector import finding_data, last_review_at, patch_data

    last_review = last_review_at(session)
    exception_findings = [finding_data(row, last_review) for row in session.scalars(
        select(ExceptionFinding)
        .where(or_(ExceptionFinding.status.in_(NON_TERMINAL_FINDING),
                   ExceptionFinding.first_seen_at >= now - timedelta(days=SUMMARY_DAYS)))
        .order_by(ExceptionFinding.first_seen_at.desc(), ExceptionFinding.id))]
    exception_patches = [patch_data(session, row, as_of) for row in session.scalars(
        select(ExceptionPatch)
        .where(or_(ExceptionPatch.status.in_(LIVE_PATCH),
                   ExceptionPatch.window_end >= as_of - timedelta(days=SUMMARY_DAYS - 1)))
        .order_by(ExceptionPatch.created_at.desc(), ExceptionPatch.id))]
    return exception_findings, exception_patches


def _load_benchmark_history(session: Session, block_rows: Sequence[BlockVersion]) -> list[dict]:
    versions = {(row.block_uid, row.version): row.objective for row in block_rows}
    benchmark_history = [
        {"block_uid": row.block_uid, "objective": versions.get((row.block_uid, row.block_version)),
         "protocol": row.protocol, "distance_m": row.distance_m, "local_date": row.local_date,
         "result_s": row.result_s, "outcome": row.outcome}
        for row in session.scalars(
            select(BlockBenchmarkResult)
            .where(BlockBenchmarkResult.outcome.is_not(None))
            .order_by(BlockBenchmarkResult.local_date.desc().nulls_last(), BlockBenchmarkResult.updated_at.desc())
            .limit(BENCHMARK_HISTORY_MAX)
        )
    ]
    return benchmark_history


def _load_review_recommended(session: Session, as_of: date) -> list[dict]:
    from app.services.exceptions.detector import review_recommended

    return [r.to_wire() for r in review_recommended(session, as_of)]


def load_inputs(session: Session, as_of: date, *, now: datetime) -> SnapshotInputs:
    zone = athlete_tz(session)
    state = session.get(AppState, 1)
    profile = current_profile(session)
    head = head_version(session)
    first = as_of - timedelta(days=120)
    sessions = _load_sessions(session, head, first, as_of)
    completions = _load_completions(session)
    slots = _load_strength_slots(session)
    strong_rows = session.scalars(select(StrongWorkoutRow).where(
        StrongWorkoutRow.local_date >= first, StrongWorkoutRow.local_date <= as_of,
        StrongWorkoutRow.resolution_state == "resolved",
    ).order_by(StrongWorkoutRow.local_date, StrongWorkoutRow.id)).all()
    rpe_rows = session.scalars(select(SessionRpe).order_by(SessionRpe.collected_at, SessionRpe.id)).all()
    strong = _load_strong_workouts(strong_rows, rpe_rows)
    runs = _load_runs(session, first, as_of, rpe_rows)
    checkins = _load_checkins(session, now, zone)
    prompts = _load_prompts(session, now)
    metrics = _load_metrics(session, as_of, runs)
    anchors = _load_anchors(session)
    block_rows, active_block = _load_active_block(session, as_of)
    decisions = _load_block_decisions(session)
    proposals = _load_proposals(session)
    goals = _load_goals(session)
    events = _load_events(session, as_of)
    exception_findings, exception_patches = _load_exception_state(session, as_of, now)
    benchmark_history = _load_benchmark_history(session, block_rows)
    this_monday = week_bounds(as_of)[0]
    weekly = [load_week(session, this_monday - timedelta(days=7), today=as_of), load_week(session, this_monday, today=as_of)]
    return SnapshotInputs(
        as_of=as_of, now=now, timezone=zone.key, calendar_version=head,
        data_revision=state.data_revision if state else 0,
        cycle_anchor=profile.cycle_anchor if profile else None,
        anchor_confirmed=bool(profile.anchor_confirmed) if profile else False,
        clinical_restriction=clinical_restriction(profile.facts) if profile else None,
        sessions=sessions, completions=completions, strength_slots=slots, strong_workouts=strong,
        goals=goals, events=events, active_block=active_block, block_decisions=decisions,
        runs=runs, checkins=checkins, prompts=prompts,
        metric_results=metrics, anchors=anchors, proposals=proposals, coverage=coverage(session, first, as_of),
        exception_findings=exception_findings, exception_patches=exception_patches,
        review_recommended=_load_review_recommended(session, as_of), benchmark_history=benchmark_history,
        weekly_digest=weekly,
    )


def build_snapshot(
    session: Session, operation: str, as_of: date, *, now: datetime, kb_root: Path | None = None
) -> dict:
    from app.metrics.refresh import ensure_nights, ensure_windows

    global_write_lock(session)
    session.execute(select(AppState.id).where(AppState.id == 1).with_for_update())
    previous_now = session.info.get("metrics_now", MISSING)
    session.info["metrics_now"] = now
    try:
        ensure_windows(session, as_of)
        if operation in {DAILY, ROLLING, QUALITY_OP, BLOCK, EXCEPTION, POST_EVENT}:
            days = {DAILY: 3, ROLLING: 14, QUALITY_OP: 14, BLOCK: 28, EXCEPTION: 3, POST_EVENT: 14}[operation]
            ensure_nights(session, as_of - timedelta(days=days - 1), as_of)
        if operation in {EXCEPTION, POST_EVENT, ROLLING, BLOCK}:
            from app.services.exceptions.detector import run_detection

            run_detection(session, now)
        inputs = load_inputs(session, as_of, now=now)
        payload = build_payload(inputs, operation)
        bundle = load_route(
            operation,
            recipe_ids=select_recipe_ids(inputs, operation),
            conditional_topics=select_conditional_topics(inputs, operation),
            root=kb_root,
        )
        kb = VerifiedKnowledge(**verify_selection(tuple(bundle.routes), root=kb_root))
        decision = collect_decision_inputs(session, operation, as_of, now=now, kb=kb)
        meta = payload["snapshot_meta"]
        meta["source_fingerprint"] = decision["source_fingerprint"]
        meta["source_provenance"] = source_provenance(decision["source_versions"])
        meta["safety_guard"] = decision["safety_guard"]
        meta["knowledge"] = {"digest": kb.digest, "selected_records": list(kb.selected_records)}
        payload_json = canonical_json(payload)
        approx_tokens = math.ceil((len(payload_json) + bundle.chars) / 4)
        row = CoachSnapshot(
            operation=operation,
            as_of=as_of,
            generated_at=now,
            calendar_version_number=inputs.calendar_version or 0,
            block_version_id=inputs.active_block.get("version_id") if inputs.active_block else None,
            data_revision=inputs.data_revision,
            payload=payload,
            payload_sha256=hashlib.sha256(payload_json.encode()).hexdigest(),
            kb_package_version=bundle.package_version,
            kb_routes=list(kb.selection),
            kb_digest=kb.digest,
            source_fingerprint=decision["source_fingerprint"],
            source_versions=decision["source_versions"],
            approx_tokens=approx_tokens,
        )
        session.add(row)
        session.flush()
    finally:
        if previous_now is MISSING:
            session.info.pop("metrics_now", None)
        else:
            session.info["metrics_now"] = previous_now
    return {
        "snapshot_id": str(row.id),
        "payload": payload,
        "kb": {"package_version": bundle.package_version, "excerpts": [e.to_json() for e in bundle.excerpts]},
        "approx_tokens": approx_tokens,
    }
