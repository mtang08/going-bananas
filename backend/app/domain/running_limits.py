"""Evaluate structured run prescriptions against confirmed and temporary limits."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.domain.athlete_facts import RunningRestriction
from app.domain.calendar_structure import StructureError, expand_structure
from app.domain.running_interruption import RunningInterruption
from app.domain.session_class import QUALITY_RECIPES, RECIPE_CLASS, expected_rpe

_DOSE_FIELDS = ("planned_duration_s", "planned_distance_m")
_PRESCRIPTION_FIELDS = (
    "local_date",
    "kind",
    "recipe_id",
    "custom",
    "placeholder",
    "intent",
    "structure",
    "brief",
    *_DOSE_FIELDS,
)


def _steps(row: dict[str, Any]) -> list[dict[str, Any]]:
    if row.get("structure") is None:
        return []
    try:
        return expand_structure(row["structure"])
    except StructureError:
        return []  # The calendar and proposal schemas reject invalid new structures.


def _structured_dose(steps: list[dict[str, Any]], unit: str) -> tuple[float, bool]:
    """Sum exact and speed-bounded steps, tracking whether any unit remains unaccounted for."""
    total = 0.0
    complete = bool(steps)
    for step in steps:
        amount = step["duration_value"]
        if step["duration_type"] == unit:
            total += amount
            continue
        target = step.get("target") or {}
        if target.get("modality") == "speed":
            if unit == "distance":
                total += amount * target["high"]
                continue
            if target["low"] > 0:
                total += amount / target["low"]
                continue
            if target["high"] > 0:
                # Even the fastest prescribed pace imposes this much duration.
                total += amount / target["high"]
        complete = False
    return total, complete


def _prescribed_effort(row: dict[str, Any]) -> tuple[int, int] | None:
    brief = row.get("brief")
    effort = brief.get("effort") if isinstance(brief, dict) else None
    if not isinstance(effort, dict):
        return None
    low, high = effort.get("rpe_low"), effort.get("rpe_high")
    return (low, high) if type(low) is int and type(high) is int else None


def _recipe_effort(recipe_id: Any) -> tuple[float, float] | None:
    if not isinstance(recipe_id, str):
        return None
    return expected_rpe(recipe_id, RECIPE_CLASS.get(recipe_id, "unknown"))


def _raises_prescribed_effort(after: dict[str, Any], before: dict[str, Any]) -> bool:
    target = _prescribed_effort(after)
    if target is None:
        return False
    previous = _prescribed_effort(before)
    if previous is not None:
        return target[0] > previous[0] or target[1] > previous[1]
    # With recipe-only guidance, the prescribed ceiling is the known comparison.
    guide = _recipe_effort(before.get("recipe_id"))
    return guide is not None and target[1] > guide[1]


def restriction_conflict(
    limit: RunningRestriction | None, after: dict[str, Any], before: dict[str, Any] | None = None
) -> str | None:
    day = after.get("local_date")
    if (
        limit is None
        or after.get("kind") != "run"
        or day is None
        or not limit.applies_on(day)
        or (before is not None and all(after.get(key) == before.get(key) for key in _PRESCRIPTION_FIELDS))
    ):
        return None
    prefix = f"Running restriction on {day}"
    if limit.ends_on is None and limit.review_on is not None and day >= limit.review_on:
        prefix += f" (review date {limit.review_on}, with no confirmed end)"
    if limit.pause_running:
        return f"{prefix} pauses running. Remove the run or move it outside the restricted dates."
    steps = _steps(after)
    recipe_id = after.get("recipe_id")
    recipe = RECIPE_CLASS.get(recipe_id) if isinstance(recipe_id, str) else None
    if limit.no_quality and (
        recipe not in {"easy", "long"}
        or after.get("placeholder")
        or after.get("custom")
        or any(step["type"] == "recovery" for step in steps)
        or sum(step["type"] == "work" for step in steps) > 1
    ):
        return f"{prefix} excludes quality sessions. Use an easy or long run recipe with continuous work."
    target = _prescribed_effort(after)
    guide = _recipe_effort(recipe_id)
    if limit.no_quality and target is not None and guide is not None and target[1] > guide[1]:
        return (
            f"{prefix} excludes quality sessions. "
            f"Keep the target within the {recipe} recipe range up to RPE {guide[1]:g}."
        )

    for unit, field, cap, suffix in (
        ("distance", "planned_distance_m", limit.max_distance_m, "m"),
        ("time", "planned_duration_s", limit.max_duration_s, "s"),
    ):
        if cap is None:
            continue
        declared = after.get(field)
        measured, complete = _structured_dose(steps, unit)
        if max(declared or 0, measured) > cap:
            return f"{prefix} caps each run at {cap} {suffix}. Reduce the planned total and workout steps."
        if declared is None and not complete:
            label = "distance" if unit == "distance" else "duration"
            return f"{prefix} caps each run at {cap} {suffix}. Enter a planned {label} within the limit."
    return None


def _step_no_harder(after: dict[str, Any], before: dict[str, Any]) -> bool:
    if (
        after["type"] != before["type"]
        or after["duration_type"] != before["duration_type"]
        or after["duration_value"] > before["duration_value"]
    ):
        return False
    new_target, old_target = after.get("target"), before.get("target")
    if new_target == old_target:
        return True
    return bool(
        new_target
        and old_target
        and new_target["modality"] == old_target["modality"]
        and new_target["modality"] in {"speed", "hr"}
        and new_target["low"] <= old_target["low"]
        and new_target["high"] <= old_target["high"]
        and new_target.get("effort_cue") == old_target.get("effort_cue")
    )


def increases_run_dose(after: dict[str, Any], before: dict[str, Any]) -> bool:
    if _raises_prescribed_effort(after, before):
        return True
    if any((after.get(field) or 0) > (before.get(field) or 0) for field in _DOSE_FIELDS):
        return True
    recipe, previous_recipe = after.get("recipe_id"), before.get("recipe_id")
    if recipe != previous_recipe:
        if recipe in QUALITY_RECIPES or (previous_recipe == "REC001" and recipe == "REC007"):
            return True
        guide, previous_guide = _recipe_effort(recipe), _recipe_effort(previous_recipe)
        if (
            guide is not None
            and previous_guide is not None
            and (guide[0] > previous_guide[0] or guide[1] > previous_guide[1])
        ):
            return True
    if after.get("structure") == before.get("structure"):
        return False
    previous = iter(_steps(before))
    return any(not any(_step_no_harder(step, old) for old in previous) for step in _steps(after))


def reduces_existing_dose(after: dict[str, Any], before: dict[str, Any]) -> bool:
    if any(
        after.get(field) != before.get(field)
        for field in ("local_date", "kind", "recipe_id", "placeholder", "custom", "intent")
    ):
        return False
    if any(before.get(field) is not None and after.get(field) is None for field in _DOSE_FIELDS):
        return False
    if increases_run_dose(after, before):
        return False
    return any(after.get(field) != before.get(field) for field in (*_DOSE_FIELDS, "structure"))


def interruption_conflict(
    interruption: RunningInterruption | None, after: dict[str, Any], before: dict[str, Any] | None, today: date
) -> str | None:
    """Do not add, move, or increase a future run during a confirmed interruption."""
    day = after.get("local_date")
    if (
        interruption is None
        or after.get("kind") != "run"
        or day is None
        or day < today
        or not interruption.unavailable_on(day)
    ):
        return None
    if (
        before is None
        or before.get("kind") != "run"
        or before.get("local_date") != day
        or increases_run_dose(after, before)
    ):
        return f"Running is unavailable on {day}. Remove the run or move it outside the confirmed interruption."
    return None
