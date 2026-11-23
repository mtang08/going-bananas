"""Coach proposal validation."""

from __future__ import annotations

import re
import uuid
from collections import Counter
from datetime import date, timedelta
from typing import Any, Literal

from app.domain.calendar_structure import StructureError, expand_structure
from app.domain.cycle import opportunity
from app.domain.session_class import LONG_RECIPE, QUALITY_RECIPES
from app.services.block_benchmark import ACTIVE_STATUSES, BENCHMARK_MAX_AGE_DAYS, CREDIBLE_OUTCOMES
from app.services.exceptions.vocab import NON_TERMINAL_FINDING
from app.services.proposals.schema import (
    ANCHOR_CONFIDENCE,
    ANCHOR_KINDS,
    ANCHOR_UNIT,
    ANCHOR_UNITS,
    BLOCK_OPS,
    BLOCK_REVIEW_LEAD_DAYS,
    HORIZON_MIN_DAYS,
    HORIZON_OPS,
    NO_STRENGTH_EDIT_OPS,
    OFF_CYCLE_OPS,
    PROTOCOLS,
    RECIPE_IDS,
    RESOLUTION_OPS,
    BlockVersionFields,
    Change,
    HeadSession,
    ProposalDoc,
    RepeatBlock,
    SnapshotRef,
    StructureStep,
    Target,
    ValidationContext,
    ValidationIssue,
    ValidationResult,
    anchor_key,
    anchors_allowed,
    is_quality_slot,
    parse_document,
    safety_active,
    scope,
)

ID_TOKEN = re.compile(
    r"\b(?:E-[A-Z]{2,8}-\d{2}|P\d{3}|REC\d{3}|S\d{3})\b"
    r"|\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
PROSE_KEYS = frozenset(
    {
        "headline",
        "text",
        "when",
        "then",
        "check",
        "coach_note",
        "uncertainty",
        "reason",
        "intent",
        "feel",
        "focus",
        "why",
        "effort_cue",
        "objective",
        "maintained_qualities",
        "non_goals",
        "early_review_triggers",
        "label",
        "progress_when",
        "protocol",
        "progress_if",
        "consolidate_if",
        "emphasis",
        "conditions",
        "triggering_evidence",
        "relevant_context",
        "monitor",
        "return_criteria",
        "escalate_criteria",
        "pacing",
        "effort_and_limiter",
        "symptoms",
        "recovery_observation",
        "training_implication",
        "compared_with",
        "note",
    }
)
NEXT_CHECK_MAX_DAYS = 14
BRIEF_WINDOW_DAYS = 13
BRIEF_OPTIONAL_FIELDS = frozenset({"slot", "locked", "brief"})


def _issue(code: str, path: str, message: str | None = None) -> ValidationIssue:
    return ValidationIssue(code, path, message or code)


def _resulting(doc: ProposalDoc, ctx: ValidationContext) -> dict[str, dict]:
    state = {str(uid): dict(vars(row)) for uid, row in ctx.head_sessions.items()}
    for change in doc.changes:
        if change.is_unplanned_strength_omission:
            continue
        uid = str(change.session_uid) if change.session_uid else f"new:{change.change_id}"
        if change.op == "delete":
            state.pop(uid, None)
        elif change.op == "add" and change.after:
            state[uid] = {
                "session_uid": None,
                "local_date": change.after.local_date,
                "slot": change.after.slot or 0,
                "kind": change.after.kind,
                "recipe_id": change.after.recipe_id,
                "custom": change.after.custom or False,
                "placeholder": change.after.placeholder or False,
                "intent": change.after.intent,
                "planned_duration_s": change.after.planned_duration_s,
                "structure": change.after.structure,
                "strength_slot_id": change.after.strength_slot_id,
            }
        elif uid in state and change.after:
            state[uid].update(change.after.model_dump(include=change.after.model_fields_set))
    return state


def _id_in_text(doc: ProposalDoc) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def walk(value: Any, path: str, prose: bool) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else key, key in PROSE_KEYS)
        elif isinstance(value, list):
            for j, item in enumerate(value):
                walk(item, f"{path}.{j}", prose)
        elif prose and isinstance(value, str) and ID_TOKEN.search(value):
            issues.append(
                _issue("V24.id_in_text", path, "Cite IDs in evidence_ids, policy_ids, or recipe_ids, not in text")
            )

    walk(doc.model_dump(mode="json"), "", False)
    return issues


def _unsourced_research_path(doc: ProposalDoc) -> str | None:
    if doc.evidence_ids or doc.policy_ids:
        return None
    groups = [("why", doc.why)]
    if doc.block_change is not None:
        groups.append(("block_change.version_fields.why", doc.block_change.version_fields.why))
    for prefix, items in groups:
        for j, item in enumerate(items):
            if item.kind == "research":
                return f"{prefix}.{j}"
    return None


