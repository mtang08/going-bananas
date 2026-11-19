"""Bounded, source-aware coach snapshot projections."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.calendar_models import SessionCompletion
from app.checkin_models import Checkin as CheckinV2
from app.checkin_models import SessionRpe, SymptomReport
from app.coach_v2_models import CoachProposal, CoachProposalChange, CoachSnapshot
from app.domain.athlete_facts import clinical_restriction
from app.domain.session_class import LONG_RECIPE, QUALITY_CLASSES, QUALITY_RECIPES, classify, expected_rpe, rpe_mismatch
from app.metric_models import MetricResult, Prompt
from app.models import Activity, AppState, ProfileVersion
from app.planning_models import (
    BlockBenchmarkResult,
    BlockDecision,
    BlockVersion,
    Event,
    Goal,
    IntensityAnchor,
    StrengthRoutineSlot,
)
from app.services.block_benchmark import active_block_version
from app.services.calendar import state_at
from app.services.calendar_structure import work_signature
from app.services.coverage import coverage
from app.services.decision_inputs import VerifiedKnowledge, canonical_json, collect_decision_inputs
from app.services.exceptions.vocab import NON_TERMINAL_FINDING, RULE_VERSION
from app.services.knowledge import CONDITIONAL_TOPICS, load_route, verify_selection
from app.services.operations import OPERATIONS
from app.services.proposals import DecisionError, derive_certainty, is_quality_slot, scope
from app.services.run_rpe import effective_run_rpe
from app.services.timezone import athlete_tz
from app.services.workout_progression import assemble_groups, session_point
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
EXCEPTION = "exception_review"
POST_EVENT = "post_event_review"
OPEN_FINDINGS_MAX = 20
FINDING_EVIDENCE_MAX = 5
OPEN_PATCHES_MAX = 5
RECENT_RPE_MAX = 14
SUMMARY_FINDINGS_MAX = 30
SUMMARY_PATCHES_MAX = 10
SUMMARY_DAYS = 14
LIVE_PATCH = ("open", "escalated")
BENCHMARK_HISTORY_MAX = 6
PROGRESSION_GROUPS_MAX = 3
PROGRESSION_POINTS_MAX = 4
AEROBIC_RECENT_MAX = 5
PROGRESSION_POINT_KEYS = ("local_date", "activity_id", "status", "reason_codes", "n_planned", "n_completed",
                          "work_speed_mps", "work_hr_bpm", "work_m_per_beat", "cv_speed",
                          "last_first_change_pct", "target_coverage", "sport")


def _view(row: Any, keys: tuple[str, ...], *, names: dict[str, str] | None = None) -> dict:
    names = names or {}
    return {names.get(key, key): row.get(key) if isinstance(row, dict) else getattr(row, key) for key in keys}


def _wire(value: Any) -> Any:
    return json.loads(canonical_json(value))


def _source_provenance(source_versions: dict[str, Any]) -> dict[str, Any]:
    """Summarize the stored source vector without repeating its records in the coach input."""
    collections = {}
    for key, value in source_versions.items():
        if isinstance(value, list):
            kind, count = "array", len(value)
        elif isinstance(value, dict):
            kind, count = "object", len(value)
        else:
            kind, count = "scalar", 0 if value is None else 1
        collections[key] = {"kind": kind, "count": count}
    return {
        "sha256": hashlib.sha256(canonical_json(source_versions).encode()).hexdigest(),
        "collections": collections,
    }


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
    exception_findings: list[dict] = field(default_factory=list)
    exception_patches: list[dict] = field(default_factory=list)
    review_recommended: list[dict] = field(default_factory=list)
    benchmark_history: list[dict] = field(default_factory=list)


def _window(operation: str, section: str, inputs: SnapshotInputs) -> tuple[date, date]:
    day = inputs.as_of
    if section == "calendar":
        if operation in {RACE, POST_EVENT}:
            return day, day + timedelta(days=13)
        if operation == EXCEPTION:
            return day - timedelta(days=7), day + timedelta(days=6)
        return (
            day - timedelta(days={DAILY: 3, ROLLING: 14, QUALITY_OP: 14, BLOCK: 28}[operation]),
            day + timedelta(days=3 if operation == DAILY else 13),
        )
    if section == "exposures":
        return day - timedelta(
            days={DAILY: 2, ROLLING: 13, QUALITY_OP: 13, BLOCK: 27, RACE: 13, CALIB: 83, EXCEPTION: 2, POST_EVENT: 13}[
                operation
            ]
        ), day
    if section == "symptoms":
        days = 14 if operation in {DAILY, EXCEPTION} else 28
        if operation == BLOCK and inputs.active_block:
            return _day(inputs.active_block["start_date"]), day
        return day - timedelta(days=days - 1), day
    if section == "recovery":
        days = {DAILY: 3, ROLLING: 14, QUALITY_OP: 14, BLOCK: 28, EXCEPTION: 3, POST_EVENT: 14}[operation]
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
    result["modification_reason"] = completion.get("modification_reason") if completion else None
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
        "window_days": {DAILY: 3, ROLLING: 14, QUALITY_OP: 14, BLOCK: 28, RACE: 14, EXCEPTION: 3, POST_EVENT: 14}[operation],
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
        decided = {"accepted", "partially_accepted", "rejected"}
        proposals = [p for p in proposals if p.get("operation") == ROLLING and p.get("status") in decided][:2] + [
            p for p in proposals if p.get("operation") == EXCEPTION and p.get("status") in decided][:3]
    else:
        proposals = proposals[:3]
    result = []
    completions = {str(c["session_uid"]): c for c in inputs.completions}
    patch_status = {str(p["proposal_id"]): p["status"] for p in inputs.exception_patches}
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
        if proposal.get("operation") == EXCEPTION:
            view["patch_status"] = patch_status.get(str(proposal.get("proposal_id")))
        result.append(view)
    return result


def _site_key(symptom: dict) -> str:
    return f"{str(symptom.get('site') or '').strip().lower()}|{symptom.get('side')}"


def _rpe_rows(inputs: SnapshotInputs) -> list[dict]:
    start = inputs.as_of - timedelta(days=SUMMARY_DAYS - 1)
    by_activity = {str(c["activity_id"]): c for c in inputs.completions if c.get("activity_id")}
    sessions = {str(s["session_uid"]): s for s in inputs.sessions}
    rows = []
    for run in inputs.runs:
        if not _between(run.get("local_date"), start, inputs.as_of):
            continue
        completion = by_activity.get(str(run["activity_id"]))
        planned = sessions.get(str(completion["session_uid"])) if completion else None
        recipe = planned.get("recipe_id") if planned else None
        cls = classify(planned["kind"], recipe, planned.get("intent")) if planned else None
        rpe = float(run["rpe"]) if run.get("rpe") is not None else None
        expected = expected_rpe(recipe, cls) if cls else None
        rows.append({"activity_id": run["activity_id"], "local_date": run["local_date"], "class": cls, "rpe": rpe,
                     "rpe_source": run.get("rpe_source"), "expected_rpe": list(expected) if expected else None,
                     "mismatch": rpe_mismatch(cls, recipe, rpe) if cls else None})
    rows.sort(key=lambda r: (str(r["local_date"]), str(r["activity_id"])), reverse=True)
    return rows


def _exceptions_section(inputs: SnapshotInputs) -> dict:
    last = inputs.as_of + timedelta(days=6)
    findings = sorted(
        (f for f in inputs.exception_findings if f.get("status") in NON_TERMINAL_FINDING),
        key=lambda f: (str(f.get("first_seen_at")), str(f.get("id"))),
        reverse=True,
    )[:OPEN_FINDINGS_MAX]
    patches = sorted(
        (p for p in inputs.exception_patches if p.get("status") in LIVE_PATCH),
        key=lambda p: (str(p.get("created_at")), str(p.get("id"))),
        reverse=True,
    )[:OPEN_PATCHES_MAX]
    upcoming = []
    for row in sorted(
        (s for s in inputs.sessions if _between(s.get("local_date"), inputs.as_of, last)),
        key=lambda s: (str(s["local_date"]), s.get("slot") or 0, str(s["session_uid"])),
    ):
        cls = classify(row.get("kind") or "", row.get("recipe_id"), row.get("intent"))
        expected = expected_rpe(row.get("recipe_id"), cls)
        upcoming.append({
            "session_uid": row["session_uid"],
            "local_date": row["local_date"],
            "kind": row.get("kind"),
            "class": cls,
            "expected_rpe": list(expected) if expected else None,
            "certainty": row.get("certainty"),
        })
    return {
        "rule_version": RULE_VERSION,
        "review_recommended": list(inputs.review_recommended),
        "open_findings": [{**f, "evidence": list(f.get("evidence") or [])[:FINDING_EVIDENCE_MAX]} for f in findings],
        "open_patches": patches,
        "upcoming": upcoming,
        "recent_rpe": _rpe_rows(inputs)[:RECENT_RPE_MAX],
    }


def _quality_sessions(inputs: SnapshotInputs, start: date) -> dict:
    def cls_of(row: dict) -> str:
        return classify(row.get("kind") or "", row.get("recipe_id"), row.get("intent"))

    completions = {str(c["session_uid"]): c for c in inputs.completions}
    head = [
        s for s in inputs.sessions
        if _between(s.get("local_date"), start, inputs.as_of) and cls_of(s) in QUALITY_CLASSES
    ]
    removed = modified = 0
    for proposal in inputs.proposals:
        if proposal.get("operation") != EXCEPTION:
            continue
        for change in proposal.get("changes", []):
            if change.get("decision") != "accepted":
                continue
            before = change.get("before") or {}
            if not _between(before.get("local_date"), start, inputs.as_of) or cls_of(before) not in QUALITY_CLASSES:
                continue
            after_cls = cls_of({**before, **(change.get("after") or {})})
            if change.get("op") == "delete" or after_cls not in QUALITY_CLASSES:
                removed += 1
            elif change.get("op") in {"modify", "move"}:
                modified += 1
    since = inputs.now - timedelta(days=SUMMARY_DAYS)
    return {
        "planned": len(head) + removed,
        "completed_as_planned": sum(
            1 for s in head
            if (completions.get(str(s["session_uid"])) or {}).get("status") == "completed_as_planned"
        ),
        "modified_by_patch": modified,
        "removed_by_patch": removed,
        "failed": sum(
            1 for f in inputs.exception_findings
            if f.get("rule_code") == "SESSION_FAILED" and _instant(f["first_seen_at"]) >= since
        ),
    }


def _exception_summary(inputs: SnapshotInputs) -> dict:
    start = inputs.as_of - timedelta(days=SUMMARY_DAYS - 1)
    since = inputs.now - timedelta(days=SUMMARY_DAYS)
    reviews = [
        _instant(p["decided_at"])
        for p in inputs.proposals
        if p.get("operation") in {ROLLING, BLOCK}
        and p.get("status") in {"accepted", "partially_accepted"}
        and p.get("decided_at")
    ]
    findings = sorted(
        (
            f for f in inputs.exception_findings
            if f.get("status") in NON_TERMINAL_FINDING or _instant(f["first_seen_at"]) >= since
        ),
        key=lambda f: (str(f.get("first_seen_at")), str(f.get("id"))),
        reverse=True,
    )[:SUMMARY_FINDINGS_MAX]
    patches = [
        p for p in inputs.exception_patches
        if p.get("status") in LIVE_PATCH or _day(p["window_end"]) >= start
    ][:SUMMARY_PATCHES_MAX]
    mismatch = {"easy_above": 0, "long_above": 0, "quality_above": 0, "quality_below": 0}
    for row in _rpe_rows(inputs):
        key = f"{row['class']}_{row['mismatch']}"
        if key in mismatch:
            mismatch[key] += 1
    days_by_site: dict[str, set[date]] = {}
    for checkin in inputs.checkins:
        if _between(checkin.get("local_date"), start, inputs.as_of):
            for symptom in checkin.get("symptoms", []):
                days_by_site.setdefault(_site_key(symptom), set()).add(_day(checkin["local_date"]))
    sites: list[dict[str, Any]] = sorted(
        ({"site_key": key, "distinct_days_14": len(days)} for key, days in days_by_site.items() if len(days) >= 2),
        key=lambda s: (-s["distinct_days_14"], s["site_key"]),
    )
    finding_keys = ("id", "rule_code", "category", "severity", "status", "first_seen_at", "summary",
                    "is_new_since_last_review")
    patch_keys = ("id", "category", "severity", "window_start", "window_end", "status", "reassess_on")
    return {
        "window_start": start,
        "window_end": inputs.as_of,
        "since_last_review": max(reviews).astimezone(ZoneInfo(inputs.timezone)).date() if reviews else None,
        "findings": [_view(f, finding_keys) for f in findings],
        "patches": [dict(_view(p, patch_keys), changes_count=len(p.get("session_uids") or [])) for p in patches],
        "rpe_mismatch": mismatch,
        "quality_sessions": _quality_sessions(inputs, start),
        "recurring_symptom_sites": sites,
        "open_escalations": sum(
            1 for f in inputs.exception_findings
            if f.get("status") in NON_TERMINAL_FINDING and f.get("severity") == "escalate"
        ),
    }


def _event_payload(inputs: SnapshotInputs, event: dict | None, day: date, activity_id: Any) -> dict:
    if activity_id is not None:
        candidates = [r for r in inputs.runs if str(r["activity_id"]) == str(activity_id)]
    else:
        candidates = [r for r in inputs.runs if r.get("local_date") is not None and _day(r["local_date"]) == day]
    run = max(candidates, key=lambda r: (r.get("distance_m") or 0, str(r["activity_id"])), default=None)
    matched = None
    if run is not None:
        start_at = run.get("start_at")
        matched = {
            "id": run["activity_id"],
            "start_local": _instant(start_at).astimezone(ZoneInfo(inputs.timezone)).isoformat() if start_at else None,
            "distance_m": run.get("distance_m"),
            "duration_s": run.get("timer_s"),
            "rpe": run.get("rpe"),
            "rpe_source": run.get("rpe_source"),
        }
    last = day + timedelta(days=3)
    checkins = [
        {
            **_view(c, ("observed_at", "kind", "fatigue", "illness", "gait_change")),
            "symptoms": [
                {"site_key": _site_key(s), "severity": s.get("severity"), "timing": s.get("timing")}
                for s in c.get("symptoms", [])
            ],
        }
        for c in inputs.checkins
        if _between(c.get("local_date"), day, last)
    ]
    nights = [
        _metric_view(m)
        for m in inputs.metric_results
        if m.get("metric_id") == "recovery_multisignal_summary"
        and m.get("subject_type") == "night"
        and str(m.get("subject_key", "")).startswith("night:")
        and _between(str(m["subject_key"]).split(":", 1)[1], day - timedelta(days=1), last)
    ]
    event_keys = ("event_id", "name", "event_date", "distance_m", "priority", "status", "result_s")
    return {
        "event": _view(event, event_keys, names={"event_id": "id"}) if event else None,
        "matched_activity": matched,
        "checkins_after": checkins,
        "recovery_nights": nights,
    }


def _event_section(inputs: SnapshotInputs) -> dict | None:
    due = {
        str(f.get("entity_key") or "").removeprefix("event:")
        for f in inputs.exception_findings
        if f.get("rule_code") == "POST_EVENT_REVIEW_DUE" and f.get("status") in NON_TERMINAL_FINDING
    }
    events = [e for e in inputs.events if str(e.get("event_id")) in due]
    if not events:
        return None
    event = max(events, key=lambda e: (str(e.get("event_date")), str(e.get("event_id"))))
    return _event_payload(inputs, event, _day(event["event_date"]), None)


def _benchmark_event(inputs: SnapshotInputs) -> dict | None:
    status = (inputs.active_block or {}).get("benchmark_status")
    if not status or status.get("status") != "completed":
        return None
    event = next((e for e in inputs.events if str(e.get("event_id")) == str(status.get("event_id"))), None)
    return _event_payload(inputs, event, _day(status["local_date"]), status.get("activity_id"))


def _quality_progression(inputs: SnapshotInputs, operation: str) -> list[dict]:
    cal_start, cal_end = _window(operation, "calendar", inputs)
    ordered = sorted(inputs.sessions, key=lambda s: (str(s["local_date"]), s.get("slot", 0), str(s["session_uid"])))
    signatures = {str(s["session_uid"]): work_signature(s.get("structure")) for s in ordered if s.get("kind") == "run"}
    wanted = list(dict.fromkeys(
        sig for s in ordered
        if (sig := signatures.get(str(s["session_uid"]))) and _between(s.get("local_date"), cal_start, cal_end)
    ))[:PROGRESSION_GROUPS_MAX]
    if not wanted:
        return []
    completions = {str(c["session_uid"]): c for c in inputs.completions}
    runs = {str(r["activity_id"]): r for r in inputs.runs}
    intervals = {str(m["subject_key"]): m for m in inputs.metric_results
                 if m.get("metric_id") == "work_interval_execution"}
    points = []
    for s in ordered:
        if signatures.get(str(s["session_uid"])) not in wanted or _day(s["local_date"]) > inputs.as_of:
            continue
        completion = completions.get(str(s["session_uid"]))
        run = runs.get(str(completion["activity_id"])) if completion and completion.get("activity_id") else None
        row = intervals.get(str(run["activity_id"])) if run else None
        points.append(session_point(
            {"session_uid": s["session_uid"], "local_date": _day(s["local_date"]), "recipe_id": s.get("recipe_id"),
             "intent": s.get("intent"), "structure": s["structure"]},
            completion,
            {"id": run["activity_id"], "local_date": _day(run["local_date"]), "sport": run["sport"]} if run else None,
            {"id": row["result_id"], "status": row["status"], "reason_codes": row["reason_codes"],
             "value": row["value"]} if row else None,
        ))
    groups = {g["signature"]: g for g in assemble_groups(points, "signature")}
    return [
        {"signature": sig, "recipe_ids": groups[sig]["recipe_ids"],
         "sessions_total": groups[sig]["sessions_total"],
         "sessions_assessable": groups[sig]["sessions_assessable"],
         "recent": [_view(p, PROGRESSION_POINT_KEYS) for p in groups[sig]["points"]
                    if p["status"] in ("available", "partial")][-PROGRESSION_POINTS_MAX:]}
        for sig in wanted if sig in groups
    ]


def _aerobic_efficiency(inputs: SnapshotInputs) -> dict:
    rows = {str(m["subject_key"]).split(":", 1)[0]: m for m in inputs.metric_results
            if m.get("metric_id") == "aerobic_efficiency" and m.get("subject_type") == "window"
            and m.get("subject_key") in {f"w28:{inputs.as_of.isoformat()}", f"w84:{inputs.as_of.isoformat()}"}}
    section: dict[str, Any] = {"interpretation": "descriptive_only", "recent_runs": []}
    for key in ("w28", "w84"):
        row = rows.get(key)
        if row is None:
            section[key] = None
            continue
        view = _metric_view(row)
        value = dict(view["value"] or {})
        points = value.pop("points", [])
        view["value"] = value
        section[key] = view
        if key == "w84":
            section["recent_runs"] = list(points)[-AEROBIC_RECENT_MAX:]
    return section


def build_payload(inputs: SnapshotInputs, operation: str) -> dict:
    if operation not in OPERATIONS:
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
        if operation not in {DAILY, EXCEPTION}:
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
    elif operation in {DAILY, EXCEPTION}:
        payload["block"] = _view(block, ("block_uid", "version_id", "objective", "benchmark", "benchmark_status")) if block else None
    elif operation == CALIB:
        payload["block"] = (
            {"objective": block["objective"], "benchmark": block.get("benchmark"),
             "benchmark_status": block.get("benchmark_status")}
            if block
            else None
        )
    else:
        payload["block"] = _view(block, tuple(block)) if block else None
    if operation not in {CALIB}:
        windows = [7] if operation in {DAILY, EXCEPTION} else [7, 14, 28, 56, 84] if operation == BLOCK else [7, 14, 28]
        keys = {f"w{days}:{inputs.as_of.isoformat()}" for days in windows}
        keys.update(f"w{days}:{inputs.as_of.isoformat()}:{kind}" for days in windows for kind in ("run", "strength"))
        payload["load_shape"] = [
            _metric_view(m)
            for m in inputs.metric_results
            if m.get("subject_type") == "window" and m.get("subject_key") in keys
            and m.get("metric_id") != "aerobic_efficiency"
        ]
    if operation not in {RACE}:
        quality_runs = [r for r in payload["completed_exposures"]["runs"] if r["class"] == "quality"]
        if operation in {DAILY, EXCEPTION}:
            quality_runs = quality_runs[-1:]
        exposure_ids = {str(r["activity_id"]) for r in quality_runs}
        execution = [
            _metric_view(m)
            for m in inputs.metric_results
            if m.get("metric_id") == "work_interval_execution" and str(m.get("subject_key")) in exposure_ids
        ]
        payload["execution"] = execution
    if operation in {ROLLING, QUALITY_OP, BLOCK}:
        payload["quality_progression"] = _quality_progression(inputs, operation)
    if operation in {ROLLING, BLOCK}:
        payload["aerobic_efficiency"] = _aerobic_efficiency(inputs)
    if operation not in {CALIB}:
        payload["symptoms"] = _symptoms(inputs, operation)
    if operation in {DAILY, ROLLING, QUALITY_OP, BLOCK, EXCEPTION, POST_EVENT}:
        rec_start, rec_end = _window(operation, "recovery", inputs)
        payload["recovery"] = [
            _metric_view(m)
            for m in inputs.metric_results
            if m.get("metric_id") == "recovery_multisignal_summary"
            and m.get("subject_type") == "night"
            and str(m.get("subject_key", "")).startswith("night:")
            and _between(str(m["subject_key"]).split(":", 1)[1], rec_start, rec_end)
        ]
    if operation in {DAILY, ROLLING, QUALITY_OP, BLOCK, CALIB, EXCEPTION, POST_EVENT}:
        payload["prior_decisions"] = _prior_decisions(inputs, operation)
    if operation in {EXCEPTION, POST_EVENT}:
        payload["exceptions"] = _exceptions_section(inputs)
    if operation in {ROLLING, BLOCK}:
        payload["exception_summary"] = _exception_summary(inputs)
    if operation == POST_EVENT:
        payload["event"] = _event_section(inputs)
    if operation == BLOCK:
        payload["benchmark_history"] = list(inputs.benchmark_history)
        if (benchmark_event := _benchmark_event(inputs)) is not None:
            payload["event"] = benchmark_event
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
    symptom_start, symptom_end = _window(operation if operation not in {CALIB, RACE, POST_EVENT} else DAILY, "symptoms", inputs)
    recent_checkins = [c for c in inputs.checkins if _between(c.get("local_date"), symptom_start, symptom_end)]
    ptt = any(c.get("symptoms") for c in recent_checkins) or any(
        p.get("kind") == "delayed_symptom"
        and p.get("status") == "answered"
        and _between(_instant(p["opens_at"]).date(), symptom_start, symptom_end)
        for p in inputs.prompts
    )
    rec_start = inputs.as_of - timedelta(
        days=(3 if operation in {DAILY, EXCEPTION} else 14 if operation in {CALIB, RACE, POST_EVENT, ROLLING, QUALITY_OP} else 28) - 1
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
        operation in {BLOCK, RACE, POST_EVENT},
        operation in {RACE, POST_EVENT},
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


def _effective_rpe(rpe_rows: Sequence[SessionRpe], strong_id: Any) -> Any:
    matched = [r for r in rpe_rows if r.strong_workout_id == strong_id]
    preferred = next((r for r in reversed(matched) if r.source == "manual"), None) or next(
        (r for r in reversed(matched) if r.source == "garmin_fit"), None
    )
    return preferred.rpe if preferred else None


def _load_sessions(session: Session, head: int, first: date, as_of: date) -> list[dict]:
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
    return sessions


def _load_completions(session: Session) -> list[dict]:
    completion_rows = session.scalars(select(SessionCompletion)).all()
    completions = [
        _view(row, ("session_uid", "status", "activity_id", "strong_workout_id", "manual_session_id", "modification_reason"))
        for row in completion_rows
    ]
    return completions


def _load_strength_slots(session: Session) -> list[dict]:
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
    return slots


def _load_strong_workouts(strong_rows: Sequence[StrongWorkoutRow], rpe_rows: Sequence[SessionRpe]) -> list[dict]:
    strong = [
        dict(
            _view(row, ("local_date", "workout_name", "duration_s")),
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
    from app.calendar_models import LegacyImportMap

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
    return checkins


def _load_legacy_checkins(session: Session, now: datetime) -> list[dict]:
    from app.models import Checkin as LegacyCheckin

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
    return legacy


def _load_prompts(session: Session, now: datetime) -> list[dict]:
    prompt_rows = session.scalars(
        select(Prompt)
        .where(Prompt.opens_at >= now - timedelta(days=120), Prompt.opens_at <= now)
        .order_by(Prompt.opens_at, Prompt.id)
    ).all()
    prompts = [
        _view(row, ("id", "kind", "activity_id", "status", "opens_at", "closes_at"), names={"id": "prompt_id"})
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
    return metrics


def _load_anchors(session: Session) -> list[dict]:
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
            _view(active_row, block_keys),
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
    return proposals


def _load_goals(session: Session) -> list[dict]:
    goals = [
        _view(row, ("id", "text", "horizon", "priority", "status"), names={"id": "goal_id"})
        for row in session.scalars(select(Goal).where(Goal.status == "active").order_by(Goal.priority, Goal.id))
    ]
    return goals


def _load_events(session: Session, as_of: date) -> list[dict]:
    events = [
        _view(
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
    profile = session.scalars(select(ProfileVersion).order_by(ProfileVersion.version.desc()).limit(1)).first()
    head = state.calendar_head_version if state else 0
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
    legacy = _load_legacy_checkins(session, now)
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
    return SnapshotInputs(
        as_of=as_of, now=now, timezone=zone.key, calendar_version=head,
        data_revision=state.data_revision if state else 0,
        cycle_anchor=profile.cycle_anchor if profile else None,
        anchor_confirmed=bool(profile.anchor_confirmed) if profile else False,
        clinical_restriction=clinical_restriction(profile.facts) if profile else None,
        sessions=sessions, completions=completions, strength_slots=slots, strong_workouts=strong,
        goals=goals, events=events, active_block=active_block, block_decisions=decisions,
        runs=runs, checkins=checkins, legacy_checkins=legacy, prompts=prompts,
        metric_results=metrics, anchors=anchors, proposals=proposals, coverage=coverage(session, first, as_of),
        exception_findings=exception_findings, exception_patches=exception_patches,
        review_recommended=_load_review_recommended(session, as_of), benchmark_history=benchmark_history,
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
        payload["legacy_checkins"] = decision["source_versions"]["legacy_checkins"]
        meta = payload["snapshot_meta"]
        meta["source_fingerprint"] = decision["source_fingerprint"]
        meta["source_provenance"] = _source_provenance(decision["source_versions"])
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
