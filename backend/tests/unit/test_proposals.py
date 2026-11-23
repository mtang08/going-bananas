from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import get_args
from zoneinfo import ZoneInfo

import pytest

from app.domain.calendar_structure import expand_structure
from app.services.block_benchmark import BenchmarkOutcome, BenchmarkSpec, benchmark_spec
from app.services.decision_inputs import VerifiedKnowledge, canonical_json, fingerprint
from app.services.proposals.schema import (
    ActiveBlock,
    BlockBenchmark,
    EventRef,
    EventReview,
    HeadSession,
    SnapshotRef,
    ValidationContext,
    anchor_key,
    derive_certainty,
    parse_document,
    scope,
)
from app.services.proposals.validation import proposal_freshness, validate_document, validate_subset

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
    active = (
        ActiveBlock(U(100), U(101), 1, ("REC001", "REC002", "REC003", "REC007"), TODAY + timedelta(days=13))
        if block
        else None
    )
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


def exception_block(**overrides) -> dict:
    block = {
        "finding_ids": [str(U(300))],
        "category": "accumulated_fatigue",
        "severity": "caution",
        "confidence": "moderate",
        "triggering_evidence": "Fatigue 8 on two mornings",
        "relevant_context": None,
        "ladder_level": "next_session",
        "patch_window": {"start": "2026-11-16", "end": "2026-11-18"},
        "unchanged": [{"session_uid": str(U(1)), "reason": "Easy run stays"}],
        "reassess_on": "2026-11-19",
        "monitor": ["Morning fatigue"],
        "return_criteria": ["Usual fatigue twice"],
        "escalate_criteria": ["High through Saturday"],
    }
    block.update(overrides)
    return block


def exception_doc(**overrides) -> dict:
    doc = valid_doc("exception_review")
    doc["changes"] = [change("c1", "modify", 2, {"intent": "Easy instead of quality"})]
    doc["exception"] = exception_block(**overrides)
    return doc


def exc_ctx(op: str = "exception_review") -> ValidationContext:
    return replace(
        context(op),
        findings={U(300): "open", U(301): "dismissed"},
        patches={U(400): "open", U(401): "resolved"},
        events={
            U(500): EventRef("completed", date(2026, 11, 14), None),
            U(501): EventRef("cancelled", date(2026, 11, 13), None),
        },
    )


EVENT = {
    "event_id": str(U(500)),
    "activity_id": None,
    "pacing": "Even",
    "effort_and_limiter": "RPE 9, breathing",
    "conditions": None,
    "symptoms": None,
    "recovery_observation": "Normal walking",
    "recalibration": "defer",
    "training_implication": "Easy until fresh",
}


BENCH = {
    "kind": "time_trial",
    "protocol": "5 km solo time trial",
    "planned_date": "2026-12-20",
    "progress_if": "Under 22:00",
    "consolidate_if": "Over 22:30",
}


def test_valid_rolling_proposal_is_pending() -> None:
    assert outcome(valid_doc()) == ("pending", [])
    doc = valid_doc()
    doc["changes"] = []
    assert outcome(doc) == ("pending", [])


@pytest.mark.parametrize(
    "structure",
    [
        [],
        [
            {
                "type": "work",
                "duration_type": "time",
                "duration_value": 180,
                "target": {"modality": "effort", "low": 6, "high": 7, "effort_cue": "Controlled"},
            }
        ],
        [
            {
                "type": "repeat",
                "count": 5,
                "steps": [
                    {
                        "type": "work",
                        "duration_type": "time",
                        "duration_value": 180,
                        "target": {"modality": "effort", "low": 6, "high": 7, "effort_cue": "Controlled"},
                    }
                ],
            }
        ],
        [
            {
                "type": "work",
                "duration_type": "time",
                "duration_value": 180,
                "target": {"modality": "effort", "effort_cue": " "},
            }
        ],
        [
            {
                "type": "work",
                "duration_type": "time",
                "duration_value": 180,
                "target": {"modality": "hr", "low": 160, "high": 150},
            }
        ],
        [{"type": "work", "duration_type": "time", "duration_value": float("inf")}],
        [{"type": "repeat", "count": 101, "steps": [{"type": "work", "duration_type": "time", "duration_value": 180}]}],
    ],
)
def test_invalid_workout_structure_rejected_on_submit_and_acceptance(structure: list) -> None:
    doc = valid_doc()
    doc["changes"][0]["after"]["structure"] = structure
    result = validate_document(doc, context())
    expected = [("V6.invalid_structure", "changes.0.after.structure")]
    assert result.status == "invalid"
    assert [(issue.code, issue.path) for issue in result.issues] == expected
    # Older pending proposals must still parse, but cannot apply malformed steps.
    assert result.doc is not None
    assert [
        (issue.code, issue.path) for issue in validate_subset(result.doc, {"c1"}, False, set(), context())
    ] == expected
    assert validate_subset(result.doc, set(), False, set(), context()) == []


def test_effort_intervals_use_cues_and_expand_for_calendar() -> None:
    doc = valid_doc()
    work = {
        "type": "work",
        "duration_type": "time",
        "duration_value": 180,
        "target": {"modality": "effort", "effort_cue": "RPE 6-7, controlled"},
    }
    recovery = {
        "type": "recovery",
        "duration_type": "time",
        "duration_value": 120,
        "target": {"modality": "effort", "effort_cue": "RPE 2-3, easy"},
    }
    doc["changes"][0]["after"]["structure"] = [{"type": "repeat", "count": 4, "steps": [work, recovery]}, work]
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


def omission(change_id: str, day: int) -> dict:
    return {
        **change(
            change_id,
            "add",
            None,
            {"local_date": f"2026-11-{day}", "kind": "rest", "intent": "Omit full-body B"},
            ["strength_omission"],
        ),
        "reason": "Travel prevents access to the gym",
    }