def _text_rules(doc: ProposalDoc, ctx: ValidationContext) -> list[ValidationIssue]:
    issues = _id_in_text(doc)
    if doc.confidence.decision != "high" and not doc.uncertainty:
        issues.append(_issue("V24.uncertainty_required", "uncertainty", "Name the main unknowns"))
    if doc.operation != "exception_review" and not doc.change_triggers:
        issues.append(
            _issue("V24.triggers_required", "change_triggers", "Name the feedback that would change this decision")
        )
    last = ctx.today + timedelta(days=NEXT_CHECK_MAX_DAYS)
    if not ctx.today <= doc.next_check.on <= last:
        issues.append(
            _issue(
                "V24.next_check_date",
                "next_check.on",
                f"Next check must fall between {ctx.today.isoformat()} and {last.isoformat()}",
            )
        )
    research = _unsourced_research_path(doc)
    if research is not None:
        issues.append(_issue("V24.research_unsourced", research, "A research reason needs evidence_ids or policy_ids"))
    return issues


def _brief_missing(ctx: ValidationContext, change: Change, fields: set[str], result: dict[str, Any]) -> bool:
    day = result.get("local_date")
    reworked = change.op == "add" or (change.op == "modify" and bool(fields - BRIEF_OPTIONAL_FIELDS))
    return (
        reworked
        and result.get("kind") == "run"
        and day is not None
        and ctx.today <= day <= ctx.today + timedelta(days=BRIEF_WINDOW_DAYS)
        and (change.after is None or change.after.brief is None)
    )


def _exception_block_rules(doc: ProposalDoc, ctx: ValidationContext) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    exc = doc.exception
    last = ctx.today + timedelta(days=6)
    if doc.operation == "exception_review" and exc is None:
        issues.append(_issue("V16.exception_required", "exception"))
    if doc.operation != "exception_review" and exc is not None:
        issues.append(_issue("V16.exception_forbidden", "exception"))
    if doc.operation == "exception_review" and exc is not None:
        window = exc.patch_window
        length = (window.end - window.start).days + 1
        if not ctx.today <= window.start <= window.end <= last:
            issues.append(_issue("V17.window_out_of_scope", "exception.patch_window"))
        if length > (3 if exc.severity in {"observe", "caution"} else 7):
            issues.append(_issue("V17.window_too_long", "exception.patch_window"))
        for i, change in enumerate(doc.changes):
            head = ctx.head_sessions.get(change.session_uid) if change.session_uid else None
            days = [head.local_date] if head else []
            if change.after is not None and change.after.local_date is not None:
                days.append(change.after.local_date)
            if any(not window.start <= day <= window.end for day in days):
                issues.append(_issue("V17.change_outside_window", f"changes.{i}"))
        if not ctx.today <= exc.reassess_on <= ctx.today + timedelta(days=7):
            issues.append(_issue("V17.reassess_out_of_range", "exception.reassess_on"))
        count = len(doc.changes)
        single = count == 1 or (count == 0 and exc.severity == "observe")
        ladder_ok = {
            "current_session": single,
            "next_session": single,
            "next_days": length <= 3,
            "committed_window": exc.severity in {"hold", "escalate"},
            "block": exc.severity == "escalate" and doc.escalation == "review_training_block",
        }[exc.ladder_level]
        if not ladder_ok:
            issues.append(_issue("V18.ladder_mismatch", "exception.ladder_level"))
        touched = {change.session_uid for change in doc.changes if change.session_uid}
        seen: set[uuid.UUID] = set()
        for j, item in enumerate(exc.unchanged):
            row = ctx.head_sessions.get(item.session_uid)
            if (
                row is None
                or not ctx.today <= row.local_date <= last
                or item.session_uid in touched
                or item.session_uid in seen
            ):
                issues.append(_issue("V19.unchanged_invalid", f"exception.unchanged.{j}"))
            seen.add(item.session_uid)
        for j, finding_id in enumerate(exc.finding_ids):
            status = ctx.findings.get(finding_id)
            if status is None:
                issues.append(_issue("V20.finding_unknown", f"exception.finding_ids.{j}"))
            elif status not in NON_TERMINAL_FINDING:
                issues.append(_issue("V20.finding_closed", f"exception.finding_ids.{j}"))
    return issues


def _event_review_rules(doc: ProposalDoc, ctx: ValidationContext) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    review, bench = doc.event_review, ctx.benchmark
    if review is not None and review.event_id is None and review.activity_id is None:
        issues.append(_issue("V20.event_target_invalid", "event_review"))
    if review is not None and review.outcome is not None and doc.operation != "review_training_block":
        issues.append(_issue("V20.event_forbidden", "event_review.outcome"))
    if doc.operation == "post_event_review":
        if review is None:
            issues.append(_issue("V20.event_required", "event_review"))
        elif review.event_id is None or ctx.events.get(review.event_id, ("cancelled", None))[0] == "cancelled":
            issues.append(_issue("V20.event_unknown", "event_review.event_id"))
    elif doc.operation == "review_training_block":
        if "BLOCK_BENCHMARK_COMPLETED" in ctx.open_rule_codes and (review is None or review.outcome is None):
            issues.append(_issue("V20.event_required", "event_review"))
        if review is not None and (
            bench is None
            or bench.status != "completed"
            or (review.activity_id is not None and review.activity_id != bench.activity_id)
            or (review.event_id is not None and review.event_id != bench.event_id)
        ):
            issues.append(_issue("V20.event_target_invalid", "event_review"))
    elif review is not None:
        issues.append(_issue("V20.event_forbidden", "event_review"))
    return issues


