"""Validation and atomic acceptance of reviewed coaching proposals."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.cycle import opportunity
from app.services.decision_inputs import KnowledgeResolver, VerifiedKnowledge, canonical_json, collect_decision_inputs

OPERATIONS = (
    "proceed_or_modify_today",
    "review_rolling_plan",
    "review_training_block",
    "select_quality_session",
    "recalibrate_intensity",
    "handle_goal_or_race_change",
)
RECIPE_IDS = {f"REC{n:03d}" for n in range(1, 11)}
QUALITY_RECIPES = {"REC003", "REC004", "REC005", "REC006", "REC008", "REC009"}
LONG_RECIPE = "REC002"
BLOCK_OPS = {"review_training_block", "handle_goal_or_race_change"}
OFF_CYCLE_OPS = {"review_rolling_plan", "review_training_block", "handle_goal_or_race_change"}
ANCHOR_UNIT = {
    "hr_aerobic_upper": "bpm",
    "hr_threshold_lower": "bpm",
    "speed_aerobic_upper": "mps",
    "speed_threshold_lower": "mps",
    "performance_5k": "s",
    "performance_1mile": "s",
    "performance_3min": "m",
    "performance_20_30min": "mps",
}
ANCHOR_KINDS = set(ANCHOR_UNIT)
ANCHOR_UNITS = {"bpm", "mps", "s", "m"}
PROTOCOLS = {
    "race_5k",
    "time_trial_5k",
    "time_trial_1mile",
    "time_trial_3min",
    "time_trial_20_30min",
    "workout_derived",
    "lab_test",
    "manual",
}
ANCHOR_CONFIDENCE = {"high", "moderate", "low", "insufficient"}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Confidence(Strict):
    decision: Literal["high", "moderate", "low"]
    evidence: Literal["high", "moderate", "low"]
    data: Literal["high", "moderate", "low"]


class Target(Strict):
    modality: Literal["speed", "hr", "effort"]
    low: float | None = None
    high: float | None = None
    effort_cue: str | None = Field(None, max_length=200)


class StructureStep(Strict):
    type: Literal["warmup", "work", "recovery", "cooldown"]
    duration_type: Literal["time", "distance"]
    duration_value: float = Field(gt=0)
    target: Target | None = None


class RepeatBlock(Strict):
    type: Literal["repeat"]
    count: int = Field(ge=2)
    steps: list[StructureStep] = Field(min_length=1)


class SessionFields(Strict):
    local_date: date | None = None
    slot: int | None = Field(None, ge=0)
    kind: Literal["run", "strength", "cross", "rest", "mobility"] | None = None
    recipe_id: str | None = None
    custom: bool | None = None
    placeholder: bool | None = None
    locked: bool | None = None
    intent: str | None = Field(None, max_length=200)
    planned_duration_s: int | None = Field(None, gt=0)
    planned_distance_m: int | None = Field(None, gt=0)
    structure: list[StructureStep | RepeatBlock] | None = None
    strength_slot_id: uuid.UUID | None = None
    notes: str | None = None


class Change(Strict):
    change_id: str = Field(pattern=r"^c[1-9][0-9]{0,9}$")
    op: Literal["add", "modify", "move", "delete"]
    session_uid: uuid.UUID | None = None
    after: SessionFields | None = None
    reason: str = Field(min_length=1)
    material_flags: list[Literal["off_cycle_run", "strength_move"]] = Field(default_factory=list)

    @model_validator(mode="after")
    def shape(self) -> Change:
        keys = self.after.model_fields_set if self.after else set()
        if self.op == "add" and (
            self.session_uid is not None or self.after is None or not {"local_date", "kind", "intent"} <= keys
        ):
            raise ValueError("add requires local_date, kind, intent and no session_uid")
        if self.op == "modify" and (self.session_uid is None or self.after is None or not keys or "local_date" in keys):
            raise ValueError("modify requires session_uid and non-date after fields")
        if self.op == "move" and (
            self.session_uid is None
            or self.after is None
            or "local_date" not in keys
            or not keys <= {"local_date", "slot"}
        ):
            raise ValueError("move requires session_uid and local_date/slot only")
        if self.op == "delete" and (self.session_uid is None or self.after is not None):
            raise ValueError("delete requires session_uid and no after")
        return self


class BlockConstraint(Strict):
    kind: str
    text: str


class BlockVersionFields(Strict):
    status: Literal["draft", "active", "consolidating", "completed", "replaced", "ended"]
    objective: str
    rationale: str
    maintained_qualities: list[str]
    non_goals: list[str]
    eligible_recipe_ids: list[str]
    progression_dimension: Literal["duration", "frequency", "long_run", "quality_volume", "intensity", "none"]
    constraints: list[BlockConstraint]
    start_date: date
    review_date: date
    completion_indicators: list[str]
    early_review_triggers: list[str]
    objective_status: Literal["unresolved", "partially_achieved", "achieved", "not_achieved"]


class BlockChange(Strict):
    decision: Literal["start", "continue", "extend", "consolidate", "transition", "replace", "end"]
    block_uid: uuid.UUID | None
    version_fields: BlockVersionFields


class AnchorChange(Strict):
    kind: str
    value_low: float
    value_high: float | None = None
    unit: str
    protocol: str
    confidence: str
    calibrated_at: AwareDatetime
    source_activity_id: uuid.UUID | None = None
    conditions: str | None = None
    supersedes_key: str | None = Field(None, max_length=40)


class ProposalDoc(Strict):
    schema_version: Literal["coach_proposal.v1"]
    operation: Literal[*OPERATIONS]  # type: ignore[valid-type]
    snapshot_id: uuid.UUID
    base_calendar_version: int = Field(ge=0)
    base_block_version_id: uuid.UUID | None
    summary: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=8000)
    confidence: Confidence
    changes: list[Change] = Field(max_length=50)
    preserved: list[uuid.UUID] = Field(default_factory=list)
    block_change: BlockChange | None = None
    anchor_changes: list[AnchorChange] = Field(default_factory=list)
    evidence_ids: list[str]
    policy_ids: list[str]
    recipe_ids: list[str]
    observations_used: list[str] = Field(default_factory=list)
    follow_up: str | None = None
    escalation: Literal[*OPERATIONS] | None = None  # type: ignore[valid-type]
    skill_version: Literal["running-coach.v1"]


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str

    def to_json(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class HeadSession:
    session_uid: uuid.UUID
    revision: int
    local_date: date
    slot: int
    kind: str
    recipe_id: str | None
    custom: bool
    placeholder: bool
    locked: bool
    legacy_unstructured: bool
    intent: str
    certainty: str
    planned_duration_s: int | None
    planned_distance_m: int | None
    structure: list | None
    strength_slot_id: uuid.UUID | None
    notes: str | None


def session_fields(row: HeadSession) -> dict[str, Any]:
    """Return only the calendar fields a reviewed proposal may edit."""
    return {
        key: getattr(row, key)
        for key in (
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
            "notes",
        )
    }


@dataclass(frozen=True)
class ActiveBlock:
    block_uid: uuid.UUID
    version_id: uuid.UUID
    version: int
    eligible_recipe_ids: tuple[str, ...]


@dataclass(frozen=True)
class SnapshotRef:
    id: uuid.UUID
    operation: str
    as_of: date
    generated_at: datetime
    source_fingerprint: str
    kb_routes: tuple[dict, ...]
    kb_digest: str
    safety_guard: dict | None


@dataclass(frozen=True)
class ValidationContext:
    now: datetime
    today: date
    tz: ZoneInfo
    snapshot: SnapshotRef | None
    head_version: int
    head_sessions: dict[uuid.UUID, HeadSession]
    active_block: ActiveBlock | None
    cycle_anchor: date | None
    current_safety_guard: dict | None
    current_source_fingerprint: str
    current_kb_digest: str
    kb: VerifiedKnowledge


@dataclass(frozen=True)
class ValidationResult:
    status: Literal["pending", "invalid", "stale"]
    doc: ProposalDoc | None
    issues: list[ValidationIssue]


def parse_document(raw: Any) -> tuple[ProposalDoc | None, list[ValidationIssue]]:
    try:
        return ProposalDoc.model_validate(raw), []
    except ValidationError as exc:
        return None, [
            ValidationIssue("V1.schema", ".".join(str(part) for part in error["loc"]), error["msg"])
            for error in exc.errors()
        ]


def safety_active(guard: dict | None) -> bool:
    if not isinstance(guard, dict):
        return True
    severity = guard.get("max_symptom_severity")
    return bool(
        guard.get("gait_change_yes")
        or (severity is not None and severity >= 6.5)
        or guard.get("illness_present")
        or guard.get("clinical_restriction_active")
        or guard.get("legacy_safety_active")
    )


def is_quality_slot(kind: str, recipe_id: str | None, placeholder: bool) -> bool:
    return kind == "run" and (recipe_id in QUALITY_RECIPES or placeholder)


def scope(operation: str, today: date) -> tuple[date, date]:
    return today, today + timedelta(days=3 if operation == "proceed_or_modify_today" else 13)


def derive_certainty(day: date, today: date) -> str:
    return "committed" if day <= today + timedelta(days=6) else "provisional"


def anchor_key(item: AnchorChange, tz: ZoneInfo) -> str:
    return f"{item.kind}-{item.calibrated_at.astimezone(tz).date().isoformat()}"


def _issue(code: str, path: str, message: str | None = None) -> ValidationIssue:
    return ValidationIssue(code, path, message or code)


def _resulting(doc: ProposalDoc, ctx: ValidationContext) -> dict[str, dict]:
    state = {str(uid): dict(vars(row)) for uid, row in ctx.head_sessions.items()}
    for change in doc.changes:
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
            }
        elif uid in state and change.after:
            state[uid].update(change.after.model_dump(include=change.after.model_fields_set))
    return state


def _rules(doc: ProposalDoc, ctx: ValidationContext) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    start, end = scope(doc.operation, ctx.today)
    state = _resulting(doc, ctx)
    before = {str(uid): dict(vars(row)) for uid, row in ctx.head_sessions.items()}
    seen_ids: set[str] = set()
    seen_uids: set[uuid.UUID] = set()
    for i, change in enumerate(doc.changes):
        path = f"changes.{i}"
        head = ctx.head_sessions.get(change.session_uid) if change.session_uid else None
        after = change.after
        fields = after.model_fields_set if after else set()
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
            issues.append(_issue("V5.out_of_scope", path))
        check_recipe = (change.op == "add" and result.get("kind") == "run") or (
            change.op == "modify"
            and result.get("kind") == "run"
            and bool(fields & {"kind", "recipe_id", "custom", "structure"})
        )
        if check_recipe:
            recipe = result.get("recipe_id")
            if not recipe and not (result.get("custom") and result.get("structure")):
                issues.append(_issue("V6.recipe_required", f"{path}.after"))
            elif recipe:
                if recipe not in RECIPE_IDS:
                    issues.append(_issue("V6.unknown_recipe", f"{path}.after.recipe_id"))
                else:
                    eligible = (
                        doc.block_change.version_fields.eligible_recipe_ids
                        if doc.block_change
                        else (ctx.active_block.eligible_recipe_ids if ctx.active_block else ())
                    )
                    if recipe not in eligible:
                        issues.append(_issue("V6.recipe_not_eligible", f"{path}.after.recipe_id"))
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
            if doc.operation == "proceed_or_modify_today":
                issues.append(_issue("V9.daily_strength_move", path))
            elif "strength_move" not in change.material_flags:
                issues.append(_issue("V9.strength_move_flag", path))
        if doc.operation == "proceed_or_modify_today" and (
            (change.op in {"add", "delete"} and result.get("kind") == "strength")
            or (change.op == "modify" and head and (head.kind == "strength") != (result.get("kind") == "strength"))
        ):
            issues.append(_issue("V9.daily_strength_change", path))
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

            if count(state) > count(before):
                issues.append(_issue("V10.quality_pileup", path))
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
                        head.planned_duration_s is None
                        or (result.get("planned_duration_s") or 0) > head.planned_duration_s
                    )
                )
                or (
                    change.op in {"add", "modify"}
                    and "recipe_id" in fields
                    and result.get("recipe_id") in QUALITY_RECIPES
                )
            )
            if unsafe:
                issues.append(_issue("V12.safety_guard", path))
        if doc.operation == "select_quality_session" and (
            change.op != "modify" or not head or not is_quality_slot(head.kind, head.recipe_id, head.placeholder)
        ):
            issues.append(_issue("V15.not_quality_slot", path))
        if doc.operation == "recalibrate_intensity" and (
            change.op != "modify" or not fields <= {"intent", "structure", "notes"}
        ):
            issues.append(_issue("V15.recalibrate_change_not_allowed", path))
    for j, uid in enumerate(doc.preserved):
        if uid not in ctx.head_sessions:
            issues.append(_issue("V4.unknown_preserved", f"preserved.{j}"))
    for day_offset in range((end - start).days + 1):
        day = start + timedelta(days=day_offset)
        if sum(row["kind"] == "run" and row["local_date"] == day for row in state.values()) > 1:
            issues.append(_issue("V7.multiple_runs_per_day", "changes", day.isoformat()))
    week = start - timedelta(days=start.weekday())
    while week <= end:
        rows = [row for row in state.values() if week <= row["local_date"] <= week + timedelta(days=6)]
        if week >= start and week + timedelta(days=6) <= end and sum(row["kind"] == "strength" for row in rows) < 2:
            issues.append(_issue("V9.strength_count", "changes"))
        if sum(row["kind"] == "run" and row.get("recipe_id") == LONG_RECIPE for row in rows) > 1:
            issues.append(_issue("V10.multiple_long", "changes"))
        week += timedelta(days=7)
    for field, allowed in [
        ("policy_ids", ctx.kb.policy_ids),
        ("recipe_ids", ctx.kb.recipe_ids),
        ("evidence_ids", ctx.kb.evidence_ids),
    ]:
        for j, value in enumerate(getattr(doc, field)):
            if value not in allowed:
                issues.append(_issue("V11.unknown_kb_id", f"{field}.{j}"))
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
    if doc.anchor_changes and doc.operation != "recalibrate_intensity":
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


def validate_parsed(doc: ProposalDoc, ctx: ValidationContext) -> ValidationResult:
    snapshot = ctx.snapshot
    if snapshot is None or snapshot.id != doc.snapshot_id:
        return ValidationResult("invalid", doc, [_issue("V2.snapshot_not_found", "snapshot_id")])
    if snapshot.operation != doc.operation:
        return ValidationResult("invalid", doc, [_issue("V2.operation_mismatch", "operation")])
    if (
        snapshot.as_of != ctx.today
        or snapshot.generated_at > ctx.now
        or ctx.now - snapshot.generated_at > timedelta(hours=24)
    ):
        return ValidationResult("invalid", doc, [_issue("V2.snapshot_expired", "snapshot_id")])
    stale: list[ValidationIssue] = []
    if doc.base_calendar_version != ctx.head_version:
        stale.append(_issue("V3.stale_base", "base_calendar_version"))
    if doc.base_block_version_id != (ctx.active_block.version_id if ctx.active_block else None):
        stale.append(_issue("V3.stale_base", "base_block_version_id"))
    if stale:
        return ValidationResult("stale", doc, stale)
    if snapshot.source_fingerprint != ctx.current_source_fingerprint or snapshot.kb_digest != ctx.current_kb_digest:
        return ValidationResult("stale", doc, [_issue("V3.stale_sources", "snapshot_id")])
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
    selected = doc.model_copy(
        update={
            "changes": [change for change in doc.changes if change.change_id in accepted_ids],
            "block_change": doc.block_change if accept_block_change else None,
            "anchor_changes": [item for item in doc.anchor_changes if anchor_key(item, ctx.tz) in accepted_anchor_keys],
        }
    )
    issues = _rules(selected, ctx)
    if doc.operation == "recalibrate_intensity":
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


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _lock(session: Session) -> Any:
    from app.models import AppState

    session.execute(text("SELECT pg_advisory_xact_lock(71382413)"))
    state = session.get(AppState, 1, with_for_update=True, populate_existing=True)
    if state is None or state.planning_authority != "calendar":
        raise DecisionError("planning_not_active", "Calendar planning is not active", 409)
    return state


def _snapshot_ref(row: Any) -> SnapshotRef:
    meta = (row.payload or {}).get("snapshot_meta") or {}
    routes = row.kb_routes
    selection = routes.get("selection", []) if isinstance(routes, dict) else routes
    return SnapshotRef(
        row.id,
        row.operation,
        row.as_of,
        row.generated_at,
        row.source_fingerprint,
        tuple(selection),
        row.kb_digest,
        meta.get("safety_guard"),
    )


def _active_block(session: Session) -> ActiveBlock | None:
    from app.planning_models import BlockVersion

    rows = list(session.scalars(select(BlockVersion).order_by(BlockVersion.block_uid, BlockVersion.version.desc())))
    latest_by_uid: dict[uuid.UUID, Any] = {}
    for row in rows:
        latest_by_uid.setdefault(row.block_uid, row)
    active = [row for row in latest_by_uid.values() if row.status in {"active", "consolidating"}]
    if not active:
        return None
    row = max(active, key=lambda item: (item.created_at, item.version, str(item.id)))
    return ActiveBlock(row.block_uid, row.id, row.version, tuple(row.eligible_recipe_ids))


def load_context(
    session: Session, snapshot_id: uuid.UUID, *, now: datetime, kb: VerifiedKnowledge
) -> ValidationContext:
    from app.coach_v2_models import CoachSnapshot
    from app.models import AppState, ProfileVersion
    from app.services.calendar import state_at
    from app.services.timezone import athlete_tz

    snapshot = session.get(CoachSnapshot, snapshot_id)
    tz = athlete_tz(session)
    today = now.astimezone(tz).date()
    state = session.get(AppState, 1)
    head = state.calendar_head_version if state else 0
    rows = state_at(session, head)
    head_sessions = {
        row["session_uid"]: HeadSession(
            row["session_uid"],
            row["revision"],
            row["local_date"],
            row["slot"],
            row["kind"],
            row.get("recipe_id"),
            row.get("custom", False),
            row.get("placeholder", False),
            row.get("locked", False),
            row.get("legacy_unstructured", False),
            row.get("intent", ""),
            row.get("certainty", ""),
            row.get("planned_duration_s"),
            row.get("planned_distance_m"),
            row.get("structure"),
            row.get("strength_slot_id"),
            row.get("notes"),
        )
        for row in rows
    }
    profile = session.scalars(select(ProfileVersion).order_by(ProfileVersion.version.desc()).limit(1)).first()
    anchor = profile.cycle_anchor if profile and profile.anchor_confirmed else None
    inputs = (
        collect_decision_inputs(session, snapshot.operation, snapshot.as_of, now=now, kb=kb)
        if snapshot
        else {"source_fingerprint": "", "safety_guard": None}
    )
    return ValidationContext(
        now,
        today,
        tz,
        _snapshot_ref(snapshot) if snapshot else None,
        head,
        head_sessions,
        _active_block(session),
        anchor,
        inputs["safety_guard"] if isinstance(inputs["safety_guard"], dict) else None,
        str(inputs["source_fingerprint"]),
        kb.digest,
        kb,
    )


@dataclass(frozen=True)
class SubmitResult:
    proposal_id: uuid.UUID
    status: str
    issues: list[ValidationIssue]


def submit_proposal(session: Session, raw: dict, *, now: datetime, resolve_kb: KnowledgeResolver) -> SubmitResult:
    from app.coach_v2_models import CoachProposal, CoachProposalChange, CoachSnapshot

    _lock(session)
    input_hash = _hash(raw)
    existing = session.scalar(select(CoachProposal).where(CoachProposal.input_hash == input_hash))
    if existing:
        return SubmitResult(
            existing.id,
            existing.status,
            [
                ValidationIssue(item["code"], item["path"], item["message"])
                for item in cast(list[dict], existing.validation_errors or [])
            ],
        )
    doc, issues = parse_document(raw)
    if doc is None:
        raise DecisionError("invalid_proposal", "Proposal schema invalid", 422, issues)
    snapshot = session.get(CoachSnapshot, doc.snapshot_id)
    if snapshot is None:
        raise DecisionError("snapshot_not_found", "Snapshot not found", 404)
    kb = resolve_kb(_snapshot_ref(snapshot).kb_routes)
    ctx = load_context(session, doc.snapshot_id, now=now, kb=kb)
    result = validate_parsed(doc, ctx)
    proposal = CoachProposal(
        operation=doc.operation,
        snapshot_id=doc.snapshot_id,
        base_calendar_version=doc.base_calendar_version,
        base_block_version_id=doc.base_block_version_id,
        status=result.status,
        submitted_at=now,
        summary=doc.summary,
        rationale=doc.rationale,
        confidence=doc.confidence.model_dump(),
        evidence_ids=doc.evidence_ids,
        policy_ids=doc.policy_ids,
        recipe_ids=doc.recipe_ids,
        follow_up=doc.follow_up,
        escalation=doc.escalation,
        block_change=doc.block_change.model_dump(mode="json") if doc.block_change else None,
        anchor_changes=[item.model_dump(mode="json") for item in doc.anchor_changes],
        payload=doc.model_dump(mode="json", exclude_unset=True),
        validation_errors=[issue.to_json() for issue in result.issues],
        skill_version=doc.skill_version,
        input_hash=input_hash,
    )
    session.add(proposal)
    session.flush()
    for change in doc.changes:
        before = ctx.head_sessions.get(change.session_uid) if change.session_uid else None
        session.add(
            CoachProposalChange(
                proposal_id=proposal.id,
                change_id=change.change_id,
                op=change.op,
                session_uid=change.session_uid,
                before=canonical_json(vars(before))
                if False
                else (
                    {
                        key: str(value)
                        if isinstance(value, uuid.UUID)
                        else value.isoformat()
                        if isinstance(value, date)
                        else value
                        for key, value in vars(before).items()
                    }
                    if before
                    else None
                ),
                after=change.after.model_dump(mode="json", exclude_unset=True) if change.after else None,
                reason=change.reason,
                decision="pending",
            )
        )
    session.flush()
    return SubmitResult(proposal.id, result.status, result.issues)


def mark_pending_stale(session: Session, *, except_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    from app.coach_v2_models import CoachProposal

    query = select(CoachProposal).where(CoachProposal.status == "pending")
    if except_id:
        query = query.where(CoachProposal.id != except_id)
    rows = list(session.scalars(query))
    for row in rows:
        row.status = "stale"
    return [row.id for row in rows]


class DecisionRequest(Strict):
    idempotency_key: str = Field(min_length=8, max_length=100)
    expected_head: int = Field(ge=0)
    accept_change_ids: list[str]
    reject_change_ids: list[str]
    accept_block_change: bool = False
    accept_anchor_changes: list[str] = Field(default_factory=list)


class DecisionError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        http_status: int,
        fields: list[ValidationIssue] | None = None,
        commit: bool = False,
    ):
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status
        self.fields, self.commit = fields or [], commit


@dataclass(frozen=True)
class DecisionResult:
    proposal_id: uuid.UUID
    status: str
    calendar_version: int | None
    block_version_id: uuid.UUID | None
    anchor_keys: list[str]
    stale_proposals: list[uuid.UUID]


def _selection(proposal_id: uuid.UUID, req: DecisionRequest) -> dict:
    accepted, rejected, anchors = req.accept_change_ids, req.reject_change_ids, req.accept_anchor_changes
    if len(set(accepted)) != len(accepted) or len(set(rejected)) != len(rejected) or len(set(anchors)) != len(anchors):
        raise DecisionError("invalid_decision", "Duplicate selected IDs", 422)
    return {
        "proposal_id": str(proposal_id),
        "accept_change_ids": sorted(accepted),
        "reject_change_ids": sorted(rejected),
        "accept_block_change": req.accept_block_change,
        "accept_anchor_changes": sorted(anchors),
    }


def _store_alias(session: Session, key: str, proposal_id: uuid.UUID, decision_hash: str, result: dict) -> None:
    from app.coach_v2_models import CoachDecisionKey

    session.add(
        CoachDecisionKey(idempotency_key=key, proposal_id=proposal_id, decision_hash=decision_hash, result=result)
    )
    session.flush()


def _save_block(
    session: Session, doc: ProposalDoc, proposal_id: uuid.UUID, ctx: ValidationContext, now: datetime
) -> tuple[uuid.UUID, bool]:
    from app.planning_models import Block, BlockDecision, BlockVersion

    change = doc.block_change
    assert change is not None
    old = ctx.active_block
    block_uid = change.block_uid if old else uuid.uuid4()
    if not old:
        session.add(Block(block_uid=block_uid))
        session.flush()
    fields = change.version_fields.model_dump(mode="python")
    fields["constraints"] = [item.model_dump() for item in change.version_fields.constraints]
    if old:
        previous = session.get(BlockVersion, old.version_id)
        assert previous is not None
        if all(getattr(previous, key) == value for key, value in fields.items()):
            return previous.id, False
    version = BlockVersion(
        block_uid=block_uid, version=(old.version + 1 if old else 1), proposal_id=proposal_id, **fields
    )
    session.add(version)
    session.flush()
    session.add(
        BlockDecision(
            block_uid=block_uid,
            decision=change.decision,
            from_version=old.version if old else None,
            to_version=version.version,
            rationale=doc.rationale,
            evidence_ids=doc.evidence_ids,
            policy_ids=doc.policy_ids,
            confidence=doc.confidence.decision,
            proposal_id=proposal_id,
            decided_at=now,
        )
    )
    return version.id, True


def decide_proposal(
    session: Session, proposal_id: uuid.UUID, req: DecisionRequest, *, now: datetime, resolve_kb: KnowledgeResolver
) -> DecisionResult:
    from app.coach_v2_models import CoachDecisionKey, CoachProposal, CoachProposalChange
    from app.metrics.anchors import create_anchor
    from app.services.calendar import apply_edits

    state = _lock(session)
    proposal = session.scalar(select(CoachProposal).where(CoachProposal.id == proposal_id).with_for_update())
    if proposal is None:
        raise DecisionError("proposal_not_found", "Proposal not found", 404)
    selection = _selection(proposal_id, req)
    decision_hash = _hash(selection)
    key = session.get(CoachDecisionKey, req.idempotency_key)
    if key and key.proposal_id != proposal_id:
        raise DecisionError("idempotency_conflict", "Key belongs to another proposal", 409)
    if key and key.decision_hash != decision_hash:
        raise DecisionError("decision_conflict", "Decision selection changed", 409)
    if proposal.status in {"accepted", "partially_accepted", "rejected"}:
        if proposal.decision_hash != decision_hash or not proposal.decision_result:
            raise DecisionError("decision_conflict", "Decision selection changed", 409)
        if key is None:
            _store_alias(session, req.idempotency_key, proposal_id, decision_hash, proposal.decision_result)
        stored = proposal.decision_result
        return DecisionResult(
            proposal_id,
            stored["status"],
            stored["calendar_version"],
            uuid.UUID(stored["block_version_id"]) if stored["block_version_id"] else None,
            list(stored["anchor_keys"]),
            [uuid.UUID(value) for value in stored["stale_proposals"]],
        )
    if proposal.status != "pending":
        raise DecisionError("proposal_stale", "Proposal is no longer pending", 409)
    if req.expected_head != state.calendar_head_version:
        raise DecisionError("calendar_head_moved", "Calendar changed", 409)
    doc = ProposalDoc.model_validate(proposal.payload)
    if proposal.base_calendar_version != state.calendar_head_version or proposal.base_block_version_id != (
        block.version_id if (block := _active_block(session)) else None
    ):
        proposal.status = "stale"
        raise DecisionError("proposal_stale", "Proposal base changed", 409, commit=True)
    from app.services.timezone import athlete_tz

    today = now.astimezone(athlete_tz(session)).date()
    from app.coach_v2_models import CoachSnapshot

    snapshot = session.get(CoachSnapshot, proposal.snapshot_id)
    if (
        snapshot is None
        or snapshot.as_of != today
        or snapshot.generated_at > now
        or now - snapshot.generated_at > timedelta(hours=24)
    ):
        proposal.status = "stale"
        raise DecisionError("proposal_stale", "Proposal expired", 409, commit=True)
    try:
        kb = resolve_kb(_snapshot_ref(snapshot).kb_routes)
    except Exception as exc:
        raise DecisionError("knowledge_unavailable", "Verified knowledge is unavailable", 503) from exc
    ctx = load_context(session, proposal.snapshot_id, now=now, kb=kb)
    if snapshot.source_fingerprint != ctx.current_source_fingerprint or snapshot.kb_digest != ctx.current_kb_digest:
        proposal.status = "stale"
        raise DecisionError("stale_evidence", "Decision evidence changed", 409, commit=True)
    accepted, rejected, anchors = set(req.accept_change_ids), set(req.reject_change_ids), set(req.accept_anchor_changes)
    required = {change.change_id for change in doc.changes}
    known_anchors = {anchor_key(item, ctx.tz) for item in doc.anchor_changes}
    if (
        accepted & rejected
        or accepted | rejected != required
        or not anchors <= known_anchors
        or (req.accept_block_change and doc.block_change is None)
    ):
        raise DecisionError("decision_incomplete", "Selection must partition all changes", 422)
    issues = validate_subset(doc, accepted, req.accept_block_change, anchors, ctx)
    if issues:
        raise DecisionError("proposal_invalid_subset", "Accepted subset is invalid", 422, issues)
    block_id = ctx.active_block.version_id if ctx.active_block else None
    changed = False
    if req.accept_block_change:
        block_id, block_changed = _save_block(session, doc, proposal_id, ctx, now)
        if block_changed:
            from app.metrics.engine import enqueue_scopes

            enqueue_scopes(session, ["calendar"])
            changed = True
    anchor_keys: list[str] = []
    for item in doc.anchor_changes:
        if anchor_key(item, ctx.tz) in anchors:
            fields = item.model_dump(mode="python")
            fields.update(
                proposal_id=proposal_id,
                valid_from=today,
                review_after=item.calibrated_at.astimezone(ctx.tz).date() + timedelta(days=84),
            )
            anchor_keys.append(create_anchor(session, fields)["anchor_key"])
            changed = True
    edits = []
    for change in doc.changes:
        if change.change_id not in accepted:
            continue
        edit_fields: dict[str, Any] | None = (
            change.after.model_dump(mode="python", exclude_unset=True) if change.after else None
        )
        head = ctx.head_sessions.get(change.session_uid) if change.session_uid else None
        if (
            change.op in {"modify", "move"}
            and head
            and edit_fields
            and all(getattr(head, key) == value for key, value in edit_fields.items())
        ):
            continue
        edits.append({"op": change.op, "session_uid": change.session_uid, "fields": edit_fields})
    calendar_version = None
    stale: list[uuid.UUID] = []
    if edits:
        result = apply_edits(
            session,
            state.calendar_head_version,
            edits,
            doc.summary,
            kind="proposal_accept",
            actor="coach",
            proposal_id=proposal_id,
            block_version_id=block_id,
        )
        calendar_version = result["version"]
        stale = result["stale_proposals"]
        changed = True
        from app.calendar_models import CalendarSessionRevision

        created = list(
            session.scalars(
                select(CalendarSessionRevision)
                .where(
                    CalendarSessionRevision.calendar_version_number == calendar_version,
                    CalendarSessionRevision.revision == 1,
                )
                .order_by(CalendarSessionRevision.session_uid)
            )
        )
        for change in doc.changes:
            if change.change_id not in accepted or change.op != "add" or change.after is None:
                continue
            supplied = change.after.model_dump(mode="python", exclude_unset=True)
            match = next(
                (row for row in created if all(getattr(row, key) == value for key, value in supplied.items())), None
            )
            if match is None:
                raise RuntimeError("accepted_add_not_found")
            created.remove(match)
            proposal_change = session.scalar(
                select(CoachProposalChange).where(
                    CoachProposalChange.proposal_id == proposal_id,
                    CoachProposalChange.change_id == change.change_id,
                )
            )
            assert proposal_change is not None
            proposal_change.session_uid = match.session_uid
    for row in session.scalars(select(CoachProposalChange).where(CoachProposalChange.proposal_id == proposal_id)):
        row.decision = "accepted" if row.change_id in accepted else "rejected"
    accepted_count = len(accepted) + int(req.accept_block_change) + len(anchors)
    total_count = len(required) + int(doc.block_change is not None) + len(known_anchors)
    status = (
        "accepted"
        if total_count == 0 or accepted_count == total_count
        else "rejected"
        if accepted_count == 0
        else "partially_accepted"
    )
    proposal.status = status
    proposal.decided_at = now
    proposal.decision_idempotency_key = req.idempotency_key
    proposal.decision_hash = decision_hash
    if changed:
        stale = list(dict.fromkeys([*stale, *mark_pending_stale(session, except_id=proposal_id)]))
    decision_result = DecisionResult(
        proposal_id, status, calendar_version, block_id if req.accept_block_change else None, anchor_keys, stale
    )
    stored = {
        "status": status,
        "calendar_version": calendar_version,
        "block_version_id": str(decision_result.block_version_id) if decision_result.block_version_id else None,
        "anchor_keys": anchor_keys,
        "stale_proposals": [str(uid) for uid in stale],
    }
    proposal.decision_result = stored
    _store_alias(session, req.idempotency_key, proposal_id, decision_hash, stored)
    return decision_result