def test_v9_explicit_deletions_cover_a_week_with_no_remaining_lifts() -> None:
    ctx = context()
    ctx = replace(
        ctx,
        head_sessions={
            uid: row for uid, row in ctx.head_sessions.items() if row.local_date.day < 23 or row.kind == "strength"
        },
    )
    doc = valid_doc()
    doc["changes"] = [change("c1", "delete", 13, flags=["strength_omission"]), change("c2", "delete", 14)]
    assert outcome(doc, ctx) == ("invalid", [("V9.strength_count", "changes")])
    doc["changes"][1]["material_flags"] = ["strength_omission"]
    result = validate_document(doc, ctx)
    assert (result.status, result.issues) == ("pending", [])
    assert result.doc is not None
    assert validate_subset(result.doc, {"c1"}, False, set(), ctx) == []
    assert validate_subset(result.doc, {"c1", "c2"}, False, set(), ctx) == []


def test_v9_unmaterialized_omission_can_coexist_with_run_and_must_be_selected() -> None:
    ctx = context()
    ctx = replace(
        ctx,
        head_sessions={uid: row for uid, row in ctx.head_sessions.items() if uid != U(12)},
        confirmed_strength_dates=frozenset({date(2026, 11, 20)}),
    )
    doc = valid_doc()
    doc["changes"].append(omission("c2", 20))
    result = validate_document(doc, ctx)
    assert (result.status, result.issues) == ("pending", [])
    assert result.doc is not None
    assert [(issue.code, issue.path) for issue in validate_subset(result.doc, {"c1"}, False, set(), ctx)] == [
        ("V9.strength_count", "changes")
    ]
    assert validate_subset(result.doc, {"c2"}, False, set(), ctx) == []
    assert validate_subset(result.doc, set(), False, set(), ctx) == []


def test_v9_unmaterialized_omissions_count_even_in_an_empty_week() -> None:
    ctx = context()
    ctx = replace(
        ctx,
        head_sessions={uid: row for uid, row in ctx.head_sessions.items() if row.local_date.day < 23},
        confirmed_strength_dates=frozenset({date(2026, 11, 23), date(2026, 11, 27)}),
    )
    doc = valid_doc()
    doc["changes"] = [omission("c1", 23)]
    assert outcome(doc, ctx) == ("invalid", [("V9.strength_count", "changes")])
    doc["changes"].append(omission("c2", 27))
    assert outcome(doc, ctx) == ("pending", [])


@pytest.mark.parametrize(
    "changes",
    [
        [omission("c1", 19)],
        [omission("c1", 20)],
        [{**omission("c1", 17), "reason": "  "}],
        [change("c1", "delete", 3, flags=["strength_omission"])],
        [change("c1", "move", 13, {"local_date": "2026-11-24"}, ["strength_move", "strength_omission"])],
        [
            change("c1", "delete", 13, flags=["strength_omission"]),
            change("c2", "add", None, {"local_date": "2026-11-23", "kind": "strength", "intent": "Full body"}),
        ],
        [
            omission("c1", 17),
            change("c2", "move", 11, {"local_date": "2026-11-17"}, ["strength_move"]),
        ],
    ],
)
def test_v9_omission_requires_a_valid_absent_lift(changes: list[dict]) -> None:
    ctx = replace(context(), confirmed_strength_dates=frozenset({date(2026, 11, 17), date(2026, 11, 20)}))
    doc = valid_doc()
    doc["changes"] = changes
    assert any(code == "V9.strength_omission_invalid" for code, _ in outcome(doc, ctx)[1])


def test_v9_duplicate_dates_cannot_be_counted_twice() -> None:
    ctx = replace(context(), confirmed_strength_dates=frozenset({date(2026, 11, 17)}))
    doc = valid_doc()
    doc["changes"] = [omission("c1", 17), omission("c2", 17)]
    assert outcome(doc, ctx) == ("invalid", [("V9.strength_omission_duplicate", "changes.1")])
    ctx = replace(ctx, accepted_strength_omission_dates=frozenset({date(2026, 11, 17)}))
    doc["changes"].pop()
    assert outcome(doc, ctx) == ("invalid", [("V9.strength_omission_duplicate", "changes.0")])


def test_v9_an_unrelated_omission_cannot_pay_for_moving_a_lift_out_of_a_week() -> None:
    ctx = replace(context(), confirmed_strength_dates=frozenset({date(2026, 11, 25)}))
    doc = valid_doc()
    doc["changes"] = [
        omission("c1", 25),
        change("c2", "move", 13, {"local_date": "2026-11-17"}, ["strength_move"]),
    ]
    assert outcome(doc, ctx) == ("invalid", [("V9.strength_count", "changes")])


def test_v9_accepted_omissions_only_cover_still_absent_lifts() -> None:
    ctx = context()
    omissions = frozenset({date(2026, 11, 23)})
    ctx = replace(ctx, accepted_strength_omission_dates=omissions)
    doc = valid_doc()
    doc["changes"] = [change("c1", "delete", 13)]
    assert outcome(doc, ctx) == ("invalid", [("V9.strength_count", "changes")])
    remaining = {uid: row for uid, row in ctx.head_sessions.items() if uid != U(13)}
    without_lift = replace(ctx, head_sessions=remaining)
    assert outcome(valid_doc(), without_lift) == ("pending", [])
    doc["changes"] = [change("c1", "move", 14, {"local_date": "2026-11-23"}, ["strength_move"])]
    assert outcome(doc, without_lift) == ("invalid", [("V9.strength_count", "changes")])


