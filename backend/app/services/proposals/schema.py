"""Coach proposal schema."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal, NamedTuple
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.domain.local_time import date_in_zone
from app.domain.session_class import QUALITY_RECIPES
from app.services.block_benchmark import BenchmarkOutcome
from app.services.decision_inputs import (
    VerifiedKnowledge,
)
from app.services.exceptions.vocab import LadderLevel, PatchCategory, Severity
from app.services.operations import Operation

RECIPE_IDS = {f"REC{n:03d}" for n in range(1, 11)}
BLOCK_OPS = {"review_training_block", "handle_goal_or_race_change"}
OFF_CYCLE_OPS = {"review_rolling_plan", "review_training_block", "handle_goal_or_race_change"}
PATCH_SCOPE_OPS = {"exception_review", "post_event_review"}
HORIZON_OPS = {"review_rolling_plan", "review_training_block", "handle_goal_or_race_change"}
HORIZON_MIN_DAYS = 13
HORIZON_MAX_DAYS = 42
BLOCK_REVIEW_LEAD_DAYS = 7
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
    low: float | None = Field(None, description="Numeric speed/HR lower bound; must be null for effort targets.")
    high: float | None = Field(None, description="Numeric speed/HR upper bound; must be null for effort targets.")
    effort_cue: str | None = Field(
        None, max_length=200, description="Required nonblank cue for effort targets; include any RPE range here."
    )


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
    material_flags: list[Literal["off_cycle_run", "strength_move", "strength_omission"]] = Field(default_factory=list)

    @property
    def is_unplanned_strength_omission(self) -> bool:
        return self.op == "add" and "strength_omission" in self.material_flags

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


class BlockBenchmark(Strict):
    kind: Literal["time_trial", "event"]
    event_id: uuid.UUID | None = None
    protocol: str = Field(max_length=300)
    distance_m: int | None = None
    planned_date: date
    progress_if: str = Field(max_length=300)
    consolidate_if: str = Field(max_length=300)


class OutlineStep(Strict):
    emphasis: str = Field(min_length=1, max_length=120)
    weeks: int = Field(ge=1, le=8)


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
    benchmark: BlockBenchmark | None = None
    target_event_id: uuid.UUID | None = None
    build_outline: list[OutlineStep] = Field(default_factory=list, max_length=8)


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


RESOLUTION_OPS = {"exception_review", "review_rolling_plan", "review_training_block", "post_event_review"}
ANCHOR_OPS = {"recalibrate_intensity", "post_event_review"}
NO_STRENGTH_EDIT_OPS = {"proceed_or_modify_today", "exception_review"}
Criterion = Annotated[str, Field(max_length=200)]


def anchors_allowed(doc: ProposalDoc) -> bool:
    return doc.operation in ANCHOR_OPS or (doc.operation == "review_training_block" and doc.event_review is not None)


class PatchWindow(Strict):
    start: date
    end: date


class UnchangedSession(Strict):
    session_uid: uuid.UUID
    reason: str = Field(max_length=200)


class ExceptionBlock(Strict):
    finding_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    category: PatchCategory
    severity: Severity
    confidence: Literal["low", "moderate", "high"]
    triggering_evidence: str = Field(max_length=600)
    relevant_context: str | None = Field(default=None, max_length=600)
    ladder_level: LadderLevel
    patch_window: PatchWindow
    unchanged: list[UnchangedSession] = Field(default_factory=list, max_length=14)
    reassess_on: date
    monitor: list[Criterion] = Field(min_length=1, max_length=6)
    return_criteria: list[Criterion] = Field(min_length=1, max_length=6)
    escalate_criteria: list[Criterion] = Field(min_length=1, max_length=6)


class EventReview(Strict):
    event_id: uuid.UUID | None = None
    activity_id: uuid.UUID | None = None
    outcome: BenchmarkOutcome | None = None
    compared_with: str | None = Field(default=None, max_length=300)
    pacing: str = Field(max_length=600)
    effort_and_limiter: str = Field(max_length=600)
    conditions: str | None = Field(default=None, max_length=400)
    symptoms: str | None = Field(default=None, max_length=400)
    recovery_observation: str = Field(max_length=600)
    recalibration: Literal["none", "propose_anchors", "defer"]
    training_implication: str = Field(max_length=600)


class PatchResolution(Strict):
    patch_id: uuid.UUID
    status: Literal["resolved", "escalated"]
    note: str = Field(max_length=300)


class ProposalDoc(Strict):
    schema_version: Literal["coach_proposal.v1"]
    operation: Operation
    snapshot_id: uuid.UUID
    base_calendar_version: int = Field(ge=0)
    base_block_version_id: uuid.UUID | None
    summary: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=8000)
    confidence: Confidence
    changes: list[Change] = Field(max_length=80)
    preserved: list[uuid.UUID] = Field(default_factory=list)
    block_change: BlockChange | None = None
    anchor_changes: list[AnchorChange] = Field(default_factory=list)
    evidence_ids: list[str]
    policy_ids: list[str]
    recipe_ids: list[str]
    observations_used: list[str] = Field(default_factory=list)
    follow_up: str | None = None
    escalation: Operation | None = None
    exception: ExceptionBlock | None = None
    event_review: EventReview | None = None
    patch_resolutions: list[PatchResolution] = Field(default_factory=list, max_length=10)
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


@dataclass(frozen=True)
class ActiveBlock:
    block_uid: uuid.UUID
    version_id: uuid.UUID
    version: int
    eligible_recipe_ids: tuple[str, ...]
    review_date: date


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


class EventRef(NamedTuple):
    status: str
    day: date
    rank: int | None
    purpose: str | None = None


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
    findings: dict[uuid.UUID, str] = dataclass_field(default_factory=dict)
    patches: dict[uuid.UUID, str] = dataclass_field(default_factory=dict)
    events: dict[uuid.UUID, EventRef] = dataclass_field(default_factory=dict)
    open_rule_codes: frozenset[str] = frozenset()
    benchmark: Any = None
    last_benchmark_date: date | None = None
    confirmed_strength_dates: frozenset[date] = frozenset()
    confirmed_strength_slot_ids: dict[date, uuid.UUID] = dataclass_field(default_factory=dict)
    accepted_strength_omission_dates: frozenset[date] = frozenset()
    accepted_strength_omission_slot_ids: dict[date, uuid.UUID] = dataclass_field(default_factory=dict)


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
    )


def is_quality_slot(kind: str, recipe_id: str | None, placeholder: bool) -> bool:
    return kind == "run" and (recipe_id in QUALITY_RECIPES or placeholder)


def scope(operation: str, today: date, review_date: date | None = None) -> tuple[date, date]:
    if operation in HORIZON_OPS:
        days = (review_date - today).days if review_date is not None else HORIZON_MIN_DAYS
        return today, today + timedelta(days=min(max(days, HORIZON_MIN_DAYS), HORIZON_MAX_DAYS))
    days = 3 if operation == "proceed_or_modify_today" else 6 if operation in PATCH_SCOPE_OPS else 13
    return today, today + timedelta(days=days)


def derive_certainty(day: date, today: date) -> str:
    return "committed" if day <= today + timedelta(days=6) else "provisional"


def anchor_key(item: AnchorChange, tz: ZoneInfo) -> str:
    return f"{item.kind}-{date_in_zone(item.calibrated_at, tz).isoformat()}"


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
