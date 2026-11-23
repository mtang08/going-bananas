"""Snapshot inputs."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.calendar_models import SessionCompletion
from app.checkin_models import Checkin as CheckinV2
from app.checkin_models import SessionRpe, SymptomReport
from app.coach_v2_models import CoachProposal, CoachProposalChange
from app.domain.athlete_facts import clinical_restriction
from app.domain.local_time import date_in_zone
from app.domain.travel import OPEN_TRIP_MAX
from app.metric_models import MetricResult, Prompt
from app.models import Activity, AppState, ImportBatch
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
from app.services.events import goal_pace_s_per_km, ranked_upcoming, target_status
from app.services.exceptions.vocab import NON_TERMINAL_FINDING
from app.services.profile import current_profile
from app.services.proposals.schema import HORIZON_MAX_DAYS, derive_certainty
from app.services.run_rpe import effective_run_rpe
from app.services.snapshot.common import (
    BENCHMARK_HISTORY_MAX,
    LIVE_PATCH,
    SUMMARY_DAYS,
    SnapshotInputs,
    row_view,
)
from app.services.timezone import athlete_tz
from app.services.trips import trip_view
from app.services.weekly_digest import load_week, week_bounds
from app.strong_models import StrongWorkoutRow
from app.travel_models import Trip


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
                    "brief",
                ),
            ),
            certainty=derive_certainty(row["local_date"], as_of),
        )
        for row in state_at(session, head)
        if first <= row["local_date"] <= as_of + timedelta(days=HORIZON_MAX_DAYS)
    ]
    return sessions


def _load_completions(session: Session) -> list[dict]:
    completion_rows = session.scalars(select(SessionCompletion)).all()
    completions = [
        row_view(
            row,
            (
                "session_uid",
                "status",
                "match_method",
                "activity_id",
                "strong_workout_id",
                "manual_session_id",
                "modification_reason",
            ),
        )
        for row in completion_rows
    ]
    return completions


def _load_strength_slots(session: Session) -> list[dict]:
    slots = [
        row_view(
            row,
            (
                "id",
                "label",
                "default_weekday",
                "lower_body_cost",
                "typical_duration_s",
                "main_lower_body_lifts",
                "active",
            ),
            names={"id": "slot_id"},
        )
        for row in session.scalars(
            select(StrengthRoutineSlot).order_by(StrengthRoutineSlot.default_weekday, StrengthRoutineSlot.id)
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


def _load_active_block(
    session: Session, as_of: date, top_event_id: uuid.UUID | None
) -> tuple[Sequence[BlockVersion], dict | None]:
    block_rows = session.scalars(
        select(BlockVersion).order_by(BlockVersion.block_uid, BlockVersion.version.desc())
    ).all()
    active_row = active_block_version(session)
    block_keys = (
        "status",
        "objective",
        "why",
        "legacy_text",
        "maintained_qualities",
        "non_goals",
        "eligible_recipe_ids",
        "progression_dimension",
        "constraints",
        "start_date",
        "review_date",
        "indicators",
        "early_review_triggers",
        "objective_status",
        "benchmark",
        "target_event_id",
        "build_outline",
    )
    from app.services.block_benchmark import benchmark_status, status_data

    active_block = (
        dict(
            row_view(active_row, block_keys),
            block_uid=active_row.block_uid,
            version_id=active_row.id,
            version=active_row.version,
            benchmark_status=status_data(benchmark_status(session, active_row, as_of)),
            target_event_status=target_status(active_row.target_event_id, top_event_id),
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
    omissions = {
        (proposal.id, change["change_id"])
        for proposal in proposal_rows
        for change in proposal.payload.get("changes", [])
        if "strength_omission" in change.get("material_flags", [])
    }
    by_proposal: dict[uuid.UUID, list[dict]] = {}
    for change_row in changes:
        item = row_view(change_row, ("change_id", "op", "session_uid", "decision", "before", "after"))
        if (change_row.proposal_id, change_row.change_id) in omissions:
            item.update(material_flags=["strength_omission"], reason=change_row.reason)
        by_proposal.setdefault(change_row.proposal_id, []).append(item)
    proposals = [
        dict(
            row_view(row, ("operation", "status", "submitted_at", "decided_at", "headline", "next_check")),
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
    rows = list(
        session.scalars(
            select(Event).where(Event.event_date >= as_of - timedelta(days=28)).order_by(Event.event_date, Event.id)
        )
    )
    ranks = {row.id: rank for rank, row in ranked_upcoming(rows, as_of)}
    return [
        {
            "event_id": row.id,
            "name": row.name,
            "event_date": row.event_date,
            "distance_m": row.distance_m,
            "purpose": row.purpose,
            "goal_time_s": row.goal_time_s,
            "goal_pace_s_per_km": goal_pace_s_per_km(row.distance_m, row.goal_time_s),
            "rank": ranks.get(row.id),
            "status": row.status,
            "result_s": row.result_s,
        }
        for row in rows
    ]


def _load_exception_state(session: Session, as_of: date, now: datetime) -> tuple[list[dict], list[dict]]:
    from app.exception_models import ExceptionFinding, ExceptionPatch
    from app.services.exceptions.detector import finding_data, last_review_at, patch_data

    last_review = last_review_at(session)
    exception_findings = [
        finding_data(row, last_review)
        for row in session.scalars(
            select(ExceptionFinding)
            .where(
                or_(
                    ExceptionFinding.status.in_(NON_TERMINAL_FINDING),
                    ExceptionFinding.first_seen_at >= now - timedelta(days=SUMMARY_DAYS),
                )
            )
            .order_by(ExceptionFinding.first_seen_at.desc(), ExceptionFinding.id)
        )
    ]
    exception_patches = [
        patch_data(session, row, as_of)
        for row in session.scalars(
            select(ExceptionPatch)
            .where(
                or_(
                    ExceptionPatch.status.in_(LIVE_PATCH),
                    ExceptionPatch.window_end >= as_of - timedelta(days=SUMMARY_DAYS - 1),
                )
            )
            .order_by(ExceptionPatch.created_at.desc(), ExceptionPatch.id)
        )
    ]
    return exception_findings, exception_patches


def _load_benchmark_history(session: Session, block_rows: Sequence[BlockVersion]) -> list[dict]:
    versions = {(row.block_uid, row.version): row.objective for row in block_rows}
    benchmark_history = [
        {
            "block_uid": row.block_uid,
            "objective": versions.get((row.block_uid, row.block_version)),
            "protocol": row.protocol,
            "distance_m": row.distance_m,
            "local_date": row.local_date,
            "result_s": row.result_s,
            "outcome": row.outcome,
        }
        for row in session.scalars(
            select(BlockBenchmarkResult)
            .where(BlockBenchmarkResult.outcome.is_not(None))
            .order_by(BlockBenchmarkResult.local_date.desc().nulls_last(), BlockBenchmarkResult.updated_at.desc())
            .limit(BENCHMARK_HISTORY_MAX)
        )
    ]
    return benchmark_history


TRAVEL_DAYS_BACK = 7
TRAVEL_DAYS_AHEAD = 120


def _local_iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _load_trips(session: Session, as_of: date, zone: ZoneInfo) -> list[dict]:
    first = as_of - timedelta(days=TRAVEL_DAYS_BACK)
    last = as_of + timedelta(days=TRAVEL_DAYS_AHEAD)
    rows = session.scalars(
        select(Trip)
        .where(
            Trip.status != "dismissed",
            Trip.start_date <= last,
            or_(Trip.end_date >= first, and_(Trip.end_date.is_(None), Trip.start_date >= first - OPEN_TRIP_MAX)),
        )
        .order_by(Trip.start_date, Trip.id)
    )
    trips = []
    for row in rows:
        view = trip_view(session, row, zone)
        trips.append(
            {
                "trip_id": view["id"],
                "status": view["status"],
                "confirmed": view["status"] == "confirmed",
                "start_date": view["start_date"],
                "end_date": view["end_date"],
                "destination": view["destination_label"],
                "destination_timezone": view["destination_tz"],
                "source": view["source"],
                "confidence": view["confidence"],
                "running_access": view["running_access"],
                "gym_access": view["gym_access"],
                "days": list(view["day_availability"]),
                "travel_days": list(view["travel_days"]),
                "legs": [
                    {
                        "depart_local": _local_iso(leg["depart_local"]),
                        "depart_timezone": leg["depart_tz"],
                        "arrive_local": _local_iso(leg["arrive_local"]),
                        "arrive_timezone": leg["arrive_tz"],
                        "timezone_basis": leg["timezone_basis"],
                    }
                    for leg in view["legs"]
                    if not leg["removed"] and leg["depart_local"] is not None and leg["arrive_local"] is not None
                ],
            }
        )
    return trips


def _load_travel_meta(session: Session, zone: ZoneInfo) -> dict:
    synced = session.scalar(
        select(ImportBatch.finished_at)
        .where(ImportBatch.source_kind == "google_calendar", ImportBatch.status == "complete")
        .order_by(ImportBatch.finished_at.desc().nulls_last())
        .limit(1)
    )
    return {"home_timezone": zone.key, "calendar_synced_at": synced}


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
    strong_rows = session.scalars(
        select(StrongWorkoutRow)
        .where(
            StrongWorkoutRow.local_date >= first,
            StrongWorkoutRow.local_date <= as_of,
            StrongWorkoutRow.resolution_state == "resolved",
        )
        .order_by(StrongWorkoutRow.local_date, StrongWorkoutRow.id)
    ).all()
    rpe_rows = session.scalars(select(SessionRpe).order_by(SessionRpe.collected_at, SessionRpe.id)).all()
    strong = _load_strong_workouts(strong_rows, rpe_rows)
    runs = _load_runs(session, first, as_of, rpe_rows)
    checkins = _load_checkins(session, now, zone)
    prompts = _load_prompts(session, now)
    metrics = _load_metrics(session, as_of, runs)
    anchors = _load_anchors(session)
    events = _load_events(session, as_of)
    top_event_id = next((event["event_id"] for event in events if event["rank"] == 1), None)
    block_rows, active_block = _load_active_block(session, as_of, top_event_id)
    decisions = _load_block_decisions(session)
    proposals = _load_proposals(session)
    goals = _load_goals(session)
    exception_findings, exception_patches = _load_exception_state(session, as_of, now)
    benchmark_history = _load_benchmark_history(session, block_rows)
    this_monday = week_bounds(as_of)[0]
    weekly = [
        load_week(session, this_monday - timedelta(days=7), today=as_of),
        load_week(session, this_monday, today=as_of),
    ]
    return SnapshotInputs(
        as_of=as_of,
        now=now,
        timezone=zone.key,
        calendar_version=head,
        data_revision=state.data_revision if state else 0,
        cycle_anchor=profile.cycle_anchor if profile else None,
        anchor_confirmed=bool(profile.anchor_confirmed) if profile else False,
        clinical_restriction=clinical_restriction(profile.facts) if profile else None,
        sessions=sessions,
        completions=completions,
        strength_slots=slots,
        strong_workouts=strong,
        goals=goals,
        events=events,
        active_block=active_block,
        block_decisions=decisions,
        runs=runs,
        checkins=checkins,
        prompts=prompts,
        metric_results=metrics,
        anchors=anchors,
        proposals=proposals,
        coverage=coverage(session, first, as_of),
        exception_findings=exception_findings,
        exception_patches=exception_patches,
        review_recommended=_load_review_recommended(session, as_of),
        benchmark_history=benchmark_history,
        weekly_digest=weekly,
        trips=_load_trips(session, as_of, zone),
        travel_meta=_load_travel_meta(session, zone),
    )