def test_v9_omission_cannot_target_a_routine_slot_planned_on_a_different_date() -> None:
    ctx = context()
    remaining = {uid: row for uid, row in ctx.head_sessions.items() if uid != U(12)}
    remaining[U(11)] = replace(remaining[U(11)], strength_slot_id=U(21))
    tue, fri = date(2026, 11, 17), date(2026, 11, 20)
    ctx = replace(
        ctx,
        head_sessions=remaining,
        confirmed_strength_dates=frozenset({tue, fri}),
        confirmed_strength_slot_ids={tue: U(21), fri: U(22)},
    )
    doc = valid_doc()
    doc["changes"] = [omission("c1", 17)]
    assert ("V9.strength_omission_invalid", "changes.0") in outcome(doc, ctx)[1]
    ctx = replace(
        ctx,
        accepted_strength_omission_dates=frozenset({tue}),
        accepted_strength_omission_slot_ids={tue: U(21)},
    )
    assert outcome(valid_doc(), ctx) == ("invalid", [("V9.strength_count", "changes")])
    doc["changes"] = [omission("c1", 20)]
    assert outcome(doc, ctx) == ("pending", [])
    doc["changes"].append(
        change(
            "c2",
            "add",
            None,
            {"local_date": "2026-11-19", "kind": "strength", "intent": "Full body", "strength_slot_id": str(U(22))},
        )
    )
    assert outcome(doc, ctx) == ("invalid", [("V9.strength_omission_invalid", "changes.0")])


def test_v9_two_occurrences_of_the_same_routine_template_remain_distinct() -> None:
    ctx = context()
    remaining = {uid: row for uid, row in ctx.head_sessions.items() if uid != U(11)}
    remaining[U(12)] = replace(remaining[U(12)], strength_slot_id=U(21))
    tue, fri = date(2026, 11, 17), date(2026, 11, 20)
    ctx = replace(
        ctx,
        head_sessions=remaining,
        confirmed_strength_dates=frozenset({tue, fri}),
        confirmed_strength_slot_ids={tue: U(21), fri: U(21)},
    )
    doc = valid_doc()
    doc["changes"] = [omission("c1", 17)]
    assert outcome(doc, ctx) == ("pending", [])


def test_v9_daily_operations_cannot_omit_strength() -> None:
    doc = valid_doc("proceed_or_modify_today")
    doc["changes"] = [omission("c1", 17), change("c2", "delete", 11, flags=["strength_omission"])]
    ctx = replace(context("proceed_or_modify_today"), confirmed_strength_dates=frozenset({date(2026, 11, 17)}))
    assert outcome(doc, ctx) == (
        "invalid",
        [("V9.daily_strength_change", "changes.1"), ("V9.daily_strength_change", "changes.0")],
    )


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
            "eligible_recipe_ids": ["REC001", "REC002", "REC009"],
            "progression_dimension": "duration",
            "constraints": [],
            "start_date": "2026-11-16",
            "review_date": "2026-12-28",
            "completion_indicators": [],
            "early_review_triggers": [],
            "objective_status": "unresolved",
            "benchmark": BENCH,
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
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/coach-fingerprint.json").read_text())
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


@pytest.mark.parametrize(
    "op,days",
    [("proceed_or_modify_today", 3), ("review_rolling_plan", 13), ("exception_review", 6), ("post_event_review", 6)],
)
def test_scope_by_operation(op: str, days: int) -> None:
    assert scope(op, TODAY) == (TODAY, TODAY + timedelta(days=days))


@pytest.mark.parametrize(
    "op,review_offset,days",
    [
        ("review_rolling_plan", 28, 28),
        ("review_rolling_plan", 7, 13),
        ("review_rolling_plan", 60, 42),
        ("review_rolling_plan", -3, 13),
        ("review_rolling_plan", None, 13),
        ("review_training_block", 35, 35),
        ("handle_goal_or_race_change", 20, 20),
        ("exception_review", 28, 6),
        ("post_event_review", 28, 6),
        ("proceed_or_modify_today", 28, 3),
        ("select_quality_session", 28, 13),
        ("recalibrate_intensity", 28, 13),
    ],
)
def test_scope_horizon_clamp(op: str, review_offset: int | None, days: int) -> None:
    review = None if review_offset is None else TODAY + timedelta(days=review_offset)
    assert scope(op, TODAY, review) == (TODAY, TODAY + timedelta(days=days))


def test_changes_limit_is_eighty() -> None:
    doc = valid_doc()
    doc["changes"] = [change(f"c{i}", "delete", 1) for i in range(1, 81)]
    assert parse_document(doc)[1] == []
    doc["changes"].append(change("c81", "delete", 1))
    assert [(issue.code, issue.path) for issue in parse_document(doc)[1]] == [("V1.schema", "changes")]


def test_exception_schema_errors() -> None:
    for doc in (
        exception_doc(monitor=[]),
        exception_doc(category="post_event"),
        exception_doc(confidence="medium"),
        exception_doc(extra=1),
    ):
        status, issues = outcome(doc)
        assert status == "invalid"
        assert issues and all(code == "V1.schema" for code, _ in issues)


def test_old_payload_without_new_fields_still_parses() -> None:
    result = validate_document(valid_doc(), context())
    assert result.doc is not None
    assert result.doc.exception is None and result.doc.event_review is None and result.doc.patch_resolutions == []


def test_exception_doc_is_pending() -> None:
    assert outcome(exception_doc(), exc_ctx()) == ("pending", [])


def test_v16_exception_required_and_forbidden() -> None:
    doc = exception_doc()
    del doc["exception"]
    assert outcome(doc, exc_ctx()) == ("invalid", [("V16.exception_required", "exception")])
    doc = valid_doc()
    doc["exception"] = exception_block()
    assert outcome(doc, exc_ctx("review_rolling_plan")) == ("invalid", [("V16.exception_forbidden", "exception")])


def test_v17_window_out_of_scope() -> None:
    doc = exception_doc(
        severity="hold", ladder_level="committed_window", patch_window={"start": "2026-11-15", "end": "2026-11-18"}
    )
    assert outcome(doc, exc_ctx()) == ("invalid", [("V17.window_out_of_scope", "exception.patch_window")])