def _last_credible_benchmark(doc: ProposalDoc, ctx: ValidationContext) -> date | None:
    dates = [ctx.last_benchmark_date]
    bench, review = ctx.benchmark, doc.event_review
    if bench is not None and bench.status == "completed" and review is not None and review.outcome in CREDIBLE_OUTCOMES:
        dates.append(bench.local_date)
    return max((d for d in dates if d is not None), default=None)


def _benchmark_required_message(last: date | None) -> str:
    if last is None:
        return "no credible benchmark result yet; set a benchmark"
    skip_by = last + timedelta(days=BENCHMARK_MAX_AGE_DAYS + BLOCK_REVIEW_LEAD_DAYS - 1)
    return (
        f"Last credible benchmark {last.isoformat()}. Set a benchmark or choose a review date "
        f"on or before {skip_by.isoformat()}."
    )


def _benchmark_rules(doc: ProposalDoc, ctx: ValidationContext) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    fields = doc.block_change.version_fields if doc.block_change else None
    if fields is not None and fields.status == "active":
        planned = fields.benchmark
        latest = fields.review_date - timedelta(days=BLOCK_REVIEW_LEAD_DAYS)
        if planned is None:
            last = _last_credible_benchmark(doc, ctx)
            if last is None or (latest - last).days >= BENCHMARK_MAX_AGE_DAYS:
                issues.append(
                    _issue(
                        "V22.benchmark_required",
                        "block_change.version_fields.benchmark",
                        _benchmark_required_message(last),
                    )
                )
            elif not fields.indicators:
                issues.append(_issue("V22.indicators_required", "block_change.version_fields.indicators"))
        else:
            earliest = fields.review_date - timedelta(days=HORIZON_MIN_DAYS)
            if not earliest <= planned.planned_date <= latest:
                issues.append(_issue("V22.benchmark_date", "block_change.version_fields.benchmark.planned_date"))
            event = ctx.events.get(planned.event_id) if planned.event_id else None
            bad_event = planned.kind == "event" and (
                event is None or event[0] == "cancelled" or event[1] != planned.planned_date
            )
            bad_trial = planned.kind == "time_trial" and (
                planned.event_id is not None or "REC009" not in fields.eligible_recipe_ids
            )
            if bad_event or bad_trial:
                issues.append(_issue("V22.benchmark_event", "block_change.version_fields.benchmark"))
    return issues


def _target_event_rules(doc: ProposalDoc, ctx: ValidationContext) -> list[ValidationIssue]:
    fields = doc.block_change.version_fields if doc.block_change else None
    if fields is None or doc.operation not in BLOCK_OPS or fields.status not in ACTIVE_STATUSES:
        return []
    path = "block_change.version_fields.target_event_id"
    issues: list[ValidationIssue] = []
    if fields.target_event_id is None:
        if any(ref.rank is not None for ref in ctx.events.values()):
            issues.append(_issue("V23.target_event_required", path))
        return issues + _build_outline_rules(fields, None)
    ref = ctx.events.get(fields.target_event_id)
    if ref is None or ref.rank is None:
        return [_issue("V23.target_event_invalid", path)]
    if ref.rank != 1:
        issues.append(_issue("V23.target_event_not_top", path))
    if ref.day < fields.start_date:
        issues.append(_issue("V23.target_event_date", path))
    return issues + _build_outline_rules(fields, ref.day)


def _build_outline_rules(fields: BlockVersionFields, race_day: date | None) -> list[ValidationIssue]:
    weeks = [step.weeks for step in fields.build_outline]
    if race_day is None or race_day <= fields.review_date:
        ok = not weeks
    else:
        lower = fields.review_date + timedelta(days=7 * (sum(weeks) - (weeks[-1] if weeks else 0)))
        upper = fields.review_date + timedelta(days=7 * sum(weeks))
        ok = bool(weeks) and lower < race_day <= upper
    return [] if ok else [_issue("V23.build_outline_span", "block_change.version_fields.build_outline")]


