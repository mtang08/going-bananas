"""Snapshot topics."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.domain.session_class import LONG_RECIPE, QUALITY_RECIPES
from app.services.knowledge import CONDITIONAL_TOPICS
from app.services.proposals.schema import is_quality_slot, scope
from app.services.snapshot.common import (
    BLOCK,
    CALIB,
    DAILY,
    EXCEPTION,
    POST_EVENT,
    QUALITY_OP,
    RACE,
    ROLLING,
    SnapshotInputs,
    day_between,
    parse_day,
    parse_instant,
)
from app.services.snapshot.payload import active_review_date, section_window


def _scope_sessions(inputs: SnapshotInputs, operation: str) -> list[dict]:
    start, end = scope(operation, inputs.as_of, active_review_date(inputs))
    return [s for s in inputs.sessions if day_between(s.get("local_date"), start, end)]


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
    slots = {str(s["slot_id"]): s for s in inputs.strength_slots if s.get("active", True)}
    symptom_start, symptom_end = section_window(
        operation if operation not in {CALIB, RACE, POST_EVENT} else DAILY, "symptoms", inputs
    )
    recent_checkins = [c for c in inputs.checkins if day_between(c.get("local_date"), symptom_start, symptom_end)]
    ptt = any(c.get("symptoms") for c in recent_checkins) or any(
        p.get("kind") == "delayed_symptom"
        and p.get("status") == "answered"
        and day_between(parse_instant(p["opens_at"]).date(), symptom_start, symptom_end)
        for p in inputs.prompts
    )
    rec_start = inputs.as_of - timedelta(
        days=(
            3
            if operation in {DAILY, EXCEPTION}
            else 14
            if operation in {CALIB, RACE, POST_EVENT, ROLLING, QUALITY_OP}
            else 28
        )
        - 1
    )
    recovery = any(
        m.get("metric_id") == "recovery_multisignal_summary"
        and m.get("subject_type") == "night"
        and str(m.get("subject_key", "")).startswith("night:")
        and day_between(str(m["subject_key"]).split(":", 1)[1], rec_start, inputs.as_of)
        and isinstance(m.get("value"), dict)
        and (m["value"].get("flags") or m["value"].get("discordance") is True)
        for m in inputs.metric_results
    ) or any(c.get("illness") in {"possible", "present"} for c in recent_checkins)
    hybrid = any(
        s.get("kind") == "strength"
        and (slots.get(str(s.get("strength_slot_id"))) or {}).get("lower_body_cost") in {"moderate", "high"}
        and any(abs((parse_day(s["local_date"]) - parse_day(r["local_date"])).days) <= 2 for r in runs)
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
    if operation == BLOCK:
        # A new block can introduce easy, long, threshold, and benchmark runs even on an empty calendar.
        ids.update({"REC001", LONG_RECIPE, "REC003", "REC009"})
        if inputs.active_block:
            ids.update(inputs.active_block.get("eligible_recipe_ids", []))
    if operation in {ROLLING, QUALITY_OP} and any(
        is_quality_slot(s.get("kind", ""), s.get("recipe_id"), bool(s.get("placeholder"))) for s in sessions
    ):
        ids.update(inputs.active_block.get("eligible_recipe_ids", []) if inputs.active_block else QUALITY_RECIPES)
    return sorted(ids)