def test_v17_window_too_long() -> None:
    doc = exception_doc(patch_window={"start": "2026-11-16", "end": "2026-11-19"})
    assert outcome(doc, exc_ctx()) == ("invalid", [("V17.window_too_long", "exception.patch_window")])


def test_v17_change_outside_window() -> None:
    doc = exception_doc(patch_window={"start": "2026-11-16", "end": "2026-11-17"})
    assert outcome(doc, exc_ctx()) == ("invalid", [("V17.change_outside_window", "changes.0")])


def test_v17_reassess_out_of_range() -> None:
    doc = exception_doc(reassess_on="2026-11-24")
    assert outcome(doc, exc_ctx()) == ("invalid", [("V17.reassess_out_of_range", "exception.reassess_on")])


def test_v9_exception_review_cannot_move_strength() -> None:
    doc = exception_doc()
    doc["changes"] = [change("c1", "move", 11, {"local_date": "2026-11-17"}, ["strength_move"])]
    assert outcome(doc, exc_ctx()) == ("invalid", [("V9.daily_strength_move", "changes.0")])


def test_v9_exception_review_cannot_add_strength() -> None:
    doc = exception_doc()
    doc["changes"] = [
        change("c1", "add", None, {"local_date": "2026-11-17", "kind": "strength", "intent": "Full body"})
    ]
    assert outcome(doc, exc_ctx()) == ("invalid", [("V9.daily_strength_change", "changes.0")])


def test_subset_skips_exception_rules() -> None:
    doc = exception_doc(ladder_level="current_session")
    ctx = exc_ctx()
    result = validate_document(doc, ctx)
    assert (result.status, result.issues) == ("pending", [])
    assert validate_subset(result.doc, set(), False, set(), replace(ctx, findings={})) == []


LADDER_MISMATCH = ("invalid", [("V18.ladder_mismatch", "exception.ladder_level")])


def test_v18_next_session_allows_one_change() -> None:
    doc = exception_doc(severity="hold", patch_window={"start": "2026-11-16", "end": "2026-11-20"})
    doc["changes"].append(change("c2", "modify", 3, {"intent": "Easy"}))
    assert outcome(doc, exc_ctx()) == LADDER_MISMATCH


def test_v18_current_session_zero_changes_only_for_observe() -> None:
    doc = exception_doc(ladder_level="current_session")
    doc["changes"] = []
    assert outcome(doc, exc_ctx()) == LADDER_MISMATCH
    doc = exception_doc(ladder_level="current_session", severity="observe")
    doc["changes"] = []
    assert outcome(doc, exc_ctx()) == ("pending", [])


def test_v18_committed_window_and_next_days() -> None:
    assert outcome(exception_doc(ladder_level="committed_window"), exc_ctx()) == LADDER_MISMATCH
    doc = exception_doc(
        severity="hold", ladder_level="next_days", patch_window={"start": "2026-11-16", "end": "2026-11-19"}
    )
    assert outcome(doc, exc_ctx()) == LADDER_MISMATCH


def test_v18_block_needs_escalate_and_escalation() -> None:
    doc = exception_doc(severity="escalate", ladder_level="block")
    assert outcome(doc, exc_ctx()) == LADDER_MISMATCH
    doc["escalation"] = "review_training_block"
    assert outcome(doc, exc_ctx()) == ("pending", [])


def test_v19_unchanged_touched_session() -> None:
    doc = exception_doc(unchanged=[{"session_uid": str(U(2)), "reason": "x"}])
    assert outcome(doc, exc_ctx()) == ("invalid", [("V19.unchanged_invalid", "exception.unchanged.0")])


def test_v19_unchanged_outside_window_or_unknown() -> None:
    doc = exception_doc(
        unchanged=[{"session_uid": str(U(7)), "reason": "x"}, {"session_uid": str(U(999)), "reason": "x"}]
    )
    assert outcome(doc, exc_ctx()) == (
        "invalid",
        [("V19.unchanged_invalid", "exception.unchanged.0"), ("V19.unchanged_invalid", "exception.unchanged.1")],
    )


def test_v19_unchanged_duplicate() -> None:
    doc = exception_doc(
        unchanged=[{"session_uid": str(U(1)), "reason": "a"}, {"session_uid": str(U(1)), "reason": "b"}]
    )
    assert outcome(doc, exc_ctx()) == ("invalid", [("V19.unchanged_invalid", "exception.unchanged.1")])


ANCHOR = {
    "kind": "hr_threshold_lower",
    "value_low": 160,
    "unit": "bpm",
    "protocol": "manual",
    "confidence": "moderate",
    "calibrated_at": NOW.isoformat(),
}


def test_v20_finding_unknown_and_closed() -> None:
    doc = exception_doc(finding_ids=[str(U(999)), str(U(301))])
    assert outcome(doc, exc_ctx()) == (
        "invalid",
        [("V20.finding_unknown", "exception.finding_ids.0"), ("V20.finding_closed", "exception.finding_ids.1")],
    )


def test_v20_post_event_requires_event_review() -> None:
    ctx = exc_ctx("post_event_review")
    doc = valid_doc("post_event_review")
    assert outcome(doc, ctx) == ("invalid", [("V20.event_required", "event_review")])
    doc["event_review"] = EVENT
    assert outcome(doc, ctx) == ("pending", [])
    doc["event_review"] = {**EVENT, "event_id": str(U(501))}
    assert outcome(doc, ctx) == ("invalid", [("V20.event_unknown", "event_review.event_id")])


def test_v20_event_review_forbidden_elsewhere() -> None:
    doc = valid_doc()
    doc["event_review"] = EVENT
    assert outcome(doc, exc_ctx("review_rolling_plan")) == ("invalid", [("V20.event_forbidden", "event_review")])