def _patch_resolution_rules(doc: ProposalDoc, ctx: ValidationContext) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if doc.patch_resolutions and doc.operation not in RESOLUTION_OPS:
        issues.append(_issue("V21.resolution_forbidden", "patch_resolutions"))
    resolved: set[uuid.UUID] = set()
    for j, resolution in enumerate(doc.patch_resolutions):
        status = ctx.patches.get(resolution.patch_id)
        if status is None:
            issues.append(_issue("V21.patch_unknown", f"patch_resolutions.{j}.patch_id"))
        elif status not in {"open", "escalated"}:
            issues.append(_issue("V21.patch_closed", f"patch_resolutions.{j}.patch_id"))
        if resolution.patch_id in resolved:
            issues.append(_issue("V21.patch_duplicate", f"patch_resolutions.{j}.patch_id"))
        resolved.add(resolution.patch_id)
    return issues


def _exception_rules(doc: ProposalDoc, ctx: ValidationContext) -> list[ValidationIssue]:
    issues = _exception_block_rules(doc, ctx)
    issues += _event_review_rules(doc, ctx)
    issues += _benchmark_rules(doc, ctx)
    issues += _target_event_rules(doc, ctx)
    issues += _patch_resolution_rules(doc, ctx)
    return issues


def _recipe_issue(
    doc: ProposalDoc, ctx: ValidationContext, *, change: Change, result: dict[str, Any], fields: set[str], path: str
) -> ValidationIssue | None:
    check_recipe = (change.op == "add" and result.get("kind") == "run") or (
        change.op == "modify"
        and result.get("kind") == "run"
        and bool(fields & {"kind", "recipe_id", "custom", "structure"})
    )
    if check_recipe:
        recipe = result.get("recipe_id")
        if not recipe and not (result.get("custom") and result.get("structure")):
            return _issue("V6.recipe_required", f"{path}.after")
        elif recipe:
            if recipe not in RECIPE_IDS:
                return _issue("V6.unknown_recipe", f"{path}.after.recipe_id")
            else:
                eligible = (
                    doc.block_change.version_fields.eligible_recipe_ids
                    if doc.block_change
                    else (ctx.active_block.eligible_recipe_ids if ctx.active_block else ())
                )
                if recipe not in eligible:
                    return _issue("V6.recipe_not_eligible", f"{path}.after.recipe_id")
    return None


def _quality_pileup(
    change: Change,
    head: HeadSession | None,
    result_date: date | None,
    *,
    state: dict[str, dict],
    before: dict[str, dict],
) -> bool:
    if (
        change.op == "move"
        and head
        and is_quality_slot(head.kind, head.recipe_id, head.placeholder)
        and result_date
        and (result_date - timedelta(days=result_date.weekday()))
        != (head.local_date - timedelta(days=head.local_date.weekday()))
    ):
        week = result_date - timedelta(days=result_date.weekday())

        def count(rows: dict[str, dict]) -> int:
            return sum(
                is_quality_slot(row["kind"], row.get("recipe_id"), row.get("placeholder", False))
                and week <= row["local_date"] <= week + timedelta(days=6)
                for row in rows.values()
            )

        return count(state) > count(before)
    return False


def _safety_violation(
    ctx: ValidationContext,
    change: Change,
    head: HeadSession | None,
    fields: set[str],
    result: dict[str, Any],
    result_date: date | None,
) -> bool:
    if (
        safety_active(ctx.current_safety_guard)
        and result_date
        and ctx.today <= result_date <= ctx.today + timedelta(days=3)
    ):
        unsafe = (
            (change.op == "add" and result.get("kind") == "run")
            or (
                change.op == "move"
                and head is not None
                and head.kind == "run"
                and not ctx.today <= head.local_date <= ctx.today + timedelta(days=3)
            )
            or (change.op == "modify" and head is not None and head.kind != "run" and result.get("kind") == "run")
            or (
                change.op == "modify"
                and "planned_duration_s" in fields
                and head is not None
                and (
                    head.planned_duration_s is None or (result.get("planned_duration_s") or 0) > head.planned_duration_s
                )
            )
            or (change.op in {"add", "modify"} and "recipe_id" in fields and result.get("recipe_id") in QUALITY_RECIPES)
        )
        return bool(unsafe)
    return False


