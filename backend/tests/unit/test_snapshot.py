"""Pure snapshot projection and knowledge routing contract."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from app.services.decision_inputs import canonical_json
from app.services.knowledge import POLICY_MAP, load_manifest, load_route
from app.services.snapshot import (
    BLOCK,
    CALIB,
    DAILY,
    QUALITY_OP,
    RACE,
    ROLLING,
    SnapshotInputs,
    build_payload,
    select_conditional_topics,
    select_recipe_ids,
)

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
    for operation in (DAILY, ROLLING, QUALITY_OP, BLOCK, CALIB, RACE):
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
        "legacy_checkins",
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
            "goals_and_constraints",
            "calendar",
            "load_shape",
            "execution",
            "symptoms",
            "recovery",
            "prior_decisions",
        },
        QUALITY_OP: {
            "goals_and_constraints",
            "calendar",
            "load_shape",
            "execution",
            "symptoms",
            "recovery",
            "prior_decisions",
        },
        BLOCK: {
            "goals_and_constraints",
            "calendar",
            "load_shape",
            "execution",
            "symptoms",
            "recovery",
            "prior_decisions",
        },
        CALIB: {"execution", "prior_decisions"},
        RACE: {"goals_and_constraints", "calendar", "load_shape", "symptoms"},
    }
    for operation, sections in expectations.items():
        assert set(build_payload(inputs(), operation)) == common | sections


def test_build_snapshot_stable_hash_and_verified_selection(monkeypatch) -> None:
    from app.services import snapshot as module
    from app.services.decision_inputs import fingerprint

    source = minimal()
    captured = []
    source_versions = {
        "legacy_checkins": [],
        "activity_sources": [{"source_id": "synthetic", "payload_hash": "a" * 64}] * 4000,
        "profile": {"version": 1},
        "history_epoch": None,
    }

    class FakeSession:
        def __init__(self) -> None:
            self.rows: list[Any] = []
            self.info: dict[str, Any] = {}
            self.calls: list[str] = []

        def execute(self, statement) -> None:
            self.calls.append(str(statement))

        def get(self, model, key, **kwargs):
            return type("State", (), {"planning_authority": "calendar"})()

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
                "legacy_safety_active": False,
            },
        }

    from app.metrics import engine as metrics_engine

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
    monkeypatch.setattr(metrics_engine, "ensure_windows", lambda session, as_of: session.calls.append("windows"))
    monkeypatch.setattr(metrics_engine, "ensure_nights", lambda session, start, end: session.calls.append("nights"))
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
            "legacy_checkins": {"kind": "array", "count": 0},
            "activity_sources": {"kind": "array", "count": 4000},
            "profile": {"kind": "object", "count": 1},
            "history_epoch": {"kind": "scalar", "count": 0},
        },
    }
    assert len(canonical_json(first["payload"])) < 30_000
    assert isinstance(session.rows[0].kb_routes, list)
    assert captured[0].digest == session.rows[0].kb_digest
    assert captured[0].selected_records == tuple(first["payload"]["snapshot_meta"]["knowledge"]["selected_records"])
    assert "research_notes" in first["payload"]["snapshot_meta"]["knowledge"]["selected_records"][-1]["content"]
    assert session.calls[:3] == ["SELECT pg_advisory_xact_lock(71382413)", "windows", "nights"]
    assert "metrics_now" not in session.info
    assert "snapshot_id" not in first["payload"]["snapshot_meta"]

    changed_versions = {**source_versions, "activity_sources": [
        *source_versions["activity_sources"][:-1],
        {"source_id": "synthetic", "payload_hash": "b" * 64},
    ]}
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


def test_snapshot_rejects_legacy_authority_before_refresh(monkeypatch) -> None:
    import pytest

    from app.metrics import engine as metrics_engine
    from app.services import snapshot as module
    from app.services.proposals import DecisionError

    class LegacySession:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def execute(self, statement) -> None:
            self.calls.append(str(statement))

        def get(self, model, key, **kwargs):
            return type("State", (), {"planning_authority": "legacy"})()

    session = LegacySession()
    monkeypatch.setattr(metrics_engine, "ensure_windows", lambda *args: session.calls.append("windows"))
    with pytest.raises(DecisionError) as error:
        module.build_snapshot(cast(Any, session), DAILY, AS_OF, now=NOW)
    assert (error.value.code, error.value.http_status) == ("planning_not_active", 409)
    assert session.calls == ["SELECT pg_advisory_xact_lock(71382413)"]