def test_v21_resolution_forbidden_for_quality_session() -> None:
    doc = valid_doc("select_quality_session")
    doc["changes"] = []
    doc["patch_resolutions"] = [{"patch_id": str(U(400)), "status": "resolved", "note": "ok"}]
    assert outcome(doc, exc_ctx("select_quality_session")) == (
        "invalid",
        [("V21.resolution_forbidden", "patch_resolutions")],
    )


def test_v21_patch_unknown_closed_duplicate() -> None:
    doc = valid_doc()
    doc["patch_resolutions"] = [
        {"patch_id": str(U(n)), "status": "resolved", "note": "ok"} for n in (999, 401, 400, 400)
    ]
    assert outcome(doc, exc_ctx("review_rolling_plan")) == (
        "invalid",
        [
            ("V21.patch_unknown", "patch_resolutions.0.patch_id"),
            ("V21.patch_closed", "patch_resolutions.1.patch_id"),
            ("V21.patch_duplicate", "patch_resolutions.3.patch_id"),
        ],
    )


def test_v14_post_event_review_allows_anchors() -> None:
    doc = valid_doc("post_event_review")
    doc["event_review"] = EVENT
    doc["changes"] = []
    doc["anchor_changes"] = [ANCHOR]
    assert outcome(doc, exc_ctx("post_event_review")) == ("pending", [])
    doc = valid_doc()
    doc["anchor_changes"] = [ANCHOR]
    assert outcome(doc, exc_ctx("review_rolling_plan")) == (
        "invalid",
        [("V14.anchor_change_not_allowed", "anchor_changes")],
    )


def test_block_benchmark_round_trips_through_benchmark_spec() -> None:
    cases = [
        (
            {**BENCH, "kind": "event", "event_id": str(U(500)), "distance_m": 5000},
            BenchmarkSpec("event", U(500), "5 km solo time trial", 5000, date(2026, 12, 20)),
        ),
        (BENCH, BenchmarkSpec("time_trial", None, "5 km solo time trial", None, date(2026, 12, 20))),
    ]
    for raw, expected in cases:
        dumped = BlockBenchmark.model_validate(raw).model_dump(mode="json")
        assert benchmark_spec(SimpleNamespace(benchmark=dumped)) == expected


def test_event_review_outcome_vocabulary() -> None:
    assert BenchmarkOutcome in get_args(EventReview.model_fields["outcome"].annotation)
    doc = valid_doc("review_training_block")
    doc["event_review"] = {**EVENT, "outcome": "great"}
    status, issues = outcome(doc)
    assert status == "invalid"
    assert issues and all(code == "V1.schema" for code, _ in issues)


def week_adds() -> list[dict]:
    return [
        change("c1", "add", None, {"local_date": "2026-12-01", "kind": "strength", "intent": "Full body"}),
        change("c2", "add", None, {"local_date": "2026-12-03", "kind": "strength", "intent": "Full body"}),
    ]


def block_start_doc(**field_overrides) -> dict:
    doc = valid_doc("review_training_block")
    doc["changes"] = []
    doc["base_block_version_id"] = None
    doc["block_change"] = {
        "decision": "start",
        "block_uid": None,
        "version_fields": {
            "status": "active",
            "objective": "Build",
            "rationale": "Ready",
            "maintained_qualities": [],
            "non_goals": [],
            "eligible_recipe_ids": ["REC001", "REC002", "REC009"],
            "progression_dimension": "duration",
            "constraints": [],
            "start_date": "2026-11-16",
            "review_date": "2026-12-28",
            "completion_indicators": [],
            "early_review_triggers": [],
            "objective_status": "unresolved",
            "benchmark": BENCH,
            **field_overrides,
        },
    }
    return doc


BENCHMARK_EVENT_ISSUE = ("invalid", [("V22.benchmark_event", "block_change.version_fields.benchmark")])


def bench_ctx(codes: frozenset[str] = frozenset({"BLOCK_BENCHMARK_COMPLETED"})) -> ValidationContext:
    return replace(
        exc_ctx("review_training_block"),
        open_rule_codes=codes,
        benchmark=SimpleNamespace(status="completed", activity_id=U(600), event_id=None),
    )


def test_v22_benchmark_required() -> None:
    doc = block_start_doc()
    del doc["block_change"]["version_fields"]["benchmark"]
    assert outcome(doc, context("review_training_block", block=False)) == (
        "invalid",
        [("V22.benchmark_required", "block_change.version_fields.benchmark")],
    )


def test_benchmark_issues_precede_patch_resolution_issues() -> None:
    doc = block_start_doc(benchmark=None)
    doc["patch_resolutions"] = [{"patch_id": str(U(999)), "status": "resolved", "note": "Settled"}]
    assert outcome(doc, context("review_training_block", block=False)) == (
        "invalid",
        [
            ("V22.benchmark_required", "block_change.version_fields.benchmark"),
            ("V21.patch_unknown", "patch_resolutions.0.patch_id"),
        ],
    )


@pytest.mark.parametrize(
    "planned,ok",
    [("2026-12-14", False), ("2026-12-15", True), ("2026-12-21", True), ("2026-12-22", False)],
)
def test_v22_benchmark_date_window(planned: str, ok: bool) -> None:
    doc = block_start_doc(benchmark={**BENCH, "planned_date": planned})
    expected = (
        ("pending", [])
        if ok
        else (
            "invalid",
            [("V22.benchmark_date", "block_change.version_fields.benchmark.planned_date")],
        )
    )
    assert outcome(doc, context("review_training_block", block=False)) == expected


def test_horizon_follows_active_block_review_date() -> None:
    doc = valid_doc()
    doc["changes"] = week_adds()
    ctx = context()
    assert outcome(doc, ctx) == (
        "invalid",
        [("V5.out_of_scope", "changes.0"), ("V5.out_of_scope", "changes.1")],
    )
    far = replace(ctx, active_block=replace(ctx.active_block, review_date=TODAY + timedelta(days=28)))
    assert outcome(doc, far) == ("pending", [])
    messages = [issue.message for issue in validate_document(doc, ctx).issues]
    assert all("block review date" in message for message in messages)