def _change_rules(
    doc: ProposalDoc, ctx: ValidationContext, *, start: date, end: date, state: dict[str, dict]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    before = {str(uid): dict(vars(row)) for uid, row in ctx.head_sessions.items()}
    seen_ids: set[str] = set()
    seen_uids: set[uuid.UUID] = set()
    for i, change in enumerate(doc.changes):
        issues += _change_issues(
            doc,
            ctx,
            i,
            change,
            start=start,
            end=end,
            state=state,
            before=before,
            seen_ids=seen_ids,
            seen_uids=seen_uids,
        )
    return issues


def _change_issues(
    doc: ProposalDoc,
    ctx: ValidationContext,
    i: int,
    change: Change,
    *,
    start: date,
    end: date,
    state: dict[str, dict],
    before: dict[str, dict],
    seen_ids: set[str],
    seen_uids: set[uuid.UUID],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    path = f"changes.{i}"
    head = ctx.head_sessions.get(change.session_uid) if change.session_uid else None
    after = change.after
    fields = after.model_fields_set if after else set()
    if after is not None and after.structure is not None:
        try:
            expand_structure([item.model_dump() for item in after.structure])
        except StructureError:
            issues.append(_issue("V6.invalid_structure", f"{path}.after.structure", "Invalid workout steps or targets"))
    result = (
        {**vars(head), **after.model_dump(include=fields)}
        if head and after
        else (after.model_dump() if after else vars(head) if head else {})
    )
    if change.change_id in seen_ids:
        issues.append(_issue("V4.duplicate_change_id", f"{path}.change_id"))
    seen_ids.add(change.change_id)
    if change.session_uid and not head:
        issues.append(_issue("V4.unknown_session", f"{path}.session_uid"))
    if change.session_uid in seen_uids:
        issues.append(_issue("V4.session_in_multiple_changes", f"{path}.session_uid"))
    if change.session_uid:
        seen_uids.add(change.session_uid)
    dates = [after.local_date] if change.op == "add" and after else [head.local_date] if head else []
    if change.op == "move" and after:
        if after.local_date is not None:
            dates.append(after.local_date)
    if any(d is not None and not (start <= d <= end) for d in dates):
        beyond = doc.operation in HORIZON_OPS and any(d is not None and d > end for d in dates)
        issues.append(_issue("V5.out_of_scope", path, _V5_BEYOND_REVIEW if beyond else None))
    recipe_issue = _recipe_issue(doc, ctx, change=change, result=result, fields=fields, path=path)
    if recipe_issue is not None:
        issues.append(recipe_issue)
    produces_run = (
        (change.op == "add" and result.get("kind") == "run")
        or (change.op == "move" and head is not None and head.kind == "run")
        or (change.op == "modify" and head is not None and head.kind != "run" and result.get("kind") == "run")
    )
    result_date = result.get("local_date")
    if (
        produces_run
        and result_date
        and (ctx.cycle_anchor is None or opportunity(result_date, ctx.cycle_anchor) is None)
        and not ("off_cycle_run" in change.material_flags and doc.operation in OFF_CYCLE_OPS)
    ):
        issues.append(_issue("V8.off_cycle", path))
    if head and head.kind == "strength" and change.op == "move":
        if doc.operation in NO_STRENGTH_EDIT_OPS:
            issues.append(_issue("V9.daily_strength_move", path))
        elif "strength_move" not in change.material_flags:
            issues.append(_issue("V9.strength_move_flag", path))
    if doc.operation in NO_STRENGTH_EDIT_OPS and (
        (change.op in {"add", "delete"} and result.get("kind") == "strength")
        or (change.op == "modify" and head and (head.kind == "strength") != (result.get("kind") == "strength"))
    ):
        issues.append(_issue("V9.daily_strength_change", path))
    if _quality_pileup(change, head, result_date, state=state, before=before):
        issues.append(_issue("V10.quality_pileup", path))
    if _safety_violation(ctx, change, head, fields, result, result_date):
        issues.append(_issue("V12.safety_guard", path))
    if doc.operation == "select_quality_session" and (
        change.op != "modify" or not head or not is_quality_slot(head.kind, head.recipe_id, head.placeholder)
    ):
        issues.append(_issue("V15.not_quality_slot", path))
    if doc.operation == "recalibrate_intensity" and (
        change.op != "modify" or not fields <= {"intent", "structure", "brief"}
    ):
        issues.append(_issue("V15.recalibrate_change_not_allowed", path))
    if _brief_missing(ctx, change, fields, result):
        issues.append(
            _issue("V25.brief_required", f"{path}.after.brief", "A run added or reworked within 14 days needs a brief")
        )
    return issues


def _preserved_rules(doc: ProposalDoc, ctx: ValidationContext) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for j, uid in enumerate(doc.preserved):
        if uid not in ctx.head_sessions:
            issues.append(_issue("V4.unknown_preserved", f"preserved.{j}"))
    return issues


def _strength_omission_target(
    change: Change, ctx: ValidationContext, head_strength_dates: set[date]
) -> tuple[date, uuid.UUID | None] | None:
    if change.op == "delete" and change.session_uid is not None:
        head = ctx.head_sessions.get(change.session_uid)
        if head and head.kind == "strength" and not head.locked:
            return head.local_date, head.strength_slot_id
        return None
    after = change.after
    if change.op != "add" or after is None or after.kind != "rest" or not (after.intent or "").strip():
        return None
    if not after.model_dump(exclude_none=True).keys() <= {"local_date", "kind", "intent"}:
        return None
    day = after.local_date
    if day is not None and day in ctx.confirmed_strength_dates and day not in head_strength_dates:
        return day, ctx.confirmed_strength_slot_ids.get(day)
    return None


def _slot_week(day: date, slot_id: uuid.UUID) -> tuple[date, uuid.UUID]:
    return day - timedelta(days=day.weekday()), slot_id


def _shared_strength_slots(ctx: ValidationContext) -> set[tuple[date, uuid.UUID]]:
    # A routine template can describe both weekly lifts. In that case the dates identify them.
    return {
        key
        for assignments in (ctx.confirmed_strength_slot_ids, ctx.accepted_strength_omission_slot_ids)
        for key, count in Counter(_slot_week(day, slot) for day, slot in assignments.items()).items()
        if count > 1
    }


def _strength_omission_rules(
    doc: ProposalDoc, ctx: ValidationContext, state: dict[str, dict]
) -> tuple[set[date], set[date], list[ValidationIssue]]:
    head_lifts = [
        (row.local_date, row.strength_slot_id) for row in ctx.head_sessions.values() if row.kind == "strength"
    ]
    result_lifts = [
        (row["local_date"], row.get("strength_slot_id")) for row in state.values() if row["kind"] == "strength"
    ]
    head_dates = {day for day, _ in head_lifts}
    result_dates = {day for day, _ in result_lifts}
    head_slots = {_slot_week(day, slot) for day, slot in head_lifts if day is not None and slot is not None}
    result_slots = {_slot_week(day, slot) for day, slot in result_lifts if day is not None and slot is not None}
    shared_slots = _shared_strength_slots(ctx)

    def unique_slot(day: date, slot: uuid.UUID | None) -> tuple[date, uuid.UUID] | None:
        key = _slot_week(day, slot) if slot else None
        return key if key not in shared_slots else None

    omissions: set[date] = set()
    omission_slots: set[tuple[date, uuid.UUID]] = set()
    for accepted_day in ctx.accepted_strength_omission_dates - head_dates - result_dates:
        slot = unique_slot(accepted_day, ctx.accepted_strength_omission_slot_ids.get(accepted_day))
        if slot in head_slots or slot in result_slots:
            continue
        omissions.add(accepted_day)
        if slot is not None:
            omission_slots.add(slot)

    marked_deletions: set[date] = set()
    issues: list[ValidationIssue] = []
    for i, change in enumerate(doc.changes):
        if "strength_omission" not in change.material_flags:
            continue
        path = f"changes.{i}"
        if change.op == "add" and doc.operation in NO_STRENGTH_EDIT_OPS:
            issues.append(_issue("V9.daily_strength_change", path))
        elif not change.reason.strip():
            issues.append(_issue("V9.strength_omission_invalid", f"{path}.reason", "Explain why the lift is omitted"))
        else:
            target = _strength_omission_target(change, ctx, head_dates)
            day, slot_id = target if target else (None, None)
            slot = unique_slot(day, slot_id) if day else None
            if (
                day is None
                or day in result_dates
                or slot in result_slots
                or (change.op == "add" and slot in head_slots)
                or change.material_flags != ["strength_omission"]
            ):
                issues.append(
                    _issue(
                        "V9.strength_omission_invalid",
                        path,
                        "Mark the deletion of a planned lift or identify an absent confirmed recurring lift",
                    )
                )
            elif day in omissions or slot in omission_slots:
                issues.append(_issue("V9.strength_omission_duplicate", path, "This date already has a lift omission"))
            else:
                omissions.add(day)
                if slot is not None:
                    omission_slots.add(slot)
                if change.op == "delete":
                    marked_deletions.add(day)
    return omissions, marked_deletions, issues


def _calendar_shape_rules(
    state: dict[str, dict],
    *,
    start: date,
    end: date,
    head_sessions: dict[uuid.UUID, HeadSession],
    omissions: set[date],
    marked_deletions: set[date],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for day_offset in range((end - start).days + 1):
        day = start + timedelta(days=day_offset)
        if sum(row["kind"] == "run" and row["local_date"] == day for row in state.values()) > 1:
            issues.append(_issue("V7.multiple_runs_per_day", "changes", day.isoformat()))
    week = start - timedelta(days=start.weekday())
    while week <= end:
        week_end = week + timedelta(days=6)
        rows = [
            row for row in state.values() if row["local_date"] is not None and week <= row["local_date"] <= week_end
        ]
        if week >= start and week_end <= end:
            head_count = sum(
                row.kind == "strength" and week <= row.local_date <= week_end for row in head_sessions.values()
            )
            strength_count = sum(row["kind"] == "strength" for row in rows)
            omission_count = sum(week <= day <= week_end for day in omissions)
            deleted_count = sum(week <= day <= week_end for day in marked_deletions)
            # Unplanned omissions cannot replace the loss of an already scheduled lift.
            if (rows or head_count or omission_count) and (
                strength_count + omission_count < 2 or strength_count + deleted_count < min(2, head_count)
            ):
                issues.append(_issue("V9.strength_count", "changes"))
        if sum(row["kind"] == "run" and row.get("recipe_id") == LONG_RECIPE for row in rows) > 1:
            issues.append(_issue("V10.multiple_long", "changes"))
        week += timedelta(days=7)
    return issues


def _kb_rules(doc: ProposalDoc, ctx: ValidationContext) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for field, allowed in [
        ("policy_ids", ctx.kb.policy_ids),
        ("recipe_ids", ctx.kb.recipe_ids),
        ("evidence_ids", ctx.kb.evidence_ids),
    ]:
        for j, value in enumerate(getattr(doc, field)):
            if value not in allowed:
                issues.append(_issue("V11.unknown_kb_id", f"{field}.{j}"))
    return issues


def _block_change_rules(doc: ProposalDoc, ctx: ValidationContext) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    block = doc.block_change
    if block:
        if doc.operation not in BLOCK_OPS:
            issues.append(_issue("V13.block_change_not_allowed", "block_change"))
        else:
            if (block.decision == "start" and ctx.active_block is not None) or (
                block.decision != "start" and ctx.active_block is None
            ):
                issues.append(_issue("V13.block_change_invalid", "block_change.decision"))
            if (block.decision == "start" and block.block_uid is not None) or (
                block.decision != "start"
                and ctx.active_block is not None
                and block.block_uid != ctx.active_block.block_uid
            ):
                issues.append(_issue("V13.block_change_invalid", "block_change.block_uid"))
            if block.version_fields.review_date <= block.version_fields.start_date:
                issues.append(_issue("V13.block_change_invalid", "block_change.version_fields.review_date"))
            for j, recipe in enumerate(block.version_fields.eligible_recipe_ids):
                if recipe not in RECIPE_IDS:
                    issues.append(
                        _issue("V13.block_change_invalid", f"block_change.version_fields.eligible_recipe_ids.{j}")
                    )
    return issues


def _anchor_rules(doc: ProposalDoc, ctx: ValidationContext) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if doc.anchor_changes and not anchors_allowed(doc):
        issues.append(_issue("V14.anchor_change_not_allowed", "anchor_changes"))
    anchor_keys: set[str] = set()
    for j, anchor in enumerate(doc.anchor_changes):
        path = f"anchor_changes.{j}"
        for field, invalid in [
            ("kind", anchor.kind not in ANCHOR_KINDS),
            ("unit", anchor.unit not in ANCHOR_UNITS or anchor.unit != ANCHOR_UNIT.get(anchor.kind)),
            ("protocol", anchor.protocol not in PROTOCOLS),
            ("confidence", anchor.confidence not in ANCHOR_CONFIDENCE),
            ("value_high", anchor.value_high is not None and anchor.value_low > anchor.value_high),
        ]:
            if invalid:
                issues.append(_issue("V14.anchor_invalid", f"{path}.{field}"))
        key = anchor_key(anchor, ctx.tz)
        if key in anchor_keys:
            issues.append(_issue("V14.anchor_invalid", f"{path}.kind"))
        anchor_keys.add(key)
    return issues


_V5_BEYOND_REVIEW = "beyond the block review date; accept the block change or reject this session"


def _horizon_review_date(doc: ProposalDoc, ctx: ValidationContext) -> date | None:
    if doc.block_change is not None:
        fields = doc.block_change.version_fields
        return fields.review_date if fields.status in ACTIVE_STATUSES else None
    return ctx.active_block.review_date if ctx.active_block else None


def _rules(doc: ProposalDoc, ctx: ValidationContext, *, exception_checks: bool = True) -> list[ValidationIssue]:
    start, end = scope(doc.operation, ctx.today, _horizon_review_date(doc, ctx))
    state = _resulting(doc, ctx)
    issues = _change_rules(doc, ctx, start=start, end=end, state=state)
    issues += _preserved_rules(doc, ctx)
    omissions, marked_deletions, omission_issues = _strength_omission_rules(doc, ctx, state)
    issues += omission_issues
    issues += _calendar_shape_rules(
        state,
        start=start,
        end=end,
        head_sessions=ctx.head_sessions,
        omissions=omissions,
        marked_deletions=marked_deletions,
    )
    issues += _kb_rules(doc, ctx)
    issues += _block_change_rules(doc, ctx)
    issues += _anchor_rules(doc, ctx)
    if exception_checks:
        issues += _exception_rules(doc, ctx)
        issues += _text_rules(doc, ctx)
    return issues


FreshnessReason = Literal["snapshot_expired", "stale_base_calendar", "stale_base_block", "stale_sources"]
SNAPSHOT_MAX_AGE = timedelta(hours=24)
_STALE_ISSUES: dict[str, tuple[str, str]] = {
    "stale_base_calendar": ("V3.stale_base", "base_calendar_version"),
    "stale_base_block": ("V3.stale_base", "base_block_version_id"),
    "stale_sources": ("V3.stale_sources", "snapshot_id"),
}


def proposal_freshness(
    snapshot: SnapshotRef,
    ctx: ValidationContext,
    *,
    base_calendar_version: int,
    base_block_version_id: uuid.UUID | None,
) -> list[FreshnessReason]:
    """Why a proposal can no longer be decided; an empty list means it is current.

    Gates run in order: snapshot expiry, base versions, source evidence. A later gate is not reported
    once an earlier one fails, and both base mismatches are reported together.
    """
    if (
        snapshot.as_of != ctx.today
        or snapshot.generated_at > ctx.now
        or ctx.now - snapshot.generated_at > SNAPSHOT_MAX_AGE
    ):
        return ["snapshot_expired"]
    reasons: list[FreshnessReason] = []
    if base_calendar_version != ctx.head_version:
        reasons.append("stale_base_calendar")
    if base_block_version_id != (ctx.active_block.version_id if ctx.active_block else None):
        reasons.append("stale_base_block")
    if reasons:
        return reasons
    if snapshot.source_fingerprint != ctx.current_source_fingerprint or snapshot.kb_digest != ctx.current_kb_digest:
        return ["stale_sources"]
    return []


def validate_parsed(doc: ProposalDoc, ctx: ValidationContext) -> ValidationResult:
    snapshot = ctx.snapshot
    if snapshot is None or snapshot.id != doc.snapshot_id:
        return ValidationResult("invalid", doc, [_issue("V2.snapshot_not_found", "snapshot_id")])
    if snapshot.operation != doc.operation:
        return ValidationResult("invalid", doc, [_issue("V2.operation_mismatch", "operation")])
    reasons = proposal_freshness(
        snapshot, ctx, base_calendar_version=doc.base_calendar_version, base_block_version_id=doc.base_block_version_id
    )
    if reasons == ["snapshot_expired"]:
        return ValidationResult("invalid", doc, [_issue("V2.snapshot_expired", "snapshot_id")])
    if reasons:
        return ValidationResult("stale", doc, [_issue(*_STALE_ISSUES[reason]) for reason in reasons])
    issues = _rules(doc, ctx)
    return ValidationResult("invalid" if issues else "pending", doc, issues)


def validate_document(raw: Any, ctx: ValidationContext) -> ValidationResult:
    doc, issues = parse_document(raw)
    return ValidationResult("invalid", None, issues) if doc is None else validate_parsed(doc, ctx)


def validate_subset(
    doc: ProposalDoc,
    accepted_ids: set[str],
    accept_block_change: bool,
    accepted_anchor_keys: set[str],
    ctx: ValidationContext,
) -> list[ValidationIssue]:
    if not accepted_ids and not accept_block_change and not accepted_anchor_keys:
        return []
    selected = doc.model_copy(
        update={
            "changes": [change for change in doc.changes if change.change_id in accepted_ids],
            "block_change": doc.block_change if accept_block_change else None,
            "anchor_changes": [item for item in doc.anchor_changes if anchor_key(item, ctx.tz) in accepted_anchor_keys],
        }
    )
    issues = _rules(selected, ctx, exception_checks=False)
    if anchors_allowed(doc):
        proposed: dict[str, set[str]] = {"hr": set(), "speed": set()}
        for anchor in doc.anchor_changes:
            modality = "hr" if anchor.kind.startswith("hr_") else "speed"
            proposed[modality].add(anchor_key(anchor, ctx.tz))
        for index, change in enumerate(doc.changes):
            if (
                change.change_id not in accepted_ids
                or change.after is None
                or "structure" not in change.after.model_fields_set
                or not change.after.structure
            ):
                continue

            def numeric_targets(structure: Any) -> set[tuple[str, str, float | None, float | None]]:
                values: set[tuple[str, str, float | None, float | None]] = set()
                if not isinstance(structure, list):
                    return values
                for outer, item in enumerate(structure):
                    nested = (
                        item.steps
                        if isinstance(item, RepeatBlock)
                        else item.get("steps")
                        if isinstance(item, dict) and item.get("type") == "repeat"
                        else None
                    )
                    steps = nested if nested is not None else [item]
                    for inner, step in enumerate(steps):
                        target = (
                            step.target
                            if isinstance(step, StructureStep)
                            else step.get("target")
                            if isinstance(step, dict)
                            else None
                        )
                        if target is None:
                            continue
                        modality = (
                            target.modality
                            if isinstance(target, Target)
                            else target.get("modality")
                            if isinstance(target, dict)
                            else None
                        )
                        low = (
                            target.low
                            if isinstance(target, Target)
                            else target.get("low")
                            if isinstance(target, dict)
                            else None
                        )
                        high = (
                            target.high
                            if isinstance(target, Target)
                            else target.get("high")
                            if isinstance(target, dict)
                            else None
                        )
                        if modality in {"hr", "speed"} and (low is not None or high is not None):
                            values.add((f"{outer}.{inner}", modality, low, high))
                return values

            head = ctx.head_sessions.get(change.session_uid) if change.session_uid else None
            current = numeric_targets(head.structure) if head else set()
            changed_targets = numeric_targets(change.after.structure) - current
            needed = {modality for _, modality, _, _ in changed_targets}
            if any(not proposed[modality] <= accepted_anchor_keys for modality in needed):
                issues.append(
                    _issue(
                        "V14.anchor_dependency",
                        f"changes.{index}.after.structure",
                        "Accept the associated anchor or reject the target change",
                    )
                )
    return issues
