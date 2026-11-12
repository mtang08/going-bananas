"""Bounded, source-aware coach snapshot projections."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.core import coverage
from app.calendar_models import SessionCompletion
from app.checkin_models import Checkin as CheckinV2
from app.checkin_models import SessionRpe, SymptomReport
from app.coach_v2_models import CoachProposal, CoachProposalChange, CoachSnapshot
from app.metric_models import MetricResult, Prompt
from app.models import Activity, AppState, ProfileVersion
from app.planning_models import BlockDecision, BlockVersion, Event, Goal, IntensityAnchor, StrengthRoutineSlot
from app.services.calendar import state_at
from app.services.decision_inputs import VerifiedKnowledge, canonical_json, collect_decision_inputs
from app.services.knowledge import CONDITIONAL_TOPICS, load_route, verify_selection
from app.services.proposals import LONG_RECIPE, QUALITY_RECIPES, DecisionError, derive_certainty, is_quality_slot, scope
from app.services.timezone import athlete_tz
from app.strong_models import StrongWorkoutRow

RUN_SPORTS = {"running", "trail_running", "treadmill_running"}
DRILL_DOWN_QUERIES = ["activity_execution", "long_run_history", "recovery_nights", "calendar_diff", "explain_metric"]
DATASETS = ("activities", "sleep", "hrv", "resting_hr")
SNAPSHOT_SCHEMA = "coach_snapshot.v1"
_MISSING = object()
DAILY = "proceed_or_modify_today"
ROLLING = "review_rolling_plan"
QUALITY_OP = "select_quality_session"
BLOCK = "review_training_block"
CALIB = "recalibrate_intensity"
RACE = "handle_goal_or_race_change"


def _view(row: Any, keys: tuple[str, ...], *, names: dict[str, str] | None = None) -> dict:
    names = names or {}
    return {names.get(key, key): row.get(key) if isinstance(row, dict) else getattr(row, key) for key in keys}


def _wire(value: Any) -> Any:
    return json.loads(canonical_json(value))


_PRIVATE_KEYS = (
    "note",
    "latitude",
    "longitude",
    "gps",
    "coordinate",
    "stream",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "vo2max",
    "training_status",
    "body_battery",
    "readiness",
)


def _privacy(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _privacy(item)
            for key, item in value.items()
            if not any(term in str(key).lower() for term in _PRIVATE_KEYS)
        }
    if isinstance(value, list):
        return [_privacy(item) for item in value]
    return value


def _day(value: Any) -> date:
    return date.fromisoformat(value) if isinstance(value, str) else value


def _instant(value: Any) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value


def _between(day: Any, first: date, last: date) -> bool:
    return day is not None and first <= _day(day) <= last


@dataclass
class SnapshotInputs:
    as_of: date
    now: datetime
    timezone: str
    calendar_version: int | None
    data_revision: int
    cycle_anchor: date | None
    anchor_confirmed: bool
    clinical_restriction: str | None
    sessions: list[dict] = field(default_factory=list)
    completions: list[dict] = field(default_factory=list)
    strength_slots: list[dict] = field(default_factory=list)
    strong_workouts: list[dict] = field(default_factory=list)
    goals: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    active_block: dict | None = None
    block_decisions: list[dict] = field(default_factory=list)
    runs: list[dict] = field(default_factory=list)
    checkins: list[dict] = field(default_factory=list)
    legacy_checkins: list[dict] = field(default_factory=list)
    prompts: list[dict] = field(default_factory=list)
    metric_results: list[dict] = field(default_factory=list)
    anchors: list[dict] = field(default_factory=list)
    proposals: list[dict] = field(default_factory=list)
    coverage: list[dict] = field(default_factory=list)


def _window(operation: str, section: str, inputs: SnapshotInputs) -> tuple[date, date]:
    day = inputs.as_of
    if section == "calendar":
        return (
            (day, day + timedelta(days=13))
            if operation == RACE
            else (
                day - timedelta(days={DAILY: 3, ROLLING: 14, QUALITY_OP: 14, BLOCK: 28}[operation]),
                day + timedelta(days=3 if operation == DAILY else 13),
            )
        )
    if section == "exposures":
        return day - timedelta(
            days={DAILY: 2, ROLLING: 13, QUALITY_OP: 13, BLOCK: 27, RACE: 13, CALIB: 83}[operation]
        ), day
    if section == "symptoms":
        days = 14 if operation == DAILY else 28
        if operation == BLOCK and inputs.active_block:
            return _day(inputs.active_block["start_date"]), day
        return day - timedelta(days=days - 1), day
    if section == "recovery":
        days = {DAILY: 3, ROLLING: 14, QUALITY_OP: 14, BLOCK: 28}[operation]
        return day - timedelta(days=days - 1), day
    raise ValueError("unknown_section")


def _safe_revision(value: dict | None) -> dict | None:
    if value is None:
        return None
    allowed = {
        "local_date",
        "slot",
        "kind",
        "recipe_id",
        "custom",
        "placeholder",
        "locked",
        "intent",
        "planned_duration_s",
        "planned_distance_m",
        "structure",
        "strength_slot_id",
    }
    return {key: value[key] for key in allowed if key in value}


def _safety_guard(inputs: SnapshotInputs) -> dict:
    first = inputs.now - timedelta(hours=72)
    recent = [c for c in inputs.checkins if first <= _instant(c["observed_at"]) <= inputs.now]
    severities = [
        float(sym["severity"]) for c in recent for sym in c.get("symptoms", []) if sym.get("severity") is not None
    ]
    legacy = [c for c in inputs.legacy_checkins if first <= _instant(c["observed_at"]) <= inputs.now]
    return {
        "window_hours": 72,
        "gait_change_yes": any(c.get("gait_change") == "yes" for c in recent),
        "max_symptom_severity": max(severities) if severities else None,
        "illness_present": any(c.get("illness") == "present" for c in recent),
        "clinical_restriction_active": bool(inputs.clinical_restriction and inputs.clinical_restriction.strip()),
        "legacy_safety_active": any(
            c.get("gait") == "affected"
            or c.get("symptoms") == "severe"
            or (c.get("symptoms") == "moderate" and c.get("change") == "worse")
            for c in legacy
        ),
    }


def _metric_view(row: dict) -> dict:
    return _view(
        row,
        (
            "result_id",
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
    )


def _session_view(row: dict, completion: dict | None) -> dict:
    result = _view(
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
    )
    result["is_original"] = row["revision"] == 1
    result["completion_status"] = completion["status"] if completion else None
    return result


def _classify(recipe: str | None) -> str:
    if recipe == LONG_RECIPE:
        return "long"
    if recipe in QUALITY_RECIPES:
        return "quality"
    return "easy" if recipe else "unplanned"


def _completed_exposures(inputs: SnapshotInputs, operation: str) -> dict:
    start, end = _window(operation, "exposures", inputs)
    by_activity = {str(c["activity_id"]): c for c in inputs.completions if c.get("activity_id")}
    sessions = {str(s["session_uid"]): s for s in inputs.sessions}
    runs = []
    for row in inputs.runs:
        if not _between(row.get("local_date"), start, end):
            continue
        completion = by_activity.get(str(row["activity_id"]))
        planned = sessions.get(str(completion["session_uid"])) if completion else None
        recipe = planned.get("recipe_id") if planned else None
        if operation == CALIB and recipe not in {"REC003", "REC004", "REC005", "REC009"}:
            continue
        view = _view(row, ("activity_id", "local_date", "sport", "timer_s", "distance_m", "rpe", "rpe_source"))
        view.update(
            session_uid=completion["session_uid"] if completion else None,
            planned_recipe_id=recipe,
            completion_status=completion["status"] if completion else None,
        )
        view["class"] = _classify(recipe)
        runs.append(view)
    runs.sort(key=lambda row: (str(row["local_date"]), str(row["activity_id"])))
    if operation == CALIB:
        return {"window_days": 84, "runs": runs}
    lifts = [
        _view(row, ("strong_workout_id", "local_date", "workout_name", "duration_s", "rpe"))
        for row in inputs.strong_workouts
        if _between(row.get("local_date"), start, end)
    ]
    lifts.sort(key=lambda row: (str(row["local_date"]), str(row["strong_workout_id"])))
    return {
        "window_days": {DAILY: 3, ROLLING: 14, QUALITY_OP: 14, BLOCK: 28, RACE: 14}[operation],
        "runs": runs,
        "lifts": lifts,
    }


def _symptoms(inputs: SnapshotInputs, operation: str) -> dict:
    start, end = _window(operation, "symptoms", inputs)
    reports = []
    for checkin in inputs.checkins:
        if not _between(checkin.get("local_date"), start, end):
            continue
        for symptom in checkin.get("symptoms", []):
            view = _view(checkin, ("checkin_id", "observed_at", "local_date", "kind", "activity_id"))
            view.update(_view(symptom, ("site", "side", "severity", "timing")))
            reports.append(view)
    reports.sort(key=lambda row: (str(row["observed_at"]), str(row["checkin_id"]), row["site"], row["timing"]))
    prompts = [
        _view(p, ("prompt_id", "kind", "activity_id", "status", "opens_at", "closes_at"))
        for p in inputs.prompts
        if p.get("kind") == "delayed_symptom" and _between(_instant(p["opens_at"]).date(), start, end)
    ]
    return {"window_days": (end - start).days + 1, "reports": reports, "delayed_responses": prompts}


def _data_quality(inputs: SnapshotInputs) -> dict:
    datasets = {}
    flags = []
    for dataset in DATASETS:
        complete = [
            _day(row["end_date"])
            for row in inputs.coverage
            if row.get("dataset") == dataset and row.get("status") == "complete"
        ]
        fresh = max(complete) if complete else None
        status = "missing" if fresh is None else "stale" if fresh < inputs.as_of - timedelta(days=2) else "fresh"
        datasets[dataset] = {"status": status, "fresh_through": fresh}
        if status != "fresh":
            flags.append(f"{dataset}_{status}")
    if not any(a.get("status") == "active" for a in inputs.anchors):
        flags.append("no_intensity_anchor")
    if inputs.active_block is None:
        flags.append("no_active_block")
    return {"datasets": datasets, "flags": sorted(flags)}


def _prior_decisions(inputs: SnapshotInputs, operation: str) -> list[dict]:
    if operation == BLOCK:
        uid = inputs.active_block.get("block_uid") if inputs.active_block else None
        rows = [r for r in inputs.block_decisions if uid is None or str(r.get("block_uid")) == str(uid)]
        return sorted(
            [
                _view(
                    r,
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
                for r in rows
            ],
            key=lambda r: str(r["decided_at"]),
        )
    if operation == CALIB:
        return [
            _view(
                a,
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
            for a in inputs.anchors
        ]
    proposals = sorted(inputs.proposals, key=lambda p: str(p.get("submitted_at")), reverse=True)
    if operation in {ROLLING, QUALITY_OP}:
        proposals = [
            p
            for p in proposals
            if p.get("operation") == ROLLING and p.get("status") in {"accepted", "partially_accepted", "rejected"}
        ][:2]
    else:
        proposals = proposals[:3]
    result = []
    completions = {str(c["session_uid"]): c for c in inputs.completions}
    for proposal in proposals:
        view = _view(
            proposal, ("proposal_id", "operation", "status", "submitted_at", "decided_at", "summary", "follow_up")
        )
        changes = []
        for change in proposal.get("changes", []):
            item = _view(change, ("change_id", "op", "session_uid", "decision"))
            item["before"] = _safe_revision(change.get("before"))
            item["after"] = _safe_revision(change.get("after"))
            if change.get("decision") == "accepted" and change.get("session_uid"):
                date_value = (change.get("after") or {}).get("local_date") or (change.get("before") or {}).get(
                    "local_date"
                )
                if date_value:
                    day = _day(date_value)
                    reports = [
                        _view(sym, ("site", "side", "severity", "timing"))
                        for c in inputs.checkins
                        if _between(c.get("local_date"), day, day + timedelta(days=3))
                        for sym in c.get("symptoms", [])
                    ]
                    item["outcome"] = {
                        "session_date": day,
                        "completion_status": (completions.get(str(change["session_uid"])) or {}).get("status"),
                        "symptom_reports_after": reports,
                    }
            changes.append(item)
        view["changes"] = changes
        result.append(view)
    return result


def build_payload(inputs: SnapshotInputs, operation: str) -> dict:
    if operation not in {DAILY, ROLLING, QUALITY_OP, BLOCK, CALIB, RACE}:
        raise ValueError("unsupported_operation")
    start, end = scope(operation, inputs.as_of)
    payload: dict[str, Any] = {
        "snapshot_meta": {
            "schema_version": SNAPSHOT_SCHEMA,
            "operation": operation,
            "as_of": inputs.as_of,
            "timezone": inputs.timezone,
            "calendar_version": inputs.calendar_version,
            "block_version_id": inputs.active_block.get("version_id") if inputs.active_block else None,
            "data_revision": inputs.data_revision,
            "scope": {"start": start, "end": end},
            "safety_guard": _safety_guard(inputs),
        },
        "legacy_checkins": [
            _view(
                c,
                (
                    "schema_version",
                    "id",
                    "version",
                    "observed_at",
                    "activity_id",
                    "symptoms",
                    "change",
                    "gait",
                    "feeling",
                    "effort",
                    "severity_numeric",
                ),
            )
            for c in inputs.legacy_checkins
            if inputs.now - timedelta(hours=72) <= _instant(c["observed_at"]) <= inputs.now
        ],
        "completed_exposures": _completed_exposures(inputs, operation),
        "anchors": [
            _view(
                a,
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
            for a in inputs.anchors
            if operation in {BLOCK, CALIB} or a.get("status") == "active"
        ],
        "data_quality": _data_quality(inputs),
        "drill_down_queries": list(DRILL_DOWN_QUERIES),
    }
    if operation != CALIB:
        goals = [_view(g, ("goal_id", "text", "horizon", "priority", "status")) for g in inputs.goals]
        events = [
            _view(e, ("event_id", "name", "event_date", "distance_m", "priority", "status", "result_s"))
            for e in inputs.events
        ]
        slots = [
            _view(
                s,
                (
                    "slot_id",
                    "label",
                    "default_weekday",
                    "lower_body_cost",
                    "typical_duration_s",
                    "main_lower_body_lifts",
                ),
            )
            for s in inputs.strength_slots
        ]
        latest = sorted(inputs.strong_workouts, key=lambda s: str(s["local_date"]), reverse=True)[:2]
        goals_view = {
            "strength_routine": slots,
            "latest_strong_sessions": [_view(s, ("local_date", "workout_name", "duration_s")) for s in latest],
            "run_cycle": {"anchor_date": inputs.cycle_anchor, "confirmed": inputs.anchor_confirmed},
            "clinical_restriction": inputs.clinical_restriction,
        }
        if operation != DAILY:
            goals_view.update(goals=goals, events=events)
        payload["goals_and_constraints"] = goals_view
        cal_start, cal_end = _window(operation, "calendar", inputs)
        completions = {str(c["session_uid"]): c for c in inputs.completions}
        sessions = [
            _session_view(s, completions.get(str(s["session_uid"])))
            for s in inputs.sessions
            if _between(s.get("local_date"), cal_start, cal_end)
        ]
        sessions.sort(key=lambda s: (str(s["local_date"]), s["slot"], str(s["session_uid"])))
        payload["calendar"] = {
            "head": inputs.calendar_version,
            "start": cal_start,
            "end": cal_end,
            "sessions": sessions,
        }
    block = inputs.active_block
    if operation == BLOCK:
        payload["block"] = {
            "active": _view(block, tuple(block)) if block else None,
            "history": _prior_decisions(inputs, BLOCK),
        }
    elif operation == DAILY:
        payload["block"] = _view(block, ("block_uid", "version_id", "objective")) if block else None
    elif operation == CALIB:
        payload["block"] = {"objective": block["objective"]} if block else None
    else:
        payload["block"] = _view(block, tuple(block)) if block else None
    if operation not in {CALIB}:
        windows = [7] if operation == DAILY else [7, 14, 28, 56, 84] if operation == BLOCK else [7, 14, 28]
        keys = {f"w{days}:{inputs.as_of.isoformat()}" for days in windows}
        keys.update(f"w{days}:{inputs.as_of.isoformat()}:{kind}" for days in windows for kind in ("run", "strength"))
        payload["load_shape"] = [
            _metric_view(m)
            for m in inputs.metric_results
            if m.get("subject_type") == "window" and m.get("subject_key") in keys
        ]
    if operation not in {RACE}:
        quality_runs = [r for r in payload["completed_exposures"]["runs"] if r["class"] == "quality"]
        if operation == DAILY:
            quality_runs = quality_runs[-1:]
        exposure_ids = {str(r["activity_id"]) for r in quality_runs}
        execution = [
            _metric_view(m)
            for m in inputs.metric_results
            if m.get("metric_id") == "work_interval_execution" and str(m.get("subject_key")) in exposure_ids
        ]
        payload["execution"] = execution
    if operation not in {CALIB}:
        payload["symptoms"] = _symptoms(inputs, operation)
    if operation in {DAILY, ROLLING, QUALITY_OP, BLOCK}:
        rec_start, rec_end = _window(operation, "recovery", inputs)
        payload["recovery"] = [
            _metric_view(m)
            for m in inputs.metric_results
            if m.get("metric_id") == "recovery_multisignal_summary"
            and m.get("subject_type") == "night"
            and str(m.get("subject_key", "")).startswith("night:")
            and _between(str(m["subject_key"]).split(":", 1)[1], rec_start, rec_end)
        ]
    if operation in {DAILY, ROLLING, QUALITY_OP, BLOCK, CALIB}:
        payload["prior_decisions"] = _prior_decisions(inputs, operation)
    return _privacy(_wire(payload))


def _scope_sessions(inputs: SnapshotInputs, operation: str) -> list[dict]:
    start, end = scope(operation, inputs.as_of)
    return [s for s in inputs.sessions if _between(s.get("local_date"), start, end)]


def _has_numeric_target(structure: Any) -> bool:
    if not isinstance(structure, list):
        return False
    for item in structure:
        steps = item.get("steps", []) if isinstance(item, dict) and item.get("type") == "repeat" else [item]
        for step in steps:
            if (
                isinstance(step, dict)
                and isinstance(step.get("target"), dict)
                and step["target"].get("modality") in {"speed", "hr"}
            ):
                return True
    return False


def select_conditional_topics(inputs: SnapshotInputs, operation: str) -> list[str]:
    sessions = _scope_sessions(inputs, operation)
    runs = [s for s in sessions if s.get("kind") == "run"]
    slots = {str(s["slot_id"]): s for s in inputs.strength_slots}
    symptom_start, symptom_end = _window(operation if operation not in {CALIB, RACE} else DAILY, "symptoms", inputs)
    recent_checkins = [c for c in inputs.checkins if _between(c.get("local_date"), symptom_start, symptom_end)]
    ptt = any(c.get("symptoms") for c in recent_checkins) or any(
        p.get("kind") == "delayed_symptom"
        and p.get("status") == "answered"
        and _between(_instant(p["opens_at"]).date(), symptom_start, symptom_end)
        for p in inputs.prompts
    )
    rec_start = inputs.as_of - timedelta(
        days=(3 if operation == DAILY else 14 if operation in {CALIB, RACE, ROLLING, QUALITY_OP} else 28) - 1
    )
    recovery = any(
        m.get("metric_id") == "recovery_multisignal_summary"
        and m.get("subject_type") == "night"
        and str(m.get("subject_key", "")).startswith("night:")
        and _between(str(m["subject_key"]).split(":", 1)[1], rec_start, inputs.as_of)
        and isinstance(m.get("value"), dict)
        and (m["value"].get("flags") or m["value"].get("discordance") is True)
        for m in inputs.metric_results
    ) or any(c.get("illness") in {"possible", "present"} for c in recent_checkins)
    hybrid = any(
        s.get("kind") == "strength"
        and (slots.get(str(s.get("strength_slot_id"))) or {}).get("lower_body_cost") in {"moderate", "high"}
        and any(abs((_day(s["local_date"]) - _day(r["local_date"])).days) <= 2 for r in runs)
        for s in sessions
    )
    quality = any(is_quality_slot(s.get("kind", ""), s.get("recipe_id"), bool(s.get("placeholder"))) for s in sessions)
    low_anchor = any(
        a.get("status") == "active" and a.get("confidence") in {"low", "insufficient"} for a in inputs.anchors
    )
    active = [
        ptt,
        recovery,
        hybrid,
        operation in {ROLLING, BLOCK} and any(s.get("recipe_id") == LONG_RECIPE for s in runs),
        operation in {ROLLING, BLOCK},
        quality,
        operation == CALIB
        or (
            low_anchor
            and any(s.get("recipe_id") in QUALITY_RECIPES and _has_numeric_target(s.get("structure")) for s in runs)
        ),
        operation in {BLOCK, RACE},
        operation == RACE,
    ]
    return [topic for topic, enabled in zip(CONDITIONAL_TOPICS, active, strict=True) if enabled]


def select_recipe_ids(inputs: SnapshotInputs, operation: str) -> list[str]:
    sessions = _scope_sessions(inputs, operation)
    ids = {s["recipe_id"] for s in sessions if s.get("kind") == "run" and s.get("recipe_id")}
    if operation in {ROLLING, QUALITY_OP} and any(
        is_quality_slot(s.get("kind", ""), s.get("recipe_id"), bool(s.get("placeholder"))) for s in sessions
    ):
        ids.update(inputs.active_block.get("eligible_recipe_ids", []) if inputs.active_block else QUALITY_RECIPES)
    return sorted(ids)


def load_inputs(session: Session, as_of: date, *, now: datetime) -> SnapshotInputs:
    from app.calendar_models import LegacyImportMap
    from app.metrics.engine import load_runs
    from app.models import Checkin as LegacyCheckin

    zone = athlete_tz(session)
    state = session.get(AppState, 1)
    profile = session.scalars(select(ProfileVersion).order_by(ProfileVersion.version.desc()).limit(1)).first()
    head = state.calendar_head_version if state else 0
    first = as_of - timedelta(days=120)
    sessions = [
        dict(
            _view(
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
    completion_rows = session.scalars(select(SessionCompletion)).all()
    completions = [
        _view(row, ("session_uid", "status", "activity_id", "strong_workout_id", "manual_session_id"))
        for row in completion_rows
    ]
    slots = [
        _view(
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

    def effective_rpe(activity_id: Any = None, strong_id: Any = None, fallback: Any = None) -> tuple[Any, str | None]:
        matched = [
            r
            for r in rpe_rows
            if (activity_id and r.activity_id == activity_id) or (strong_id and r.strong_workout_id == strong_id)
        ]
        preferred = next((r for r in reversed(matched) if r.source == "manual"), None) or next(
            (r for r in reversed(matched) if r.source == "garmin_fit"), None
        )
        return (
            (preferred.rpe, preferred.source)
            if preferred
            else (fallback, "garmin_fit" if fallback is not None else None)
        )

    strong = [
        dict(
            _view(row, ("local_date", "workout_name", "duration_s")),
            strong_workout_id=row.id,
            rpe=effective_rpe(strong_id=row.id)[0],
        )
        for row in strong_rows
    ]
    run_facts = load_runs(session, first, as_of + timedelta(days=1))
    activities = (
        {
            row.id: row
            for row in session.scalars(select(Activity).where(Activity.id.in_([run.activity_id for run in run_facts])))
        }
        if run_facts
        else {}
    )
    runs = [
        dict(
            activity_id=f.activity_id,
            local_date=f.local_date,
            sport=f.sport,
            timer_s=f.timer_s,
            distance_m=f.distance_m,
            rpe=effective_rpe(activity_id=f.activity_id, fallback=activities[f.activity_id].workout_rpe)[0],
            rpe_source=effective_rpe(activity_id=f.activity_id, fallback=activities[f.activity_id].workout_rpe)[1],
        )
        for f in run_facts
    ]
    imported_ids = {
        row.target_id
        for row in session.scalars(select(LegacyImportMap).where(LegacyImportMap.source_table == "checkins"))
        if row.target_id
    }
    checkin_rows = [
        row
        for row in session.scalars(
            select(CheckinV2)
            .where(CheckinV2.observed_at >= now - timedelta(days=120), CheckinV2.observed_at <= now)
            .order_by(CheckinV2.observed_at, CheckinV2.id)
        )
        if row.id not in imported_ids
    ]
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
        symptoms.setdefault(row.checkin_id, []).append(_view(row, ("site", "side", "severity", "timing")))
    checkins = [
        dict(
            _view(row, ("kind", "observed_at", "fatigue", "illness", "gait_change", "activity_id")),
            checkin_id=row.id,
            local_date=row.observed_at.astimezone(zone).date(),
            symptoms=symptoms.get(row.id, []),
        )
        for row in checkin_rows
    ]
    legacy_rows = session.scalars(
        select(LegacyCheckin)
        .where(LegacyCheckin.observed_at >= now - timedelta(hours=72), LegacyCheckin.observed_at <= now)
        .order_by(LegacyCheckin.observed_at, LegacyCheckin.id)
    ).all()
    legacy = [
        dict(
            schema_version=1,
            id=row.id,
            version=row.version,
            observed_at=row.observed_at,
            activity_id=row.activity_id,
            symptoms=row.symptoms,
            change=row.change,
            gait=row.gait,
            feeling=row.feeling,
            effort=row.effort,
            severity_numeric=None,
        )
        for row in legacy_rows
    ]
    prompt_rows = session.scalars(
        select(Prompt)
        .where(Prompt.opens_at >= now - timedelta(days=120), Prompt.opens_at <= now)
        .order_by(Prompt.opens_at, Prompt.id)
    ).all()
    prompts = [
        _view(row, ("id", "kind", "activity_id", "status", "opens_at", "closes_at"), names={"id": "prompt_id"})
        for row in prompt_rows
    ]
    metric_keys = (
        {f"w{n}:{as_of.isoformat()}" for n in (7, 14, 28, 56, 84)}
        | {f"w{n}:{as_of.isoformat()}:{kind}" for n in (7, 14, 28, 56, 84) for kind in ("run", "strength")}
        | {f"night:{(as_of - timedelta(days=n)).isoformat()}" for n in range(120)}
        | {str(row["activity_id"]) for row in runs}
    )
    metric_rows = session.scalars(
        select(MetricResult)
        .where(MetricResult.is_current.is_(True), MetricResult.subject_key.in_(metric_keys))
        .order_by(MetricResult.metric_id, MetricResult.subject_key, MetricResult.id)
    ).all()
    metrics = [
        _view(
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
    anchor_rows = session.scalars(
        select(IntensityAnchor).order_by(
            IntensityAnchor.valid_from, IntensityAnchor.calibrated_at, IntensityAnchor.anchor_key
        )
    ).all()
    anchors = [
        _view(
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
    block_rows = session.scalars(
        select(BlockVersion).order_by(BlockVersion.block_uid, BlockVersion.version.desc())
    ).all()
    latest_by_uid: dict[uuid.UUID, BlockVersion] = {}
    for block_row in block_rows:
        latest_by_uid.setdefault(block_row.block_uid, block_row)
    active_rows = [row for row in latest_by_uid.values() if row.status in {"active", "consolidating"}]
    active_row = max(active_rows, key=lambda row: (row.created_at, row.version, str(row.id))) if active_rows else None
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
    )
    active_block = (
        dict(
            _view(active_row, block_keys),
            block_uid=active_row.block_uid,
            version_id=active_row.id,
            version=active_row.version,
        )
        if active_row
        else None
    )
    decisions = [
        _view(
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
            _view(change_row, ("change_id", "op", "session_uid", "decision", "before", "after"))
        )
    proposals = [
        dict(
            _view(row, ("operation", "status", "submitted_at", "decided_at", "summary", "follow_up")),
            proposal_id=row.id,
            changes=by_proposal.get(row.id, []),
        )
        for row in proposal_rows
    ]
    goals = [
        _view(row, ("id", "text", "horizon", "priority", "status"), names={"id": "goal_id"})
        for row in session.scalars(select(Goal).where(Goal.status == "active").order_by(Goal.priority, Goal.id))
    ]
    events = [
        _view(
            row, ("id", "name", "event_date", "distance_m", "priority", "status", "result_s"), names={"id": "event_id"}
        )
        for row in session.scalars(
            select(Event).where(Event.event_date >= as_of - timedelta(days=28)).order_by(Event.event_date, Event.id)
        )
    ]
    return SnapshotInputs(
        as_of,
        now,
        zone.key,
        head,
        state.data_revision if state else 0,
        profile.cycle_anchor if profile else None,
        bool(profile.anchor_confirmed) if profile else False,
        (profile.facts or {}).get("clinical_restriction") if profile else None,
        sessions,
        completions,
        slots,
        strong,
        goals,
        events,
        active_block,
        decisions,
        runs,
        checkins,
        legacy,
        prompts,
        metrics,
        anchors,
        proposals,
        coverage(session, first, as_of),
    )


def build_snapshot(
    session: Session, operation: str, as_of: date, *, now: datetime, kb_root: Path | None = None
) -> dict:
    from app.metrics.engine import ensure_nights, ensure_windows

    session.execute(text("SELECT pg_advisory_xact_lock(71382413)"))
    state = session.get(AppState, 1, with_for_update=True, populate_existing=True)
    if state is None or state.planning_authority != "calendar":
        raise DecisionError("planning_not_active", "Calendar planning is not active", 409)
    previous_now = session.info.get("metrics_now", _MISSING)
    session.info["metrics_now"] = now
    try:
        ensure_windows(session, as_of)
        if operation in {DAILY, ROLLING, QUALITY_OP, BLOCK}:
            days = {DAILY: 3, ROLLING: 14, QUALITY_OP: 14, BLOCK: 28}[operation]
            ensure_nights(session, as_of - timedelta(days=days - 1), as_of)
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
        payload["legacy_checkins"] = decision["source_versions"]["legacy_checkins"]
        meta = payload["snapshot_meta"]
        meta["source_fingerprint"] = decision["source_fingerprint"]
        meta["source_versions"] = decision["source_versions"]
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
        if previous_now is _MISSING:
            session.info.pop("metrics_now", None)
        else:
            session.info["metrics_now"] = previous_now
    return {
        "snapshot_id": str(row.id),
        "payload": payload,
        "kb": {"package_version": bundle.package_version, "excerpts": [e.to_json() for e in bundle.excerpts]},
        "approx_tokens": approx_tokens,
    }