def block_review_doc(review_date: str, benchmark_date: str) -> dict:
    doc = block_start_doc(review_date=review_date, benchmark={**BENCH, "planned_date": benchmark_date})
    doc["base_block_version_id"] = str(U(101))
    doc["block_change"].update(decision="continue", block_uid=str(U(100)))
    doc["changes"] = week_adds()
    return doc


def test_block_review_scope_uses_proposed_review_date_and_partial_accept_is_strict() -> None:
    ctx = context("review_training_block")
    doc = block_review_doc("2026-12-14", "2026-12-05")
    result = validate_document(doc, ctx)
    assert (result.status, result.issues) == ("pending", [])
    assert validate_subset(result.doc, {"c1", "c2"}, True, set(), ctx) == []
    rejected = validate_subset(result.doc, {"c1", "c2"}, False, set(), ctx)
    assert [(i.code, i.path) for i in rejected] == [("V5.out_of_scope", "changes.0"), ("V5.out_of_scope", "changes.1")]
    assert validate_subset(result.doc, set(), False, set(), ctx) == []


def test_ended_block_gives_minimum_horizon() -> None:
    doc = block_start_doc(status="ended")
    doc["base_block_version_id"] = str(U(101))
    doc["block_change"].update(decision="end", block_uid=str(U(100)))
    doc["changes"] = week_adds()
    issues = outcome(doc, context("review_training_block"))[1]
    assert ("V5.out_of_scope", "changes.0") in issues


def test_v9_skips_empty_weeks_but_not_partial_weeks() -> None:
    ctx = context("review_training_block", block=False)
    assert outcome(block_start_doc(), ctx) == ("pending", [])
    doc = block_start_doc()
    doc["changes"] = week_adds()[:1]
    assert outcome(doc, ctx) == ("invalid", [("V9.strength_count", "changes")])
    doc["changes"] = week_adds()
    assert outcome(doc, ctx) == ("pending", [])


def test_v22_benchmark_optional_after_recent_credible_result() -> None:
    doc = block_start_doc(benchmark=None, completion_indicators=["REC002 reps hold at RPE 7 or lower"])
    ctx = context("review_training_block", block=False)
    required = ("invalid", [("V22.benchmark_required", "block_change.version_fields.benchmark")])
    assert outcome(doc, replace(ctx, last_benchmark_date=date(2026, 11, 10))) == ("pending", [])
    assert outcome(doc, replace(ctx, last_benchmark_date=date(2026, 11, 9))) == required
    assert outcome(doc, ctx) == required
    message = validate_document(doc, replace(ctx, last_benchmark_date=date(2026, 11, 9))).issues[0].message
    assert "2026-11-09" in message and "2026-12-27" in message
    doc["block_change"]["version_fields"]["completion_indicators"] = []
    assert outcome(doc, replace(ctx, last_benchmark_date=date(2026, 11, 10))) == (
        "invalid",
        [("V22.indicators_required", "block_change.version_fields.completion_indicators")],
    )


def test_v22_result_recorded_in_this_review_counts_unless_inconclusive() -> None:
    doc = block_review_doc("2026-12-14", "2026-12-05")
    doc["changes"] = []
    doc["block_change"]["version_fields"].update(benchmark=None, completion_indicators=["Easy runs stay at RPE 3"])
    doc["event_review"] = {**EVENT, "event_id": None, "activity_id": str(U(600)), "outcome": "progress"}
    ctx = replace(
        bench_ctx(),
        benchmark=SimpleNamespace(status="completed", activity_id=U(600), event_id=None, local_date=date(2026, 11, 14)),
    )
    assert outcome(doc, ctx) == ("pending", [])
    doc["event_review"]["outcome"] = "inconclusive"
    assert outcome(doc, ctx) == ("invalid", [("V22.benchmark_required", "block_change.version_fields.benchmark")])


def test_v22_time_trial_needs_rec009() -> None:
    doc = block_start_doc(eligible_recipe_ids=["REC001", "REC002"])
    assert outcome(doc, context("review_training_block", block=False)) == BENCHMARK_EVENT_ISSUE


def test_v22_event_benchmark() -> None:
    ctx_e = replace(
        context("review_training_block", block=False),
        events={
            U(500): EventRef("completed", date(2026, 12, 20), None),
            U(501): EventRef("completed", date(2026, 11, 14), None),
        },
    )
    assert outcome(block_start_doc(benchmark={**BENCH, "kind": "event", "event_id": str(U(500))}), ctx_e) == (
        "pending",
        [],
    )
    assert outcome(block_start_doc(benchmark={**BENCH, "kind": "event", "event_id": str(U(501))}), ctx_e) == (
        BENCHMARK_EVENT_ISSUE
    )
    assert outcome(block_start_doc(benchmark={**BENCH, "event_id": str(U(500))}), ctx_e) == BENCHMARK_EVENT_ISSUE


GOAL = U(510)
RACE = date(2026, 12, 20)  # inside the fixture block, on or before its review date
TARGET_PATH = "block_change.version_fields.target_event_id"


def target_ctx(**events: EventRef) -> ValidationContext:
    refs = {U(int(key.removeprefix("e"))): ref for key, ref in events.items()}
    return replace(context("review_training_block", block=False), events=refs)


def target_doc(target: uuid.UUID | None = GOAL, **fields) -> dict:
    return block_start_doc(target_event_id=str(target) if target else None, **fields)


def goal(rank: int = 1, day: date = RACE) -> EventRef:
    return EventRef("registered", day, rank)


