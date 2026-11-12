from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.services.calendar_structure import expand_structure
from app.services.decision_inputs import VerifiedKnowledge, canonical_json, fingerprint
from app.services.proposals import (
    ActiveBlock,
    HeadSession,
    SnapshotRef,
    ValidationContext,
    anchor_key,
    derive_certainty,
    session_fields,
    validate_document,
    validate_subset,
)

TODAY = date(2026, 11, 16)
NOW = datetime(2026, 11, 16, 15, tzinfo=UTC)
TZ = ZoneInfo("America/New_York")


def U(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


KB = VerifiedKnowledge(
    "0" * 64,
    (),
    (),
    frozenset(f"P{i:03d}" for i in range(1, 24)),
    frozenset(f"REC{i:03d}" for i in range(1, 11)),
    frozenset({"E-AER-01", "E-PER-02"}),
)


def head(n: int, day: int, kind: str, recipe: str | None = None, *, placeholder: bool = False) -> HeadSession:
    return HeadSession(
        U(n),
        1,
        date(2026, 11, day),
        0,
        kind,
        recipe,
        False,
        placeholder,
        False,
        False,
        "Easy",
        "committed",
        3600 if recipe == "REC002" else 1800,
        None,
        None,
        None,
        None,
    )


def context(op: str = "review_rolling_plan", *, guard: dict | None = None, block: bool = True) -> ValidationContext:
    rows = [
        head(1, 16, "run", "REC001"),
        head(2, 18, "run", placeholder=True),
        head(3, 20, "run", "REC001"),
        head(4, 22, "run", "REC002"),
        head(5, 24, "run", "REC003"),
        head(6, 26, "run", "REC001"),
        head(7, 28, "run", "REC002"),
        head(11, 16, "strength"),
        head(12, 20, "strength"),
        head(13, 23, "strength"),
        head(14, 27, "strength"),
    ]
    snapshot = SnapshotRef(
        U(200),
        op,
        TODAY,
        NOW - timedelta(hours=1),
        "fingerprint",
        (),
        KB.digest,
        guard or {"max_symptom_severity": None},
    )
    active = ActiveBlock(U(100), U(101), 1, ("REC001", "REC002", "REC003", "REC007")) if block else None
    return ValidationContext(
        NOW,
        TODAY,
        TZ,
        snapshot,
        7,
        {row.session_uid: row for row in rows},
        active,
        TODAY,
        guard or {"max_symptom_severity": None},
        "fingerprint",
        KB.digest,
        KB,
    )


def valid_doc(op: str = "review_rolling_plan") -> dict:
    return {
        "schema_version": "coach_proposal.v1",
        "operation": op,
        "snapshot_id": str(U(200)),
        "base_calendar_version": 7,
        "base_block_version_id": str(U(101)),
        "summary": "Adjust the week",
        "rationale": "Observed load",
        "confidence": {"decision": "moderate", "evidence": "moderate", "data": "moderate"},
        "changes": [
            {
                "change_id": "c1",
                "op": "modify",
                "session_uid": str(U(3)),
                "after": {"planned_duration_s": 2400, "intent": "Easy"},
                "reason": "More time",
            }
        ],
        "preserved": [str(U(1))],
        "evidence_ids": ["E-AER-01"],
        "policy_ids": ["P001"],
        "recipe_ids": ["REC001"],
        "skill_version": "running-coach.v1",
    }


def outcome(doc: dict, ctx: ValidationContext | None = None) -> tuple[str, list[tuple[str, str]]]:
    result = validate_document(doc, ctx or context())
    return result.status, [(issue.code, issue.path) for issue in result.issues]


def change(change_id: str, op: str, uid: int | None, after: dict | None = None, flags: list[str] | None = None) -> dict:
    return {
        "change_id": change_id,
        "op": op,
        "session_uid": str(U(uid)) if uid is not None else None,
        "after": after,
        "reason": "Test",
        "material_flags": flags or [],
    }


def test_valid_rolling_proposal_is_pending() -> None:
    assert outcome(valid_doc()) == ("pending", [])
    doc = valid_doc()
    doc["changes"] = []
    assert outcome(doc) == ("pending", [])


@pytest.mark.parametrize("structure", [
    [],
    [{"type": "work", "duration_type": "time", "duration_value": 180,
      "target": {"modality": "effort", "low": 6, "high": 7, "effort_cue": "Controlled"}}],
    [{"type": "repeat", "count": 5, "steps": [
        {"type": "work", "duration_type": "time", "duration_value": 180,
         "target": {"modality": "effort", "low": 6, "high": 7, "effort_cue": "Controlled"}}]}],
    [{"type": "work", "duration_type": "time", "duration_value": 180,
      "target": {"modality": "effort", "effort_cue": " "}}],
    [{"type": "work", "duration_type": "time", "duration_value": 180,
      "target": {"modality": "hr", "low": 160, "high": 150}}],
    [{"type": "work", "duration_type": "time", "duration_value": float("inf")}],
    [{"type": "repeat", "count": 101, "steps": [
        {"type": "work", "duration_type": "time", "duration_value": 180}]}],
])
def test_invalid_workout_structure_rejected_on_submit_and_acceptance(structure: list) -> None:
    doc = valid_doc()
    doc["changes"][0]["after"]["structure"] = structure
    result = validate_document(doc, context())
    expected = [("V6.invalid_structure", "changes.0.after.structure")]
    assert result.status == "invalid"
    assert [(issue.code, issue.path) for issue in result.issues] == expected
    # Older pending proposals must still parse, but cannot apply malformed steps.
    assert result.doc is not None
    assert [(issue.code, issue.path) for issue in validate_subset(result.doc, {"c1"}, False, set(), context())] == expected
    assert validate_subset(result.doc, set(), False, set(), context()) == []


def test_effort_intervals_use_cues_and_expand_for_calendar() -> None:
    doc = valid_doc()
    work = {"type": "work", "duration_type": "time", "duration_value": 180,
            "target": {"modality": "effort", "effort_cue": "RPE 6-7, controlled"}}
    recovery = {"type": "recovery", "duration_type": "time", "duration_value": 120,
                "target": {"modality": "effort", "effort_cue": "RPE 2-3, easy"}}
    doc["changes"][0]["after"]["structure"] = [
        {"type": "repeat", "count": 4, "steps": [work, recovery]}, work]
    result = validate_document(doc, context())
    assert result.status == "pending"
    structure = result.doc.changes[0].after.model_dump()["structure"]
    expanded = expand_structure(structure)
    assert len(expanded) == 9
    assert sum(step["duration_value"] for step in expanded) == 23 * 60


def test_v1_unknown_field_rejected() -> None:
    doc = valid_doc()
    doc["extra_field"] = 1
    assert outcome(doc) == ("invalid", [("V1.schema", "extra_field")])


def test_v2_snapshot_older_than_24h() -> None:
    doc = valid_doc()
    ctx = context()
    ctx = replace(ctx, snapshot=replace(ctx.snapshot, generated_at=NOW - timedelta(hours=25)))
    assert outcome(doc, ctx) == ("invalid", [("V2.snapshot_expired", "snapshot_id")])


def test_v3_stale_base_version() -> None:
    doc = valid_doc()
    doc["base_calendar_version"] = 6
    assert outcome(doc) == ("stale", [("V3.stale_base", "base_calendar_version")])


def test_v4_session_in_two_changes() -> None:
    doc = valid_doc()
    doc["changes"].append(change("c2", "delete", 3))
    assert outcome(doc) == ("invalid", [("V4.session_in_multiple_changes", "changes.1.session_uid")])


def test_v5_daily_scope_today_plus_4() -> None:
    doc = valid_doc("proceed_or_modify_today")
    assert outcome(doc, context("proceed_or_modify_today")) == ("invalid", [("V5.out_of_scope", "changes.0")])


def test_v6_recipe_must_be_eligible() -> None:
    doc = valid_doc()
    doc["changes"] = [change("c1", "modify", 3, {"recipe_id": "REC005"})]
    assert outcome(doc) == ("invalid", [("V6.recipe_not_eligible", "changes.0.after.recipe_id")])
    doc["changes"] = [change("c1", "modify", 2, {"intent": "Quality slot"})]
    assert outcome(doc) == ("pending", [])


def test_v7_two_runs_same_date() -> None:
    doc = valid_doc()
    doc["changes"] = [
        change(
            "c1",
            "add",
            None,
            {"local_date": TODAY.replace(day=20).isoformat(), "kind": "run", "intent": "Easy", "recipe_id": "REC001"},
        )
    ]
    assert outcome(doc) == ("invalid", [("V7.multiple_runs_per_day", "changes")])


def test_v8_off_cycle_run_requires_flag() -> None:
    doc = valid_doc()
    doc["changes"] = [change("c1", "move", 3, {"local_date": "2026-11-21"})]
    assert outcome(doc) == ("invalid", [("V8.off_cycle", "changes.0")])
    doc["changes"][0]["material_flags"] = ["off_cycle_run"]
    assert outcome(doc) == ("pending", [])


def test_v9_week_keeps_two_strength() -> None:
    doc = valid_doc()
    doc["changes"] = [change("c1", "delete", 13)]
    assert outcome(doc) == ("invalid", [("V9.strength_count", "changes")])


def test_v9_daily_cannot_move_strength() -> None:
    doc = valid_doc("proceed_or_modify_today")
    doc["changes"] = [change("c1", "move", 11, {"local_date": "2026-11-17"}, ["strength_move"])]
    assert outcome(doc, context("proceed_or_modify_today")) == ("invalid", [("V9.daily_strength_move", "changes.0")])


def test_v9_strength_move_requires_flag() -> None:
    doc = valid_doc()
    doc["changes"] = [change("c1", "move", 13, {"local_date": "2026-11-24"})]
    assert outcome(doc) == ("invalid", [("V9.strength_move_flag", "changes.0")])


def test_v10_two_long_runs_in_week() -> None:
    doc = valid_doc()
    doc["changes"] = [change("c1", "modify", 3, {"recipe_id": "REC002"})]
    assert outcome(doc) == ("invalid", [("V10.multiple_long", "changes")])


def test_v10_move_cannot_increase_quality_count() -> None:
    doc = valid_doc()
    doc["changes"] = [change("c1", "delete", 3), change("c2", "move", 5, {"local_date": "2026-11-20"})]
    assert outcome(doc) == ("invalid", [("V10.quality_pileup", "changes.1")])


def test_v11_unknown_policy_id() -> None:
    doc = valid_doc()
    doc["policy_ids"] = ["P999"]
    assert outcome(doc) == ("invalid", [("V11.unknown_kb_id", "policy_ids.0")])


def test_v12_blocks_increase_after_severity_6_5() -> None:
    doc = valid_doc()
    doc["changes"] = [change("c1", "modify", 1, {"planned_duration_s": 3000})]
    assert outcome(doc, context(guard={"max_symptom_severity": 7.0})) == (
        "invalid",
        [("V12.safety_guard", "changes.0")],
    )
    assert outcome(doc, context(guard={"max_symptom_severity": 6.0})) == ("pending", [])
    ctx = context()
    ctx = replace(ctx, current_safety_guard=None)
    assert outcome(doc, ctx) == ("invalid", [("V12.safety_guard", "changes.0")])


def test_v13_start_only_without_active_block() -> None:
    doc = valid_doc("review_training_block")
    doc["changes"] = []
    doc["block_change"] = {
        "decision": "start",
        "block_uid": None,
        "version_fields": {
            "status": "active",
            "objective": "Build",
            "rationale": "Ready",
            "maintained_qualities": [],
            "non_goals": [],
            "eligible_recipe_ids": ["REC001", "REC002"],
            "progression_dimension": "duration",
            "constraints": [],
            "start_date": "2026-11-16",
            "review_date": "2026-12-28",
            "completion_indicators": [],
            "early_review_triggers": [],
            "objective_status": "unresolved",
        },
    }
    assert outcome(doc, context("review_training_block")) == (
        "invalid",
        [("V13.block_change_invalid", "block_change.decision")],
    )
    doc["base_block_version_id"] = None
    assert outcome(doc, context("review_training_block", block=False)) == ("pending", [])


def test_v14_anchor_low_gt_high() -> None:
    doc = valid_doc("recalibrate_intensity")
    doc["changes"] = []
    doc["anchor_changes"] = [
        {
            "kind": "hr_threshold_lower",
            "value_low": 170,
            "value_high": 165,
            "unit": "bpm",
            "protocol": "manual",
            "confidence": "moderate",
            "calibrated_at": NOW.isoformat(),
        }
    ]
    assert outcome(doc, context("recalibrate_intensity")) == (
        "invalid",
        [("V14.anchor_invalid", "anchor_changes.0.value_high")],
    )
    doc["anchor_changes"][0].update(value_low=160, unit="mps")
    assert outcome(doc, context("recalibrate_intensity")) == (
        "invalid",
        [("V14.anchor_invalid", "anchor_changes.0.unit")],
    )


def test_v15_non_quality_slot() -> None:
    doc = valid_doc("select_quality_session")
    doc["changes"] = [change("c1", "modify", 3, {"recipe_id": "REC003"})]
    assert outcome(doc, context("select_quality_session")) == ("invalid", [("V15.not_quality_slot", "changes.0")])
    doc["changes"] = [change("c1", "modify", 2, {"recipe_id": "REC003"})]
    assert outcome(doc, context("select_quality_session")) == ("pending", [])


def test_partial_accept_revalidates_subset() -> None:
    doc = valid_doc()
    doc["changes"] = [
        change("c1", "add", None, {"local_date": "2026-11-25", "kind": "strength", "intent": "Full body"}),
        change("c2", "delete", 14),
    ]
    ctx = context()
    result = validate_document(doc, ctx)
    assert (result.status, result.issues) == ("pending", [])
    assert [(i.code, i.path) for i in validate_subset(result.doc, {"c2"}, False, set(), ctx)] == [
        ("V9.strength_count", "changes")
    ]
    assert validate_subset(result.doc, {"c1", "c2"}, False, set(), ctx) == []


def test_derive_certainty() -> None:
    assert derive_certainty(date(2026, 11, 22), TODAY) == "committed"
    assert derive_certainty(date(2026, 11, 23), TODAY) == "provisional"


def test_fingerprint_fixture() -> None:
    fixture = json.loads(
        (Path(__file__).parents[3] / "planning/remaining_mvp/contracts/coach-fingerprint.json").read_text()
    )
    vector = fixture["canonical_vector"]
    knowledge = vector["knowledge"]
    kb = VerifiedKnowledge(
        knowledge["digest"],
        tuple(knowledge["selection"]),
        tuple(knowledge["selected_records"]),
        frozenset(),
        frozenset(),
        frozenset(),
    )
    assert fingerprint(vector["source_versions"], kb) == fixture["sha256"]
    changed = json.loads(canonical_json(knowledge["selected_records"]))
    changed[0]["content"]["title"] = "Easy revised"
    changed_kb = replace(kb, selected_records=tuple(changed))
    assert fingerprint(vector["source_versions"], changed_kb) == fixture["changed_selected_content_sha256"]
    assert canonical_json(vector) == canonical_json(json.loads(canonical_json(vector)))


def test_session_fields_excludes_identity_and_preserves_editable_values() -> None:
    fields = session_fields(head(3, 20, "run", "REC001"))
    assert fields["recipe_id"] == "REC001"
    assert set(fields).isdisjoint({"session_uid", "revision", "certainty", "legacy_unstructured"})
    assert {"notes", "structure", "planned_duration_s"} <= set(fields)


def test_subset_numeric_target_requires_matching_anchor_modality() -> None:
    doc = valid_doc("recalibrate_intensity")
    doc["changes"] = [
        change(
            "c1",
            "modify",
            3,
            {
                "structure": [
                    {
                        "type": "work",
                        "duration_type": "time",
                        "duration_value": 600,
                        "target": {"modality": "hr", "low": 150, "high": 160},
                    }
                ]
            },
        )
    ]
    doc["anchor_changes"] = [
        {
            "kind": "hr_threshold_lower",
            "value_low": 165,
            "unit": "bpm",
            "protocol": "manual",
            "confidence": "moderate",
            "calibrated_at": NOW.isoformat(),
        },
        {
            "kind": "speed_threshold_lower",
            "value_low": 3.2,
            "unit": "mps",
            "protocol": "manual",
            "confidence": "moderate",
            "calibrated_at": NOW.isoformat(),
        },
    ]
    ctx = context("recalibrate_intensity")
    result = validate_document(doc, ctx)
    assert result.status == "pending"
    hr_key = anchor_key(result.doc.anchor_changes[0], TZ)
    speed_key = anchor_key(result.doc.anchor_changes[1], TZ)
    issues = validate_subset(result.doc, {"c1"}, False, {speed_key}, ctx)
    assert [(item.code, item.path, item.message) for item in issues] == [
        (
            "V14.anchor_dependency",
            "changes.0.after.structure",
            "Accept the associated anchor or reject the target change",
        )
    ]
    assert validate_subset(result.doc, {"c1"}, False, {hr_key}, ctx) == []


def test_subset_unchanged_numeric_target_needs_no_anchor() -> None:
    doc = valid_doc("recalibrate_intensity")
    structure = [
        {
            "type": "work",
            "duration_type": "time",
            "duration_value": 600,
            "target": {"modality": "hr", "low": 150, "high": 160},
        }
    ]
    revised = [
        {
            "type": "work",
            "duration_type": "time",
            "duration_value": 650,
            "target": {"modality": "hr", "low": 150, "high": 160},
        }
    ]
    doc["changes"] = [change("c1", "modify", 3, {"structure": revised})]
    doc["anchor_changes"] = [
        {
            "kind": "hr_threshold_lower",
            "value_low": 165,
            "unit": "bpm",
            "protocol": "manual",
            "confidence": "moderate",
            "calibrated_at": NOW.isoformat(),
        }
    ]
    ctx = context("recalibrate_intensity")
    ctx = replace(ctx, head_sessions={**ctx.head_sessions, U(3): replace(ctx.head_sessions[U(3)], structure=structure)})
    result = validate_document(doc, ctx)
    assert result.status == "pending"
    assert validate_subset(result.doc, {"c1"}, False, set(), ctx) == []
