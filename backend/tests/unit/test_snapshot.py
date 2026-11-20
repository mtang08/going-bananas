"""Pure snapshot projection and knowledge routing contract."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest

from app.services.decision_inputs import canonical_json
from app.services.knowledge import POLICY_MAP, load_manifest, load_route
from app.services.proposals.schema import scope
from app.services.snapshot.common import (
    BLOCK,
    CALIB,
    DAILY,
    EXCEPTION,
    POST_EVENT,
    PROGRESSION_POINT_KEYS,
    QUALITY_OP,
    RACE,
    ROLLING,
    WEEKLY_DIGEST_MAX_CHARS,
    SnapshotInputs,
)
from app.services.snapshot.payload import build_payload
from app.services.snapshot.topics import select_conditional_topics, select_recipe_ids

AS_OF = date(2026, 11, 16)
NOW = datetime(2026, 11, 16, 15, tzinfo=UTC)


def inputs(**overrides) -> SnapshotInputs:
    base = SnapshotInputs(AS_OF, NOW, "America/New_York", 7, 2, AS_OF, True, None)
    return replace(base, **overrides)


def session(
    day: date, kind: str, recipe: str | None = None, *, slot_id: str | None = None, placeholder: bool = False
) -> dict:
    return {
        "session_uid": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{day}:{kind}:{recipe}:{slot_id}")),
        "revision": 1,
        "local_date": day,
        "slot": 0,
        "kind": kind,
        "recipe_id": recipe,
        "custom": False,
        "placeholder": placeholder,
        "intent": "Train",
        "certainty": "committed",
        "planned_duration_s": 1800,
        "planned_distance_m": None,
        "structure": None,
        "strength_slot_id": slot_id,
    }


def minimal() -> SnapshotInputs:
    slot = {
        "slot_id": "slot-1",
        "label": "Full body",
        "default_weekday": 1,
        "lower_body_cost": "low",
        "typical_duration_s": 2400,
        "main_lower_body_lifts": ["squat"],
    }
    return inputs(
        sessions=[
            session(AS_OF, "run", "REC001"),
            session(AS_OF + timedelta(days=2), "run", "REC001"),
            session(AS_OF + timedelta(days=1), "strength", slot_id="slot-1"),
            session(AS_OF + timedelta(days=5), "strength", slot_id="slot-1"),
        ],
        strength_slots=[slot],
    )


def finding(
    n: int,
    *,
    rule: str = "FATIGUE_HIGH",
    severity: str = "observe",
    status: str = "open",
    days_ago: int = 0,
    entity: str = "fatigue",
    evidence: int = 8,
) -> dict:
    seen = NOW - timedelta(days=days_ago, minutes=n)
    return {
        "id": f"f{n}",
        "rule_code": rule,
        "category": "accumulated_fatigue",
        "severity": severity,
        "status": status,
        "entity_key": entity,
        "summary": "s",
        "evidence": [{"type": "checkin", "id": str(i), "at": NOW.isoformat(), "detail": {}} for i in range(evidence)],
        "evidence_at": seen,
        "first_seen_at": seen,
        "last_seen_at": seen,
        "patch_id": None,
        "version": 1,
        "is_new_since_last_review": True,
    }


def digest_row(
    n: int,
    *,
    key: bool = False,
    kind: str = "run",
    outcome: str = "completed",
    day: int | None = None,
    execution: dict | None = None,
    actual: dict | None = None,
) -> dict:
    return {
        "session_uid": f"u{n:02d}",
        "local_date": (date(2026, 11, 9) + timedelta(days=day if day is not None else n % 7)).isoformat(),
        "slot": 0,
        "kind": kind,
        "class": "quality" if key else "easy",
        "recipe_id": "REC005" if key else "REC001",
        "custom": False,
        "intent": "SECRET-INTENT",
        "key": key,
        "changed": False,
        "outcome": outcome,
        "modification_reason": None,
        "planned_duration_s": 3000.0,
        "planned_distance_m": 8000.0,
        "planned_distance_estimated": False,
        "actual": actual,
        "execution": execution,
    }


def digest_week(rows: list[dict], unplanned: list[dict], start: str = "2026-11-09") -> dict:
    by_outcome = {
        o: 0 for o in ("completed", "modified", "partial", "moved", "missed", "recorded", "not_recorded", "planned")
    }
    return {
        "schema": "weekly_digest.v1",
        "week_start": start,
        "week_end": "2026-11-15",
        "today": "2026-11-16",
        "days_elapsed": 7,
        "timezone": "America/New_York",
        "calendar_version": 7,
        "plan_available": True,
        "activity_coverage_complete": True,
        "totals": {
            "sessions": {
                "planned": len(rows),
                "planned_to_date": len(rows),
                "done": 0,
                "by_outcome": by_outcome,
                "removed": 1,
                "unplanned": len(unplanned),
            },
            "by_kind": {},
            "time": {},
            "run_distance": {},
            "key_sessions": {"planned": 0},
        },
        "sessions": rows,
        "unplanned": unplanned,
        "removed": [{"session_uid": "gone", "local_date": "2026-11-10", "kind": "run"}],
    }


def patch(n: int, *, status: str = "open", proposal_id: str = "p1") -> dict:
    return {
        "id": f"x{n}",
        "proposal_id": proposal_id,
        "calendar_version_number": 7,
        "category": "accumulated_fatigue",
        "severity": "caution",
        "ladder_level": "next_days",
        "window_start": AS_OF,
        "window_end": AS_OF + timedelta(days=2),
        "reassess_on": AS_OF + timedelta(days=3),
        "monitor": ["Fatigue"],
        "return_criteria": ["Usual fatigue"],
        "escalate_criteria": ["Rising fatigue"],
        "unchanged": [],
        "status": status,
        "resolved_at": None,
        "resolved_by": None,
        "resolution_note": None,
        "created_at": NOW - timedelta(hours=n),
        "version": 1,
        "session_uids": ["s1", "s2"],
        "reassess_due": False,
    }


def test_daily_route_minimal_c26() -> None:
    source = minimal()
    assert select_conditional_topics(source, DAILY) == []
    assert select_recipe_ids(source, DAILY) == ["REC001"]
    bundle = load_route(
        DAILY, recipe_ids=select_recipe_ids(source, DAILY), conditional_topics=select_conditional_topics(source, DAILY)
    )
    paths = {excerpt.path for excerpt in bundle.excerpts}
    assert paths <= {
        "COACHING_GUIDE.md",
        "workflows/daily_recommendation.md",
        "policies/coaching_policy_candidates.json",
        "policies/periodization_policy_candidates.json",
        "recipes/running_session_families.json",
    }
    assert {e.record_id for e in bundle.excerpts if e.record_id and e.record_id.startswith("P")} == set(
        POLICY_MAP[DAILY]
    )
    manifest = load_manifest()
    assert paths.isdisjoint(set(manifest["routing"][DAILY]["avoid_routinely"]))
    payload_json = canonical_json(build_payload(source, DAILY))
    assert math.ceil((len(payload_json) + bundle.chars) / 4) <= 6000


def test_strength_trigger_adds_hybrid_topic() -> None:
    source = minimal()
    source.strength_slots[0]["lower_body_cost"] = "moderate"
    topics = select_conditional_topics(source, DAILY)
    assert topics == ["topics/hybrid_strength_and_scheduling.md"]
    bundle = load_route(DAILY, recipe_ids=select_recipe_ids(source, DAILY), conditional_topics=topics)
    assert "topics/hybrid_strength_and_scheduling.md" in {e.path for e in bundle.excerpts}


def test_block_projection_includes_history() -> None:
    block = {
        "block_uid": "block-1",
        "version_id": "version-1",
        "version": 1,
        "status": "active",
        "objective": "Aerobic base",
        "rationale": "Ready",
        "maintained_qualities": [],
        "non_goals": [],
        "eligible_recipe_ids": ["REC001"],
        "progression_dimension": "duration",
        "constraints": [],
        "start_date": date(2026, 10, 19),
        "review_date": date(2026, 12, 28),
        "completion_indicators": [],
        "early_review_triggers": [],
        "objective_status": "unresolved",
    }
    decisions = [
        {
            "decision": name,
            "from_version": i,
            "to_version": i + 1,
            "rationale": "Review",
            "confidence": "moderate",
            "decided_at": datetime(2026, 10, 19, tzinfo=UTC) + timedelta(days=i * 21),
            "proposal_id": None,
            "block_uid": "block-1",
        }
        for i, name in enumerate(("start", "continue"))
    ]
    metrics: list[dict] = [
        {
            "result_id": f"r{n}",
            "metric_id": "run_volume_frequency",
            "method_version": "v1",
            "subject_type": "window",
            "subject_key": f"w{n}:{AS_OF}",
            "window_label": f"w{n}",
            "status": "available",
            "quality_status": "good",
            "value": {"run_count": 2},
            "unit": None,
            "reason_codes": [],
            "quality_flags": [],
            "anchor_keys": [],
            "calculated_at": NOW,
        }
        for n in (7, 14, 28, 56, 84)
    ]
    payload = build_payload(inputs(active_block=block, block_decisions=decisions, metric_results=metrics), BLOCK)
    assert payload["block"]["active"]["objective"] == "Aerobic base"
    assert [d["decision"] for d in payload["block"]["history"]] == ["start", "continue"]
    assert len(payload["prior_decisions"]) == 2
    assert {m["subject_key"].split(":")[0] for m in payload["load_shape"]} == {"w7", "w14", "w28", "w56", "w84"}


def test_payload_size_bounded_by_projection() -> None:
    recent = [
        dict(
            activity_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, str(i))),
            local_date=AS_OF - timedelta(days=i),
            sport="running",
            timer_s=1800,
            distance_m=5000,
            rpe=None,
            rpe_source=None,
        )
        for i in range(0, 28, 2)
    ]
    old = [
        dict(
            activity_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"old{i}")),
            local_date=AS_OF - timedelta(days=i),
            sport="running",
            timer_s=1800,
            distance_m=5000,
            rpe=None,
            rpe_source=None,
        )
        for i in range(28, 365, 2)
    ]
    a = len(canonical_json(build_payload(inputs(runs=recent), ROLLING)))
    b = len(canonical_json(build_payload(inputs(runs=recent + old), ROLLING)))
    assert abs(b - a) / a <= 0.05


def test_no_vendor_scores_in_payload() -> None:
    run = {
        "activity_id": "a",
        "local_date": AS_OF,
        "sport": "running",
        "timer_s": 1800,
        "distance_m": 5000,
        "rpe": None,
        "rpe_source": None,
        "vo2max": 60,
        "training_status": "productive",
        "notes": "PRIVATE",
    }
    metric: dict = {
        "result_id": "m",
        "metric_id": "run_volume_frequency",
        "method_version": "v1",
        "subject_type": "window",
        "subject_key": f"w7:{AS_OF}",
        "window_label": "w7",
        "status": "available",
        "quality_status": None,
        "value": {"run_count": 1, "body_battery": 95, "gps_coordinates": [1, 2]},
        "unit": None,
        "reason_codes": [],
        "quality_flags": [],
        "anchor_keys": [],
        "calculated_at": NOW,
        "body_battery": 95,
        "readiness_score": 100,
    }
    for operation in (DAILY, ROLLING, QUALITY_OP, BLOCK, CALIB, RACE, EXCEPTION, POST_EVENT):
        payload = build_payload(inputs(runs=[run], metric_results=[metric]), operation)
        encoded = json.dumps(payload).lower()
        assert all(term not in encoded for term in ("vo2max", "training_status", "body_battery", "readiness"))


def test_data_quality_flags_stale_dataset() -> None:
    rows = [
        {"dataset": dataset, "end_date": day, "status": "complete"}
        for dataset, day in [("activities", date(2026, 11, 11)), ("sleep", date(2026, 11, 15))]
    ]
    quality = build_payload(inputs(coverage=rows), ROLLING)["data_quality"]
    assert {k: v["status"] for k, v in quality["datasets"].items()} == {
        "activities": "stale",
        "sleep": "fresh",
        "hrv": "missing",
        "resting_hr": "missing",
    }
    assert quality["flags"] == [
        "activities_stale",
        "hrv_missing",
        "no_active_block",
        "no_intensity_anchor",
        "resting_hr_missing",
    ]


def test_safety_guard_window() -> None:
    checkins = [
        {
            "checkin_id": "c1",
            "kind": "exception",
            "observed_at": NOW - timedelta(hours=71),
            "local_date": AS_OF - timedelta(days=3),
            "fatigue": None,
            "illness": "none",
            "gait_change": "yes",
            "activity_id": None,
            "symptoms": [],
        },
        {
            "checkin_id": "c2",
            "kind": "exception",
            "observed_at": NOW - timedelta(hours=73),
            "local_date": AS_OF - timedelta(days=3),
            "fatigue": None,
            "illness": "none",
            "gait_change": "no",
            "activity_id": None,
            "symptoms": [{"site": "knee", "side": "left", "severity": 8.0, "timing": "later"}],
        },
    ]
    guard = build_payload(inputs(checkins=checkins), DAILY)["snapshot_meta"]["safety_guard"]
    assert guard["gait_change_yes"] is True and guard["max_symptom_severity"] is None


def test_prior_decisions_include_outcomes() -> None:
    uid = "session-1"
    proposal = {
        "proposal_id": "p1",
        "operation": ROLLING,
        "status": "partially_accepted",
        "submitted_at": NOW,
        "decided_at": NOW,
        "summary": "Adjust",
        "follow_up": None,
        "changes": [
            {
                "change_id": "c1",
                "op": "modify",
                "session_uid": uid,
                "decision": "accepted",
                "before": {"local_date": AS_OF - timedelta(days=3), "notes": "PRIVATE"},
                "after": {"intent": "Easy"},
            },
            {
                "change_id": "c2",
                "op": "delete",
                "session_uid": "s2",
                "decision": "rejected",
                "before": None,
                "after": None,
            },
        ],
    }
    checkin = {
        "checkin_id": "c",
        "observed_at": NOW,
        "local_date": AS_OF - timedelta(days=2),
        "kind": "exception",
        "activity_id": None,
        "symptoms": [{"site": "knee", "side": "left", "severity": 2, "timing": "later"}],
    }
    payload = build_payload(
        inputs(
            proposals=[proposal],
            completions=[
                {"session_uid": uid, "status": "completed_as_planned", "activity_id": None, "strong_workout_id": None}
            ],
            checkins=[checkin],
        ),
        ROLLING,
    )
    changes = payload["prior_decisions"][0]["changes"]
    assert changes[0]["outcome"]["completion_status"] == "completed_as_planned"
    assert len(changes[0]["outcome"]["symptom_reports_after"]) == 1
    assert "outcome" not in changes[1]
    assert "PRIVATE" not in canonical_json(payload)


def test_projection_sections_per_operation() -> None:
    common = {
        "snapshot_meta",
        "completed_exposures",
        "block",
        "anchors",
        "data_quality",
        "drill_down_queries",
    }
    expectations = {
        DAILY: {
            "goals_and_constraints",
            "calendar",
            "load_shape",
            "execution",
            "symptoms",
            "recovery",
            "prior_decisions",
        },
        ROLLING: {
            "quality_progression",
            "aerobic_efficiency",
            "goals_and_constraints",
            "calendar",
            "load_shape",
            "execution",
            "symptoms",
            "recovery",
            "prior_decisions",
            "exception_summary",
            "weekly_digest",
        },
        QUALITY_OP: {
            "quality_progression",
            "goals_and_constraints",
            "calendar",
            "load_shape",
            "execution",
            "symptoms",
            "recovery",
            "prior_decisions",
        },
        BLOCK: {
            "quality_progression",
            "aerobic_efficiency",
            "goals_and_constraints",
            "calendar",
            "load_shape",
            "execution",
            "symptoms",
            "recovery",
            "prior_decisions",
            "exception_summary",
            "weekly_digest",
            "benchmark_history",
        },
        CALIB: {"execution", "prior_decisions"},
        RACE: {"goals_and_constraints", "calendar", "load_shape", "symptoms"},
        EXCEPTION: {
            "goals_and_constraints",
            "calendar",
            "load_shape",
            "execution",
            "symptoms",
            "recovery",
            "prior_decisions",
            "exceptions",
        },
        POST_EVENT: {
            "goals_and_constraints",
            "calendar",
            "load_shape",
            "execution",
            "symptoms",
            "recovery",
            "prior_decisions",
            "exceptions",
            "event",
        },
    }
    for operation, sections in expectations.items():
        assert set(build_payload(inputs(), operation)) == common | sections


def test_build_snapshot_stable_hash_and_verified_selection(monkeypatch) -> None:
    import app.services.snapshot.build as module
    from app.services.decision_inputs import fingerprint

    source = minimal()
    captured = []
    source_versions = {
        "activity_sources": [{"source_id": "synthetic", "payload_hash": "a" * 64}] * 4000,
        "profile": {"version": 1},
    }

    class FakeSession:
        def __init__(self) -> None:
            self.rows: list[Any] = []
            self.info: dict[str, Any] = {}
            self.calls: list[str] = []

        def execute(self, statement) -> None:
            self.calls.append(str(statement))

        def add(self, row) -> None:
            self.rows.append(row)

        def flush(self) -> None:
            self.rows[-1].id = uuid.uuid4()

    def collect(_session, operation, as_of, *, now, kb):
        captured.append(kb)
        return {
            "source_versions": source_versions,
            "source_fingerprint": fingerprint(source_versions, kb),
            "safety_guard": {
                "window_hours": 72,
                "gait_change_yes": False,
                "max_symptom_severity": None,
                "illness_present": False,
                "clinical_restriction_active": False,
            },
        }

    from app.metrics import refresh as metrics_refresh

    original_verify = module.verify_selection

    def verified_with_research_notes(selection, *, root=None):
        verified = original_verify(selection, root=root)
        return {
            **verified,
            "selected_records": (
                *verified["selected_records"],
                {
                    "path": "research/test.json",
                    "record_id": "R1",
                    "content": {"research_notes": "Keep exact verified text"},
                },
            ),
        }

    monkeypatch.setattr(module, "verify_selection", verified_with_research_notes)
    monkeypatch.setattr(metrics_refresh, "ensure_windows", lambda session, as_of: session.calls.append("windows"))
    monkeypatch.setattr(metrics_refresh, "ensure_nights", lambda session, start, end: session.calls.append("nights"))
    monkeypatch.setattr(module, "load_inputs", lambda session, as_of, *, now: source)
    monkeypatch.setattr(module, "collect_decision_inputs", collect)
    session = FakeSession()
    first = module.build_snapshot(cast(Any, session), DAILY, AS_OF, now=NOW)
    second = module.build_snapshot(cast(Any, session), DAILY, AS_OF, now=NOW)
    assert session.rows[0].payload_sha256 == session.rows[1].payload_sha256
    assert first["payload"] == second["payload"]
    assert session.rows[0].source_versions == source_versions
    assert session.rows[0].source_fingerprint == fingerprint(source_versions, captured[0])
    assert first["payload"]["snapshot_meta"]["source_fingerprint"] == session.rows[0].source_fingerprint
    provenance = first["payload"]["snapshot_meta"]["source_provenance"]
    assert "source_versions" not in first["payload"]["snapshot_meta"]
    assert provenance == {
        "sha256": hashlib.sha256(canonical_json(source_versions).encode()).hexdigest(),
        "collections": {
            "activity_sources": {"kind": "array", "count": 4000},
            "profile": {"kind": "object", "count": 1},
        },
    }
    assert len(canonical_json(first["payload"])) < 30_000
    assert isinstance(session.rows[0].kb_routes, list)
    assert captured[0].digest == session.rows[0].kb_digest
    assert captured[0].selected_records == tuple(first["payload"]["snapshot_meta"]["knowledge"]["selected_records"])
    assert "research_notes" in first["payload"]["snapshot_meta"]["knowledge"]["selected_records"][-1]["content"]
    advisory_lock, row_lock, windows, nights = session.calls[:4]
    assert advisory_lock == "SELECT pg_advisory_xact_lock(71382413)"
    assert row_lock.startswith("SELECT app_state.id") and row_lock.endswith("FOR UPDATE")
    assert (windows, nights) == ("windows", "nights")
    assert "metrics_now" not in session.info
    assert "snapshot_id" not in first["payload"]["snapshot_meta"]

    changed_versions = {
        **source_versions,
        "activity_sources": [
            *source_versions["activity_sources"][:-1],
            {"source_id": "synthetic", "payload_hash": "b" * 64},
        ],
    }
    source_versions = changed_versions
    changed = module.build_snapshot(cast(Any, session), DAILY, AS_OF, now=NOW)
    assert session.rows[-1].source_versions == changed_versions
    assert session.rows[-1].source_fingerprint == fingerprint(changed_versions, captured[-1])
    assert session.rows[-1].source_fingerprint != session.rows[0].source_fingerprint
    assert changed["payload"]["snapshot_meta"]["source_provenance"]["sha256"] != provenance["sha256"]
    assert changed["payload"]["snapshot_meta"]["source_provenance"]["collections"] == provenance["collections"]


def test_srpe_suffixed_windows_in_load_shape() -> None:
    def metric(key: str) -> dict:
        return {
            "result_id": key,
            "metric_id": "session_rpe_load",
            "method_version": "v1",
            "subject_type": "window",
            "subject_key": key,
            "window_label": key,
            "status": "available",
            "quality_status": "good",
            "value": {"load_au": 100},
            "unit": "au",
            "reason_codes": [],
            "quality_flags": [],
            "anchor_keys": [],
            "calculated_at": NOW,
        }

    rows = [metric(f"w7:{AS_OF}:run"), metric(f"w7:{AS_OF}:strength"), metric(f"w14:{AS_OF}:run")]
    assert {row["subject_key"] for row in build_payload(inputs(metric_results=rows), DAILY)["load_shape"]} == {
        f"w7:{AS_OF}:run",
        f"w7:{AS_OF}:strength",
    }
    assert len(build_payload(inputs(metric_results=rows), ROLLING)["load_shape"]) == 3


def test_new_operation_windows_and_topics() -> None:
    source = minimal()
    exc = build_payload(source, EXCEPTION)
    assert (exc["calendar"]["start"], exc["calendar"]["end"]) == ("2026-11-09", "2026-11-22")
    assert exc["completed_exposures"]["window_days"] == 3
    assert set(exc["goals_and_constraints"]) == {
        "strength_routine",
        "latest_strong_sessions",
        "run_cycle",
        "clinical_restriction",
    }
    post = build_payload(source, POST_EVENT)
    assert (post["calendar"]["start"], post["calendar"]["end"]) == ("2026-11-16", "2026-11-29")
    assert post["completed_exposures"]["window_days"] == 14
    assert {"goals", "events"} <= set(post["goals_and_constraints"])
    assert (
        exc["snapshot_meta"]["scope"] == post["snapshot_meta"]["scope"] == {"start": "2026-11-16", "end": "2026-11-22"}
    )
    assert select_conditional_topics(source, EXCEPTION) == []
    assert select_conditional_topics(source, POST_EVENT) == [
        "topics/periodization_and_training_blocks.md",
        "topics/races_tapers_and_transitions.md",
    ]
    assert select_recipe_ids(source, EXCEPTION) == ["REC001"]
    assert scope(EXCEPTION, AS_OF) == (AS_OF, AS_OF + timedelta(days=6))


def horizon_block(review_date: date) -> dict:
    return {
        "block_uid": "block-1",
        "version_id": "version-1",
        "version": 1,
        "status": "active",
        "objective": "Aerobic base",
        "rationale": "Ready",
        "maintained_qualities": [],
        "non_goals": [],
        "eligible_recipe_ids": ["REC001"],
        "progression_dimension": "duration",
        "constraints": [],
        "start_date": date(2026, 10, 19),
        "review_date": review_date,
        "completion_indicators": [],
        "early_review_triggers": [],
        "objective_status": "unresolved",
        "benchmark": None,
        "benchmark_status": {"status": "not_set"},
    }


def test_rolling_horizon_follows_active_review_date() -> None:
    review_date = AS_OF + timedelta(days=28)
    rows = [session(AS_OF + timedelta(days=day), "run", "REC001") for day in (0, 13, 20, 28, 29, 42)]
    payload = build_payload(inputs(active_block=horizon_block(review_date), sessions=rows), ROLLING)
    meta = payload["snapshot_meta"]
    assert meta["scope"] == {"start": AS_OF.isoformat(), "end": review_date.isoformat()}
    assert payload["calendar"]["end"] == review_date.isoformat()
    assert [r["session_uid"] for r in payload["calendar"]["sessions"]] == [r["session_uid"] for r in rows[:4]]
    assert meta["horizon"] == {
        "rule": "active_block_review_date",
        "min_end": (AS_OF + timedelta(days=13)).isoformat(),
        "max_end": (AS_OF + timedelta(days=42)).isoformat(),
        "block_review_due": False,
    }


@pytest.mark.parametrize(
    ("review_days", "end_days", "due"),
    [(5, 13, True), (7, 13, True), (8, 13, False), (60, 42, False), (-3, 13, True), (None, 13, False)],
)
def test_rolling_horizon_clamps_and_flags_block_review_due(review_days: int | None, end_days: int, due: bool) -> None:
    block = horizon_block(AS_OF + timedelta(days=review_days)) if review_days is not None else None
    payload = build_payload(inputs(active_block=block), ROLLING)
    meta = payload["snapshot_meta"]
    assert meta["scope"]["end"] == payload["calendar"]["end"] == (AS_OF + timedelta(days=end_days)).isoformat()
    assert meta["horizon"]["block_review_due"] is due


@pytest.mark.parametrize("operation", [BLOCK, RACE])
def test_block_and_race_snapshots_show_outer_bound(operation: str) -> None:
    outer_bound = AS_OF + timedelta(days=42)
    rows = [session(outer_bound + timedelta(days=offset), "run", "REC001") for offset in (0, 1)]
    source = inputs(active_block=horizon_block(AS_OF + timedelta(days=28)), sessions=rows)
    payload = build_payload(source, operation)
    meta = payload["snapshot_meta"]
    assert meta["scope"]["end"] == payload["calendar"]["end"] == outer_bound.isoformat()
    assert [r["session_uid"] for r in payload["calendar"]["sessions"]] == [rows[0]["session_uid"]]
    assert meta["horizon"]["rule"] == "proposed_block_review_date"


@pytest.mark.parametrize(
    ("operation", "calendar_end_days"), [(EXCEPTION, 6), (POST_EVENT, 13), (DAILY, 3), (QUALITY_OP, 13)]
)
def test_fixed_operations_keep_scope_and_have_no_horizon(operation: str, calendar_end_days: int) -> None:
    payload = build_payload(inputs(active_block=horizon_block(AS_OF + timedelta(days=28))), operation)
    assert "horizon" not in payload["snapshot_meta"]
    assert payload["calendar"]["end"] == (AS_OF + timedelta(days=calendar_end_days)).isoformat()


def test_topics_scope_uses_active_review_date() -> None:
    rows = [session(AS_OF, "run", "REC001"), session(AS_OF + timedelta(days=20), "run", "REC009")]
    with_long_horizon = inputs(active_block=horizon_block(AS_OF + timedelta(days=28)), sessions=rows)
    with_short_horizon = replace(with_long_horizon, active_block=horizon_block(AS_OF + timedelta(days=8)))
    assert "REC009" in select_recipe_ids(with_long_horizon, ROLLING)
    assert "REC009" not in select_recipe_ids(with_short_horizon, ROLLING)


def test_session_view_modification_reason() -> None:
    row = session(AS_OF - timedelta(days=1), "run", "REC003")
    completion = {
        "session_uid": row["session_uid"],
        "status": "completed_modified",
        "modification_reason": "fatigue",
        "activity_id": None,
        "strong_workout_id": None,
    }
    payload = build_payload(inputs(sessions=[row], completions=[completion]), ROLLING)
    assert payload["calendar"]["sessions"][0]["modification_reason"] == "fatigue"


def test_prior_decisions_include_exception_reviews() -> None:
    def proposal(pid: str, operation: str, hours: int, status: str = "accepted") -> dict:
        return {
            "proposal_id": pid,
            "operation": operation,
            "status": status,
            "submitted_at": NOW - timedelta(hours=hours),
            "decided_at": None if status == "pending" else NOW - timedelta(hours=hours),
            "summary": pid,
            "follow_up": None,
            "changes": [],
        }

    proposals = [proposal(f"p_r{i}", ROLLING, 100 + i) for i in range(3)]
    proposals += [proposal(f"p_e{i}", EXCEPTION, 10 + i) for i in range(4)]
    proposals.append(proposal("p_pending", EXCEPTION, 1, "pending"))
    source = inputs(proposals=proposals, exception_patches=[patch(0, proposal_id="p_e0")])
    prior = build_payload(source, ROLLING)["prior_decisions"]
    assert [p["operation"] for p in prior] == [ROLLING, ROLLING, EXCEPTION, EXCEPTION, EXCEPTION]
    assert [p["proposal_id"] for p in prior] == ["p_r0", "p_r1", "p_e0", "p_e1", "p_e2"]
    assert prior[2]["patch_status"] == "open"
    assert prior[3]["patch_status"] is None


def test_exception_section_bounded() -> None:
    findings = [finding(n) for n in range(25)] + [finding(n, status="dismissed") for n in range(25, 28)]
    recommended = [{"operation": "exception_review", "reason": "r", "finding_ids": ["f0"], "prompt": "p"}]
    source = replace(
        minimal(),
        exception_findings=findings,
        exception_patches=[patch(n) for n in range(7)],
        review_recommended=recommended,
    )
    section = build_payload(source, EXCEPTION)["exceptions"]
    assert section["rule_version"] == "exceptions.v1"
    assert [f["id"] for f in section["open_findings"]] == [f"f{n}" for n in range(20)]
    assert all(len(f["evidence"]) == 5 for f in section["open_findings"])
    assert len(section["open_patches"]) == 5
    assert section["review_recommended"] == recommended
    assert [(u["kind"], u["class"]) for u in section["upcoming"]] == [
        ("run", "easy"),
        ("strength", "strength"),
        ("run", "easy"),
        ("strength", "strength"),
    ]
    assert all(u["expected_rpe"] == [2.0, 4.0] for u in section["upcoming"] if u["kind"] == "run")
    assert all(u["expected_rpe"] is None for u in section["upcoming"] if u["kind"] == "strength")


def test_exception_summary_counts() -> None:
    plan = [("a1", 2, "REC001", 7), ("a2", 4, "REC002", 8), ("a3", 6, "REC003", 2), ("a4", 3, "REC004", 6)]
    sessions = [session(AS_OF - timedelta(days=days), "run", recipe) for _, days, recipe, _ in plan]
    runs = [
        {
            "activity_id": activity,
            "local_date": AS_OF - timedelta(days=days),
            "sport": "running",
            "timer_s": 1800,
            "distance_m": 5000,
            "rpe": rpe,
            "rpe_source": "manual",
            "start_at": None,
        }
        for activity, days, _, rpe in plan
    ]
    completions = [
        {
            "session_uid": row["session_uid"],
            "status": "completed_as_planned" if row["recipe_id"] == "REC004" else "completed_modified",
            "activity_id": item[0],
            "strong_workout_id": None,
            "manual_session_id": None,
            "modification_reason": None,
        }
        for row, item in zip(sessions, plan, strict=True)
    ]
    proposals = [
        {
            "proposal_id": "p_r",
            "operation": ROLLING,
            "status": "accepted",
            "submitted_at": NOW - timedelta(days=6),
            "decided_at": NOW - timedelta(days=6),
            "summary": "Weekly",
            "follow_up": None,
            "changes": [],
        },
        {
            "proposal_id": "p_e",
            "operation": EXCEPTION,
            "status": "accepted",
            "submitted_at": NOW - timedelta(days=1),
            "decided_at": NOW - timedelta(days=1),
            "summary": "Patch",
            "follow_up": None,
            "changes": [
                {
                    "change_id": "c1",
                    "op": "delete",
                    "session_uid": "s-del",
                    "decision": "accepted",
                    "before": {
                        "kind": "run",
                        "recipe_id": "REC005",
                        "local_date": (AS_OF - timedelta(days=1)).isoformat(),
                        "intent": "VO2",
                    },
                    "after": None,
                },
                {
                    "change_id": "c2",
                    "op": "modify",
                    "session_uid": "s-mod",
                    "decision": "accepted",
                    "before": {
                        "kind": "run",
                        "recipe_id": "REC003",
                        "local_date": (AS_OF - timedelta(days=5)).isoformat(),
                        "intent": "Threshold",
                    },
                    "after": {"planned_duration_s": 1500},
                },
            ],
        },
    ]
    findings = [
        finding(0, rule="SESSION_FAILED", days_ago=2, entity="session:x"),
        finding(1, rule="SYM_MULTIWEEK", severity="escalate", entity="site:ankle|left"),
    ]
    findings += [finding(n, entity=f"e{n}") for n in range(2, 35)]

    def checkin(days: int, site: str, side: str) -> dict:
        return {
            "checkin_id": f"c{days}{site}",
            "observed_at": NOW - timedelta(days=days),
            "local_date": AS_OF - timedelta(days=days),
            "kind": "exception",
            "fatigue": None,
            "illness": "none",
            "gait_change": "no",
            "activity_id": None,
            "symptoms": [{"site": site, "side": side, "severity": 3.0, "timing": "during"}],
        }

    checkins = [checkin(1, "Ankle", "left"), checkin(3, "ankle ", "left"), checkin(2, "knee", "right")]
    source = inputs(
        sessions=sessions,
        runs=runs,
        completions=completions,
        proposals=proposals,
        exception_findings=findings,
        exception_patches=[patch(0)],
        checkins=checkins,
    )
    summary = build_payload(source, ROLLING)["exception_summary"]
    assert (summary["window_start"], summary["window_end"]) == ("2026-11-03", "2026-11-16")
    assert summary["rpe_mismatch"] == {"easy_above": 1, "long_above": 1, "quality_above": 0, "quality_below": 1}
    assert "quality_sessions" not in summary
    assert summary["recurring_symptom_sites"] == [{"site_key": "ankle|left", "distinct_days_14": 2}]
    assert summary["since_last_review"] == "2026-11-10"
    assert len(summary["findings"]) == 30
    assert summary["open_escalations"] == 1
    assert summary["patches"][0]["changes_count"] == 2


def test_event_section() -> None:
    def event(event_id: str, days: int, name: str) -> dict:
        return {
            "event_id": event_id,
            "name": name,
            "event_date": AS_OF - timedelta(days=days),
            "distance_m": 10000,
            "purpose": "pr",
            "goal_time_s": None,
            "goal_pace_s_per_km": None,
            "rank": None,
            "status": "completed",
            "result_s": 2700,
        }

    runs = [
        {
            "activity_id": "a10k",
            "local_date": AS_OF - timedelta(days=2),
            "sport": "running",
            "timer_s": 2700,
            "distance_m": 10000,
            "rpe": 9.0,
            "rpe_source": "manual",
            "start_at": datetime(2026, 11, 14, 13, tzinfo=UTC),
        },
        {
            "activity_id": "a2k",
            "local_date": AS_OF - timedelta(days=2),
            "sport": "running",
            "timer_s": 720,
            "distance_m": 2000,
            "rpe": 3.0,
            "rpe_source": "manual",
            "start_at": datetime(2026, 11, 14, 12, tzinfo=UTC),
        },
    ]
    checkins = [
        {
            "checkin_id": f"c{days}",
            "observed_at": NOW - timedelta(days=days),
            "local_date": AS_OF - timedelta(days=days),
            "kind": "post_run",
            "fatigue": 6.0,
            "illness": "none",
            "gait_change": "no",
            "activity_id": None,
            "symptoms": [{"site": "Calf", "side": "left", "severity": 2.0, "timing": "next_morning"}],
        }
        for days in (2, 1, 7)
    ]
    nights = [
        {
            "result_id": f"n{d}",
            "metric_id": "recovery_multisignal_summary",
            "method_version": "v1",
            "subject_type": "night",
            "subject_key": f"night:{AS_OF - timedelta(days=d)}",
            "window_label": None,
            "status": "available",
            "quality_status": "good",
            "value": {"flags": []},
            "unit": None,
            "reason_codes": [],
            "quality_flags": [],
            "anchor_keys": [],
            "calculated_at": NOW,
        }
        for d in range(5)
    ]
    source = inputs(
        events=[event("e1", 2, "Synthetic 10K"), event("e0", 5, "Synthetic 5K")],
        exception_findings=[finding(0, rule="POST_EVENT_REVIEW_DUE", entity="event:e1")],
        runs=runs,
        checkins=checkins,
        metric_results=nights,
    )
    section = build_payload(source, POST_EVENT)["event"]
    assert section["event"]["id"] == "e1" and section["event"]["name"] == "Synthetic 10K"
    assert section["matched_activity"]["distance_m"] == 10000
    assert section["matched_activity"]["start_local"] == "2026-11-14T08:00:00-05:00"
    assert section["event"]["purpose"] == "pr"
    assert len(section["checkins_after"]) == 2
    assert section["checkins_after"][0]["symptoms"] == [
        {"site_key": "calf|left", "severity": 2.0, "timing": "next_morning"}
    ]
    assert {m["subject_key"] for m in section["recovery_nights"]} == {
        f"night:{AS_OF - timedelta(days=d)}" for d in (3, 2, 1, 0)
    }
    assert build_payload(inputs(), POST_EVENT)["event"] is None


def upcoming_event(event_id: str, days: int, rank: int) -> dict:
    return {
        "event_id": event_id,
        "name": f"Race {event_id}",
        "event_date": AS_OF + timedelta(days=days),
        "distance_m": 21097,
        "purpose": "pr",
        "goal_time_s": 6000,
        "goal_pace_s_per_km": 284,
        "rank": rank,
        "status": "registered",
        "result_s": None,
    }


def test_goal_race_is_the_rank_one_event() -> None:
    source = inputs(events=[upcoming_event("e2", 30, 2), upcoming_event("e1", 120, 1)])
    view = build_payload(source, ROLLING)["goals_and_constraints"]
    assert view["goal_race"] == {"event_id": "e1", "days_until": 120}
    assert [(e["event_id"], e["rank"]) for e in view["events"]] == [("e2", 2), ("e1", 1)]
    assert view["events"][0]["goal_pace_s_per_km"] == 284
    assert build_payload(inputs(events=[]), ROLLING)["goals_and_constraints"]["goal_race"] is None
    assert "goal_race" not in build_payload(source, DAILY)["goals_and_constraints"]


def test_exception_sections_size_bounded() -> None:
    def build(count: int) -> SnapshotInputs:
        return replace(
            minimal(),
            exception_findings=[finding(n) for n in range(count)],
            exception_patches=[patch(n) for n in range(7)],
            review_recommended=[{"operation": "exception_review", "reason": "r", "finding_ids": ["f0"], "prompt": "p"}],
        )

    small, large = build(40), build(120)
    for operation in (EXCEPTION, ROLLING):
        assert len(canonical_json(build_payload(small, operation))) == len(
            canonical_json(build_payload(large, operation))
        )
    assert len(canonical_json(build_payload(large, EXCEPTION))) <= 21_000
    assert len(canonical_json(build_payload(large, ROLLING))) <= 11_000


QUALITY_STRUCTURE = [
    {"type": "warmup", "duration_type": "time", "duration_value": 600, "target": None},
    {
        "type": "repeat",
        "count": 5,
        "steps": [
            {
                "type": "work",
                "duration_type": "time",
                "duration_value": 240,
                "target": {"modality": "speed", "low": 3.4, "high": 3.8},
            },
            {"type": "recovery", "duration_type": "time", "duration_value": 120, "target": None},
        ],
    },
    {"type": "cooldown", "duration_type": "time", "duration_value": 600, "target": None},
]
# offset within the 14-day cycle -> (kind, recipe, slot_id)
CYCLE = {
    0: ("strength", None, "slot-1"),
    1: ("run", "REC003", None),
    2: ("mobility", None, None),
    3: ("run", "REC001", None),
    4: ("strength", None, "slot-1"),
    5: ("run", "REC006", None),
    7: ("strength", None, "slot-1"),
    8: ("run", "REC003", None),
    9: ("mobility", None, None),
    10: ("run", "REC001", None),
    11: ("strength", None, "slot-1"),
    12: ("run", "REC006", None),
    13: ("run", "REC001", None),
}


def horizon_sessions(first: int, last: int) -> list[dict]:
    rows = []
    for offset in range(first, last + 1):
        spec = CYCLE.get(offset % 14)
        if spec is None:
            continue
        kind, recipe, slot_id = spec
        row = session(AS_OF + timedelta(days=offset), kind, recipe, slot_id=slot_id)
        row["intent"] = "Build aerobic durability with controlled effort and an easy finish"
        row["planned_duration_s"] = 3000
        if recipe == "REC003" and offset <= 14:
            row["structure"] = QUALITY_STRUCTURE
        rows.append(row)
    return rows


def test_horizon_snapshot_size_ceilings() -> None:
    source = inputs(
        sessions=horizon_sessions(-28, 35),
        events=[upcoming_event(f"e{n}", 20 * n, n) for n in range(1, 5)],
        active_block={
            **horizon_block(AS_OF + timedelta(days=35)),
            "target_event_id": "e1",
            "build_outline": [{"emphasis": "half-marathon-specific endurance " * 3, "weeks": 5}] * 4,
            "target_event_status": "current",
        },
    )
    sizes = {}
    for operation in (ROLLING, BLOCK):
        payload = build_payload(source, operation)
        sizes[operation] = (len(canonical_json(payload["calendar"])), len(canonical_json(payload)))
    assert sizes[ROLLING][0] <= 24_000
    assert sizes[ROLLING][1] <= 26_750
    assert sizes[BLOCK][0] <= 31_250
    assert sizes[BLOCK][1] <= 34_000


def test_block_benchmark_sections() -> None:
    block = {
        "block_uid": "block-1",
        "version_id": "version-1",
        "version": 1,
        "status": "active",
        "objective": "Aerobic base",
        "rationale": "Ready",
        "maintained_qualities": [],
        "non_goals": [],
        "eligible_recipe_ids": ["REC001", "REC009"],
        "progression_dimension": "duration",
        "constraints": [],
        "start_date": date(2026, 10, 19),
        "review_date": date(2026, 12, 28),
        "completion_indicators": [],
        "early_review_triggers": [],
        "objective_status": "unresolved",
        "benchmark": {
            "kind": "time_trial",
            "protocol": "5 km solo time trial",
            "planned_date": AS_OF - timedelta(days=1),
            "progress_if": "p",
            "consolidate_if": "c",
            "event_id": None,
            "distance_m": 5000,
        },
        "benchmark_status": {
            "status": "completed",
            "match_method": "auto",
            "activity_id": "a9",
            "event_id": None,
            "local_date": AS_OF - timedelta(days=1),
            "distance_m": 5000,
            "result_s": 1290,
            "rpe": 9.0,
            "scheduled_date": None,
            "evidence_at": NOW,
        },
    }
    runs = [
        {
            "activity_id": "a9",
            "local_date": AS_OF - timedelta(days=1),
            "sport": "running",
            "timer_s": 1290,
            "distance_m": 5000,
            "rpe": 9.0,
            "rpe_source": "manual",
            "start_at": datetime(2026, 11, 15, 13, tzinfo=UTC),
        },
        {
            "activity_id": "a8",
            "local_date": AS_OF - timedelta(days=1),
            "sport": "running",
            "timer_s": 2900,
            "distance_m": 8000,
            "rpe": 4.0,
            "rpe_source": "manual",
            "start_at": datetime(2026, 11, 15, 13, tzinfo=UTC),
        },
    ]
    history = [
        {
            "block_uid": "block-0",
            "objective": "Base",
            "protocol": "5 km solo time trial",
            "distance_m": 5000,
            "local_date": date(2026, 10, 18),
            "result_s": 1320,
            "outcome": "progress",
        },
        {
            "block_uid": "block-00",
            "objective": "Base",
            "protocol": "5 km solo time trial",
            "distance_m": 5000,
            "local_date": date(2026, 8, 30),
            "result_s": 1350,
            "outcome": "consolidate",
        },
    ]
    source = inputs(active_block=block, runs=runs, benchmark_history=history)
    payload = build_payload(source, BLOCK)
    assert payload["block"]["active"]["benchmark_status"]["status"] == "completed"
    assert len(payload["benchmark_history"]) == 2
    assert payload["event"]["event"] is None
    assert payload["event"]["matched_activity"]["id"] == "a9"
    for operation in (DAILY, CALIB):
        projected = build_payload(source, operation)["block"]
        assert projected["benchmark"]["protocol"] == "5 km solo time trial"
        assert projected["benchmark_status"]["status"] == "completed"


def test_quality_progression_section() -> None:
    structure = [
        {"type": "warmup", "duration_type": "time", "duration_value": 600, "target": None},
        {
            "type": "repeat",
            "count": 4,
            "steps": [
                {
                    "type": "work",
                    "duration_type": "time",
                    "duration_value": 300,
                    "target": {"modality": "speed", "low": 3.4, "high": 3.8},
                },
                {"type": "recovery", "duration_type": "time", "duration_value": 120, "target": None},
            ],
        },
        {"type": "cooldown", "duration_type": "time", "duration_value": 600, "target": None},
    ]
    old = {**session(AS_OF - timedelta(days=20), "run", "REC003"), "structure": structure}
    recent = {**session(AS_OF - timedelta(days=6), "run", "REC003"), "structure": structure}
    future = {**session(AS_OF + timedelta(days=3), "run", "REC003"), "structure": structure}
    easy = session(AS_OF - timedelta(days=2), "run", "REC001")
    completions = [
        {
            "session_uid": row["session_uid"],
            "activity_id": aid,
            "status": "completed_as_planned",
            "strong_workout_id": None,
            "manual_session_id": None,
            "match_method": None,
            "modification_reason": None,
            "reason_note": None,
        }
        for row, aid in [(old, "a-old"), (recent, "a-recent")]
    ]
    runs = [
        {
            "activity_id": aid,
            "local_date": row["local_date"],
            "sport": "running",
            "timer_s": 2880,
            "distance_m": 8000,
            "rpe": None,
            "rpe_source": None,
        }
        for row, aid in [(old, "a-old"), (recent, "a-recent")]
    ]
    metrics = []
    for aid, speed, hr in [("a-old", 3.5, 161), ("a-recent", 3.6, 158)]:
        reps = [
            {
                "fully_completed": True,
                "speed_status": "available",
                "mean_speed_mps": speed,
                "actual_timer_s": 300.0,
                "hr_median_bpm": hr,
            }
            for _ in range(4)
        ]
        metrics.append(
            {
                "result_id": aid,
                "metric_id": "work_interval_execution",
                "subject_type": "activity",
                "subject_key": aid,
                "status": "available",
                "reason_codes": [],
                "quality_flags": [],
                "value": {
                    "reps": reps,
                    "n_planned": 4,
                    "n_completed": 4,
                    "step_completion_ratio": 1.0,
                    "cv_speed": 1.0,
                    "last_first_change_pct": 0.0,
                    "target_coverage": None,
                },
            }
        )
    source = inputs(sessions=[old, recent, future, easy], completions=completions, runs=runs, metric_results=metrics)
    groups = build_payload(source, ROLLING)["quality_progression"]
    assert len(groups) == 1
    group = groups[0]
    assert group["signature"] == "ws1:4xt300" and group["recipe_ids"] == ["REC003"]
    assert (group["sessions_total"], group["sessions_assessable"]) == (2, 2)
    first, last = group["recent"]
    assert first["local_date"] == (AS_OF - timedelta(days=20)).isoformat()
    assert (first["work_speed_mps"], first["work_hr_bpm"], first["work_m_per_beat"]) == (3.5, 161.0, 1.304)
    assert (last["activity_id"], last["work_m_per_beat"], last["status"], last["sport"]) == (
        "a-recent",
        1.367,
        "available",
        "running",
    )
    assert set(last) == set(PROGRESSION_POINT_KEYS)
    assert build_payload(inputs(sessions=[easy]), ROLLING)["quality_progression"] == []
    assert "quality_progression" not in build_payload(source, DAILY)


def test_aerobic_efficiency_section() -> None:
    def window(days: int, runs: int, median: float) -> dict:
        label = f"w{days}"
        key = f"{label}:{AS_OF.isoformat()}"
        return {
            "result_id": f"w-{label}",
            "metric_id": "aerobic_efficiency",
            "method_version": "v1",
            "subject_type": "window",
            "subject_key": key,
            "window_label": key,
            "status": "available",
            "quality_status": None,
            "unit": "m_per_beat",
            "reason_codes": [],
            "quality_flags": [],
            "anchor_keys": [],
            "calculated_at": NOW,
            "value": {
                "window_days": days,
                "runs_counted": runs,
                "ef_median_m_per_beat": median,
                "points": [
                    {
                        "activity_id": f"a{i}",
                        "local_date": (AS_OF - timedelta(days=runs - i)).isoformat(),
                        "session_class": "easy",
                        "ef_m_per_beat": 1.17,
                        "mean_speed_mps": 2.8,
                        "mean_hr_bpm": 143.6,
                        "decoupling_pct": None,
                        "quality_flags": [],
                    }
                    for i in range(runs)
                ],
            },
        }

    short = window(28, 4, 1.18)
    long = window(84, 7, 1.17)
    source = inputs(metric_results=[short, long])
    payload = build_payload(source, ROLLING)
    section = payload["aerobic_efficiency"]

    assert section["interpretation"] == "descriptive_only"
    assert section["w28"]["value"] == {
        "window_days": 28,
        "runs_counted": 4,
        "ef_median_m_per_beat": 1.18,
    }
    assert section["w84"]["value"] == {
        "window_days": 84,
        "runs_counted": 7,
        "ef_median_m_per_beat": 1.17,
    }
    assert [p["activity_id"] for p in section["recent_runs"]] == ["a2", "a3", "a4", "a5", "a6"]
    assert all(row["metric_id"] != "aerobic_efficiency" for row in payload["load_shape"])
    assert len(short["value"]["points"]) == 4
    assert len(long["value"]["points"]) == 7
    assert build_payload(source, BLOCK)["aerobic_efficiency"] == section
    assert build_payload(inputs(), ROLLING)["aerobic_efficiency"] == {
        "interpretation": "descriptive_only",
        "recent_runs": [],
        "w28": None,
        "w84": None,
    }
    for operation in (DAILY, QUALITY_OP):
        assert "aerobic_efficiency" not in build_payload(source, operation)


def test_weekly_digest_empty_by_default() -> None:
    assert build_payload(inputs(), ROLLING)["weekly_digest"] == {
        "schema": "weekly_digest.v1",
        "timezone": "America/New_York",
        "weeks": [],
    }


def test_weekly_digest_week_view_caps_and_shape() -> None:
    component = {"name": "duration_ratio", "value": 0.97, "status": "met"}
    execution = {
        "assessment_status": "available",
        "reason_codes": ["MOVE_CANDIDATE"],
        "quality_flags": ["MOVED"],
        "components": [component],
        "reps_planned": 6,
        "reps_completed": 5,
    }
    actual = {
        "subject": "activity",
        "id": "a5",
        "local_date": "2026-11-14",
        "duration_s": 2900.0,
        "distance_m": 7900.0,
        "sport": "treadmill_running",
        "avg_hr_bpm": 148.0,
        "moving_pace_s_per_km": 330.0,
        "rpe": 6.0,
        "rpe_source": "manual",
    }
    rows = [digest_row(n, key=True, day=n) for n in range(5)]
    rows.append(digest_row(5, key=True, day=5, execution=execution, actual=actual))
    rows += [digest_row(n, outcome="missed") for n in range(10, 19)]
    rows += [digest_row(19, kind="mobility", outcome="not_recorded"), digest_row(20)]
    unplanned = [
        {
            "subject": "activity",
            "id": f"x{i}",
            "local_date": f"2026-11-{9 + i:02d}",
            "kind": "run",
            "duration_s": 1800.0,
            "distance_m": 5000.0,
        }
        for i in range(7)
    ]
    (week,) = build_payload(inputs(weekly_digest=[digest_week(rows, unplanned)]), ROLLING)["weekly_digest"]["weeks"]

    assert [row["session_uid"] for row in week["key_sessions"]] == ["u02", "u03", "u04", "u05"]
    assert week["key_sessions_omitted"] == 2
    assessed = week["key_sessions"][-1]
    assert assessed["activity_id"] == "a5"
    assert assessed["actual_duration_s"] == 2900.0
    activity_fields = ("sport", "avg_hr_bpm", "moving_pace_s_per_km", "rpe")
    assert {field: assessed[field] for field in activity_fields} == {field: actual[field] for field in activity_fields}
    assert "rpe_source" not in assessed
    assert assessed["assessment_status"] == "available"
    assert assessed["components"] == [component]
    assert assessed["reps_planned"] == 6 and assessed["reps_completed"] == 5
    assert assessed["quality_flags"] == ["MOVED"]
    unassessed = week["key_sessions"][0]
    assert all(unassessed[field] is None for field in activity_fields)
    assert unassessed["assessment_status"] is None
    assert unassessed["reason_codes"] == []
    assert unassessed["components"] == []
    assert unassessed["reps_planned"] is None and unassessed["activity_id"] is None
    assert len(week["not_done"]) == 6
    assert all(row["outcome"] == "missed" and row["kind"] != "mobility" for row in week["not_done"])
    assert week["not_done_omitted"] == 3
    assert [row["id"] for row in week["unplanned"]] == ["x3", "x4", "x5", "x6"]
    assert week["unplanned_omitted"] == 3
    assert week["totals"]["sessions"]["removed"] == 1
    assert not {"sessions", "removed", "intent", "slot", "custom"}.intersection(week)
    assert "SECRET-INTENT" not in canonical_json(week)


def test_weekly_digest_budget() -> None:
    components = [
        {"name": name, "value": 0.97, "status": "met"}
        for name in (
            "duration_ratio",
            "distance_ratio",
            "step_completion_ratio",
            "target_coverage",
        )
    ]
    execution = {
        "assessment_status": "available",
        "reason_codes": ["MOVE_CANDIDATE"],
        "quality_flags": ["MOVED"],
        "components": components,
        "reps_planned": 6,
        "reps_completed": 5,
    }
    actual = {
        "subject": "activity",
        "id": "a5",
        "local_date": "2026-11-14",
        "duration_s": 2900.0,
        "distance_m": 7900.0,
        "sport": "treadmill_running",
        "avg_hr_bpm": 148.0,
        "moving_pace_s_per_km": 330.0,
        "rpe": 6.0,
        "rpe_source": "manual",
    }
    rows = [digest_row(n, key=True, execution=execution, actual=actual) for n in range(4)]
    rows += [digest_row(n, outcome="missed") for n in range(4, 12)]
    rows += [digest_row(12), digest_row(13)]
    unplanned = [
        {
            "subject": "activity",
            "id": f"x{i}",
            "local_date": f"2026-11-{9 + i:02d}",
            "kind": "run",
            "duration_s": 1800.0,
            "distance_m": 5000.0,
        }
        for i in range(6)
    ]
    source = inputs(weekly_digest=[digest_week(rows, unplanned, start) for start in ("2026-11-02", "2026-11-09")])
    section = build_payload(source, ROLLING)["weekly_digest"]
    assert len(canonical_json(section)) <= WEEKLY_DIGEST_MAX_CHARS
    assert len(section["weeks"]) == 2
    for week in section["weeks"]:
        assert week["key_sessions_omitted"] == 0
        assert week["not_done_omitted"] == 2
        assert week["unplanned_omitted"] == 2