def test_v23_active_or_consolidating_block_targets_the_goal_race() -> None:
    ctx = target_ctx(e510=goal())
    assert outcome(target_doc(), ctx) == ("pending", [])
    assert outcome(target_doc(status="consolidating"), ctx) == ("pending", [])


def test_v23_target_required_only_for_active_or_consolidating_blocks() -> None:
    ctx = target_ctx(e510=goal())
    required = ("invalid", [("V23.target_event_required", TARGET_PATH)])
    assert outcome(target_doc(None), ctx) == required
    assert outcome(target_doc(None, status="consolidating"), ctx) == required
    assert outcome(target_doc(None, status="ended"), ctx) == ("pending", [])


def test_v23_no_upcoming_event_means_no_target() -> None:
    ctx = target_ctx(e500=EventRef("completed", date(2026, 11, 14), None))
    assert outcome(target_doc(None), ctx) == ("pending", [])


@pytest.mark.parametrize(
    "events",
    [
        {},  # unknown id, and no upcoming event
        {"e510": EventRef("completed", date(2026, 11, 14), None)},  # past
        {"e510": EventRef("cancelled", RACE, None)},
    ],
)
def test_v23_target_invalid(events: dict) -> None:
    assert outcome(target_doc(), target_ctx(**events)) == ("invalid", [("V23.target_event_invalid", TARGET_PATH)])


def test_v23_target_must_be_rank_one() -> None:
    ctx = target_ctx(e510=goal(rank=2), e511=goal(rank=1))
    assert outcome(target_doc(), ctx) == ("invalid", [("V23.target_event_not_top", TARGET_PATH)])


def test_v23_block_cannot_start_after_the_goal_race() -> None:
    ctx = target_ctx(e510=goal(day=date(2026, 11, 20)))
    assert outcome(target_doc(start_date="2026-11-21"), ctx) == ("invalid", [("V23.target_event_date", TARGET_PATH)])
    assert outcome(target_doc(start_date="2026-11-20"), ctx) == ("pending", [])  # race on the start day


REVIEW = date(2026, 12, 28)
FAR = date(2027, 3, 14)  # 76 days after the review date
OUTLINE = [
    {"emphasis": "threshold durability", "weeks": 4},
    {"emphasis": "half-marathon-specific endurance", "weeks": 5},
    {"emphasis": "sharpening and taper", "weeks": 2},
]  # W = 11, last step 2 weeks: the race must fall in (REVIEW + 63 days, REVIEW + 77 days]
OUTLINE_PATH = "block_change.version_fields.build_outline"


def test_v23_outline_reaching_a_far_goal_race_passes() -> None:
    ctx = target_ctx(e510=goal(day=FAR))
    assert outcome(target_doc(build_outline=OUTLINE), ctx) == ("pending", [])
    assert outcome(target_doc(build_outline=OUTLINE, status="consolidating"), ctx) == ("pending", [])


def test_v23_outline_must_be_empty_without_a_target() -> None:
    ctx = target_ctx(e500=EventRef("completed", date(2026, 11, 14), None))
    assert outcome(target_doc(None, build_outline=OUTLINE), ctx) == (
        "invalid",
        [("V23.build_outline_span", OUTLINE_PATH)],
    )


@pytest.mark.parametrize(
    "race_offset,outline,ok",
    [
        (63, OUTLINE, False),  # race before the last step starts
        (64, OUTLINE, True),  # first day of the last step
        (77, OUTLINE, True),  # last day of the outline
        (78, OUTLINE, False),
        (76, [], False),  # race beyond the review date, no outline
        (28, [{"emphasis": "taper", "weeks": 2}], False),  # outline ends before race day
        (-7, OUTLINE, False),  # race on or before the review date: outline must be empty
        (-7, [], True),
    ],
)
def test_v23_build_outline_span(race_offset: int, outline: list, ok: bool) -> None:
    ctx = target_ctx(e510=goal(day=REVIEW + timedelta(days=race_offset)))
    v23 = [issue for issue in outcome(target_doc(build_outline=outline), ctx)[1] if issue[0].startswith("V23")]
    assert v23 == ([] if ok else [("V23.build_outline_span", OUTLINE_PATH)])


def test_v20_event_target_and_outcome_scope() -> None:
    ctx = exc_ctx("post_event_review")
    doc = valid_doc("post_event_review")
    doc["event_review"] = {**EVENT, "event_id": None}
    assert outcome(doc, ctx) == (
        "invalid",
        [("V20.event_target_invalid", "event_review"), ("V20.event_unknown", "event_review.event_id")],
    )
    doc["event_review"] = {**EVENT, "outcome": "progress"}
    assert outcome(doc, ctx) == ("invalid", [("V20.event_forbidden", "event_review.outcome")])


def test_v20_block_review_benchmark_target() -> None:
    doc = valid_doc("review_training_block")
    doc["changes"] = []
    assert outcome(doc, bench_ctx()) == ("invalid", [("V20.event_required", "event_review")])
    doc["event_review"] = {**EVENT, "event_id": None, "activity_id": str(U(600)), "outcome": "progress"}
    assert outcome(doc, bench_ctx()) == ("pending", [])
    doc["event_review"] = {**EVENT, "event_id": None, "activity_id": str(U(601)), "outcome": "progress"}
    assert outcome(doc, bench_ctx()) == ("invalid", [("V20.event_target_invalid", "event_review")])


def test_v14_block_review_anchor_needs_event_review() -> None:
    doc = valid_doc("review_training_block")
    doc["changes"] = []
    doc["event_review"] = {**EVENT, "event_id": None, "activity_id": str(U(600)), "outcome": "progress"}
    doc["anchor_changes"] = [ANCHOR]
    assert outcome(doc, bench_ctx()) == ("pending", [])
    del doc["event_review"]
    assert outcome(doc, bench_ctx(frozenset())) == ("invalid", [("V14.anchor_change_not_allowed", "anchor_changes")])


