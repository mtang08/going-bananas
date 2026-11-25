"""Snapshot common."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.services.decision_inputs import canonical_json, digest

DRILL_DOWN_QUERIES = ["activity_execution", "long_run_history", "recovery_nights", "calendar_diff", "explain_metric"]
DATASETS = ("activities", "sleep", "hrv", "resting_hr")
SNAPSHOT_SCHEMA = "coach_snapshot.v1"
MISSING = object()
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
KEY_SESSIONS_MAX = 4
NOT_DONE_MAX = 6
UNPLANNED_MAX = 4
WEEKLY_DIGEST_MAX_CHARS = 10_500
PROGRESSION_POINT_KEYS = (
    "local_date",
    "activity_id",
    "status",
    "reason_codes",
    "n_planned",
    "n_completed",
    "work_speed_mps",
    "work_hr_bpm",
    "work_m_per_beat",
    "cv_speed",
    "last_first_change_pct",
    "target_coverage",
    "sport",
)


def row_view(row: Any, keys: tuple[str, ...], *, names: dict[str, str] | None = None) -> dict:
    names = names or {}
    return {names.get(key, key): row.get(key) if isinstance(row, dict) else getattr(row, key) for key in keys}


def to_wire(value: Any) -> Any:
    return json.loads(canonical_json(value))


def source_provenance(source_versions: dict[str, Any]) -> dict[str, Any]:
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
        "sha256": digest(source_versions),
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


def strip_private(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_private(item)
            for key, item in value.items()
            if not any(term in str(key).lower() for term in _PRIVATE_KEYS)
        }
    if isinstance(value, list):
        return [strip_private(item) for item in value]
    return value


def parse_day(value: Any) -> date:
    return date.fromisoformat(value) if isinstance(value, str) else value


def parse_instant(value: Any) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value


def day_between(day: Any, first: date, last: date) -> bool:
    return day is not None and first <= parse_day(day) <= last


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
    running_restriction: dict | None = None
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
    prompts: list[dict] = field(default_factory=list)
    metric_results: list[dict] = field(default_factory=list)
    anchors: list[dict] = field(default_factory=list)
    proposals: list[dict] = field(default_factory=list)
    coverage: list[dict] = field(default_factory=list)
    exception_findings: list[dict] = field(default_factory=list)
    exception_patches: list[dict] = field(default_factory=list)
    review_recommended: list[dict] = field(default_factory=list)
    benchmark_history: list[dict] = field(default_factory=list)
    weekly_digest: list[dict] = field(default_factory=list)
    confirmed_strength_sessions: list[dict] = field(default_factory=list)
    accepted_strength_omissions: list[dict] = field(default_factory=list)
    trips: list[dict] = field(default_factory=list)
    travel_meta: dict = field(default_factory=dict)
