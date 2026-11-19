"""Stable, verified source facts for coaching decisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar_models import SessionCompletion
from app.checkin_models import SessionRpe
from app.domain.athlete_facts import clinical_restriction
from app.fit_models import FitFile
from app.metrics.contract import completion_association_hash
from app.models import (
    Activity,
    ActivityAnnotation,
    ActivitySource,
    CoverageInterval,
    ManualSession,
    RawObject,
    RecoveryObservation,
    SourceRecord,
)
from app.planning_models import Event, Goal, IntensityAnchor, StrengthRoutineSlot
from app.read.calendar import head_version
from app.services.block_benchmark import active_block_version
from app.services.profile import current_profile
from app.strong_models import StrongWorkoutRow


@dataclass(frozen=True)
class VerifiedKnowledge:
    digest: str
    selection: tuple[dict, ...]
    selected_records: tuple[dict, ...]
    policy_ids: frozenset[str]
    recipe_ids: frozenset[str]
    evidence_ids: frozenset[str]


KnowledgeResolver = Callable[[tuple[dict, ...]], VerifiedKnowledge]


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=_json_default
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive_source_instant")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def fingerprint_vector(source_versions: dict, kb: VerifiedKnowledge) -> dict:
    return {
        "source_versions": source_versions,
        "knowledge": {
            "digest": kb.digest,
            "selection": list(kb.selection),
            "selected_records": list(kb.selected_records),
        },
    }


def fingerprint(source_versions: dict, kb: VerifiedKnowledge) -> str:
    return digest(fingerprint_vector(source_versions, kb))


def _wire(value: Any) -> Any:
    return json.loads(canonical_json(value))


def _project(rows: list[Any], fields: tuple[str, ...]) -> list[dict]:
    return [_wire({field: getattr(row, field) for field in fields}) for row in rows]


def _sorted(session: Session, model: Any, key: Any) -> list[Any]:
    return list(session.scalars(select(model).order_by(key)))


def collect_decision_inputs(
    session: Session, operation: str, as_of: date, *, now: datetime, kb: VerifiedKnowledge
) -> dict:
    from app.checkin_models import Checkin as CheckinV2
    from app.checkin_models import SymptomReport

    profile = current_profile(session)
    checkins = _sorted(session, CheckinV2, CheckinV2.id)
    checkin_ids = {row.id for row in checkins}
    symptoms = [row for row in _sorted(session, SymptomReport, SymptomReport.id) if row.checkin_id in checkin_ids]
    recent_ids = {row.id for row in checkins if now - timedelta(hours=72) <= row.observed_at <= now}
    recent_symptoms = [row for row in symptoms if row.checkin_id in recent_ids]
    max_severity = max((float(row.severity) for row in recent_symptoms if row.severity is not None), default=None)
    gait_yes = any(getattr(row, "gait_change", None) == "yes" for row in checkins if row.id in recent_ids)
    illness = any(getattr(row, "illness", None) == "present" for row in checkins if row.id in recent_ids)
    clinical = clinical_restriction(profile.facts) is not None if profile else False
    guard = {
        "window_hours": 72,
        "gait_change_yes": gait_yes,
        "max_symptom_severity": max_severity,
        "illness_present": illness,
        "clinical_restriction_active": clinical,
    }
    activities = _sorted(session, Activity, Activity.id)
    annotations = _sorted(session, ActivityAnnotation, ActivityAnnotation.id)
    source_versions: dict[str, Any] = {
        "operation": operation,
        "as_of": as_of.isoformat(),
        "profile": {
            "version": profile.version,
            "timezone": profile.timezone,
            "facts_hash": digest(profile.facts or {}),
            "preferences_hash": digest(profile.preferences or {}),
            "unknowns_hash": digest(profile.unknowns or []),
        }
        if profile
        else None,
        "calendar": head_version(session),
        "block": None,
        "routine": max((r.version for r in _sorted(session, StrengthRoutineSlot, StrengthRoutineSlot.id)), default=0),
        "activities": _project(
            activities,
            (
                "id",
                "canonical_revision",
                "resolution_state",
                "fit_status",
                "fit_file_id",
                "field_provenance",
                "start_at",
                "local_date",
                "distance_m",
                "timer_s",
                "workout_rpe",
            ),
        ),
        "checkins": _project(
            checkins,
            (
                "id",
                "version",
                "observed_at",
                "activity_id",
                "gait_change",
                "illness",
                "fatigue",
                "kind",
                "context_tags",
            ),
        ),
        "recovery": _project(
            _sorted(session, RecoveryObservation, RecoveryObservation.id),
            ("id", "metric", "source_date", "value", "source_revision"),
        ),
        "goals": _project(_sorted(session, Goal, Goal.id), ("id", "version", "status", "text")),
        "coverage": _project(
            _sorted(session, CoverageInterval, CoverageInterval.id),
            ("id", "dataset", "start_date", "end_date", "status", "fully_enumerated"),
        ),
        "anchors": _project(
            _sorted(session, IntensityAnchor, IntensityAnchor.id),
            (
                "anchor_key",
                "kind",
                "status",
                "value_low",
                "value_high",
                "unit",
                "protocol",
                "confidence",
                "valid_from",
                "review_after",
                "supersedes_key",
            ),
        ),
    }
    if annotations:
        source_versions["annotations"] = _project(annotations, ("activity_id", "version", "workout_label", "excluded"))
    if symptoms:
        source_versions["symptoms"] = _project(symptoms, ("checkin_id", "site", "side", "severity", "timing"))
    source_versions["fit_files"] = _project(
        _sorted(session, FitFile, FitFile.id),
        ("activity_id", "raw_object_id", "zip_sha256", "fit_sha256"),
    )
    source_versions["activity_sources"] = _project(
        _sorted(session, ActivitySource, ActivitySource.id), ("activity_id", "source_record_id", "selected_fields")
    )
    selected_source_ids = {row.source_record_id for row in _sorted(session, ActivitySource, ActivitySource.id)}
    selected_source_ids.update(
        row.source_record_id
        for row in _sorted(session, RecoveryObservation, RecoveryObservation.id)
        if row.source_record_id
    )
    selected_source_ids.update(row.source_record_id for row in _sorted(session, StrongWorkoutRow, StrongWorkoutRow.id))
    selected_records = [row for row in _sorted(session, SourceRecord, SourceRecord.id) if row.id in selected_source_ids]
    source_versions["source_records"] = _project(
        selected_records, ("id", "source_identity", "payload_hash", "raw_object_id", "parser_version")
    )
    selected_raw_ids = {row.raw_object_id for row in selected_records if row.raw_object_id}
    selected_raw_ids.update(row.raw_object_id for row in _sorted(session, FitFile, FitFile.id))
    selected_raw_ids.update(row.raw_object_id for row in _sorted(session, StrongWorkoutRow, StrongWorkoutRow.id))
    source_versions["raw_objects"] = _project(
        [row for row in _sorted(session, RawObject, RawObject.id) if row.id in selected_raw_ids], ("id", "sha256")
    )
    source_versions["completions"] = [
        completion_association_hash(row) for row in _sorted(session, SessionCompletion, SessionCompletion.id)
    ]
    source_versions["session_rpe"] = _project(
        _sorted(session, SessionRpe, SessionRpe.id),
        (
            "id",
            "activity_id",
            "strong_workout_id",
            "manual_session_id",
            "rpe",
            "source",
            "collected_at",
            "collection_delay_s",
        ),
    )
    source_versions["manual_sessions"] = _project(
        _sorted(session, ManualSession, ManualSession.id),
        ("id", "version", "date", "kind", "duration_s", "effort", "linked_activity_id"),
    )
    source_versions["strong_workouts"] = _project(
        _sorted(session, StrongWorkoutRow, StrongWorkoutRow.id),
        ("id", "payload_hash", "source_record_id", "raw_object_id", "resolution_state", "local_date"),
    )
    source_versions["routine_slots"] = _project(
        _sorted(session, StrengthRoutineSlot, StrengthRoutineSlot.id),
        (
            "id",
            "version",
            "active",
            "label",
            "default_weekday",
            "lower_body_cost",
            "typical_duration_s",
            "main_lower_body_lifts",
        ),
    )
    events = _sorted(session, Event, Event.id)
    if events:
        source_versions["events"] = _project(events, ("id", "version", "event_date", "status", "priority"))
    block = active_block_version(session)
    if block:
        source_versions["block"] = {"id": block.id, "version": block.version, "status": block.status}
    if profile:
        source_versions["profile"]["recurrence"] = {
            "cycle_anchor": profile.cycle_anchor,
            "anchor_confirmed": profile.anchor_confirmed,
            "scheduled_strength_days": profile.scheduled_strength_days,
            "strength_schedule_mode": profile.strength_schedule_mode,
            "strength_week_a_start": profile.strength_week_a_start,
            "strength_week_a_days": profile.strength_week_a_days,
            "strength_week_b_days": profile.strength_week_b_days,
            "mobility_week_a_days": profile.mobility_week_a_days,
            "mobility_week_b_days": profile.mobility_week_b_days,
            "mobility_optional_days": profile.mobility_optional_days,
        }
    source_versions = _wire(source_versions)
    return {
        "source_versions": source_versions,
        "source_fingerprint": fingerprint(source_versions, kb),
        "safety_guard": guard,
    }