def test_rule_issue_order_is_pinned() -> None:
    doc = valid_doc()
    doc["changes"] = [
        change("c1", "modify", 3, {"recipe_id": "REC099"}),
        change("c1", "move", 11, {"local_date": "2026-11-17"}),
        change(
            "c3",
            "add",
            None,
            {
                "local_date": "2026-12-30",
                "kind": "run",
                "recipe_id": "REC001",
                "intent": "Easy",
                "planned_duration_s": 1800,
            },
        ),
        change("c4", "modify", 99, {"intent": "Unknown"}),
        change("c5", "modify", 3, {"intent": "Again"}),
    ]
    doc["preserved"] = [str(U(98))]
    doc["evidence_ids"] = ["E-NOPE-01"]
    EXPECTED = (
        "invalid",
        [
            ("V6.unknown_recipe", "changes.0.after.recipe_id"),
            ("V4.duplicate_change_id", "changes.1.change_id"),
            ("V9.strength_move_flag", "changes.1"),
            ("V5.out_of_scope", "changes.2"),
            ("V4.unknown_session", "changes.3.session_uid"),
            ("V4.session_in_multiple_changes", "changes.4.session_uid"),
            ("V4.unknown_preserved", "preserved.0"),
            ("V11.unknown_kb_id", "evidence_ids.0"),
        ],
    )
    assert outcome(doc) == EXPECTED
    assert [(issue.code, issue.path, issue.message) for issue in validate_document(doc, context()).issues] == [
        ("V6.unknown_recipe", "changes.0.after.recipe_id", "V6.unknown_recipe"),
        ("V4.duplicate_change_id", "changes.1.change_id", "V4.duplicate_change_id"),
        ("V9.strength_move_flag", "changes.1", "V9.strength_move_flag"),
        (
            "V5.out_of_scope",
            "changes.2",
            "beyond the block review date; accept the block change or reject this session",
        ),
        ("V4.unknown_session", "changes.3.session_uid", "V4.unknown_session"),
        ("V4.session_in_multiple_changes", "changes.4.session_uid", "V4.session_in_multiple_changes"),
        ("V4.unknown_preserved", "preserved.0", "V4.unknown_preserved"),
        ("V11.unknown_kb_id", "evidence_ids.0", "V11.unknown_kb_id"),
    ]


def test_exception_rule_issue_order_is_pinned() -> None:
    doc = valid_doc("exception_review")
    doc["exception"] = {
        "finding_ids": [str(U(500))],
        "category": "accumulated_fatigue",
        "severity": "caution",
        "confidence": "moderate",
        "triggering_evidence": "Fatigue",
        "ladder_level": "current_session",
        "patch_window": {"start": "2026-11-16", "end": "2026-11-21"},
        "unchanged": [{"session_uid": str(U(3)), "reason": "Touched"}],
        "reassess_on": "2026-11-30",
        "monitor": ["Fatigue"],
        "return_criteria": ["Fatigue below 5"],
        "escalate_criteria": ["Fatigue rising"],
    }
    doc["patch_resolutions"] = [{"patch_id": str(U(600)), "status": "resolved", "note": "Done"}]
    EXPECTED = (
        "invalid",
        [
            ("V17.window_too_long", "exception.patch_window"),
            ("V17.reassess_out_of_range", "exception.reassess_on"),
            ("V19.unchanged_invalid", "exception.unchanged.0"),
            ("V20.finding_unknown", "exception.finding_ids.0"),
            ("V21.patch_unknown", "patch_resolutions.0.patch_id"),
        ],
    )
    assert outcome(doc, context("exception_review")) == EXPECTED
    assert [
        (issue.code, issue.path, issue.message) for issue in validate_document(doc, context("exception_review")).issues
    ] == [
        ("V17.window_too_long", "exception.patch_window", "V17.window_too_long"),
        ("V17.reassess_out_of_range", "exception.reassess_on", "V17.reassess_out_of_range"),
        ("V19.unchanged_invalid", "exception.unchanged.0", "V19.unchanged_invalid"),
        ("V20.finding_unknown", "exception.finding_ids.0", "V20.finding_unknown"),
        ("V21.patch_unknown", "patch_resolutions.0.patch_id", "V21.patch_unknown"),
    ]


def freshness(ctx: ValidationContext | None = None, *, calendar: int = 7, block: uuid.UUID | None = U(101)):
    ctx = ctx or context()
    assert ctx.snapshot is not None
    return proposal_freshness(ctx.snapshot, ctx, base_calendar_version=calendar, base_block_version_id=block)


def test_freshness_current_proposal_has_no_reasons() -> None:
    assert freshness() == []


def test_freshness_expiry_wins_over_stale_base() -> None:
    ctx = context()
    old = replace(ctx, snapshot=replace(ctx.snapshot, generated_at=NOW - timedelta(hours=25)))
    assert freshness(old, calendar=6) == ["snapshot_expired"]


@pytest.mark.parametrize("change", [{"as_of": TODAY - timedelta(days=1)}, {"generated_at": NOW + timedelta(minutes=1)}])
def test_freshness_other_day_or_future_snapshot_is_expired(change: dict) -> None:
    ctx = context()
    assert freshness(replace(ctx, snapshot=replace(ctx.snapshot, **change))) == ["snapshot_expired"]


def test_freshness_reports_both_stale_bases_in_order() -> None:
    assert freshness(calendar=6, block=U(999)) == ["stale_base_calendar", "stale_base_block"]
    assert freshness(block=None) == ["stale_base_block"]


def test_freshness_no_active_block_matches_a_missing_base_block() -> None:
    assert freshness(context(block=False), block=None) == []


@pytest.mark.parametrize("change", [{"current_source_fingerprint": "other"}, {"current_kb_digest": "1" * 64}])
def test_freshness_changed_sources_are_stale(change: dict) -> None:
    assert freshness(replace(context(), **change)) == ["stale_sources"]
