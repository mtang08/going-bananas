"""Plain-value inputs of the exception detector and its candidate output."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.domain.session_class import SessionClass
from app.services.exceptions.vocab import Category, Severity


@dataclass(frozen=True)
class SymptomFact:
    id: str
    site: str
    side: str
    severity: float
    timing: str

    @property
    def site_key(self) -> str:
        return f"{self.site.strip().lower()}|{self.side}"


@dataclass(frozen=True)
class CheckinFact:
    id: str
    kind: str
    observed_at: datetime
    recorded_at: datetime
    local_date: date
    fatigue: float | None
    illness: str | None
    gait_change: str | None
    context_tags: tuple[str, ...]
    activity_id: str | None
    linked_activity_id: str | None
    symptoms: tuple[SymptomFact, ...]


@dataclass(frozen=True)
class RpeRun:
    activity_id: str
    local_date: date
    start_at: datetime
    end_at: datetime | None
    rpe: float | None
    rpe_source: str | None
    rpe_at: datetime | None
    session_uid: str | None


@dataclass(frozen=True)
class SessionFact:
    session_uid: str
    local_date: date
    kind: str
    recipe_id: str | None
    intent: str
    certainty: str
    session_class: SessionClass
    expected_rpe: tuple[float, float] | None
    completion_status: str | None
    modification_reason: str | None
    activity_id: str | None
    planned_at: datetime
    completion_updated_at: datetime | None


@dataclass(frozen=True)
class PlannedActualFact:
    reason_codes: tuple[str, ...]
    target_coverage: str | None


@dataclass(frozen=True)
class EventFact:
    id: str
    name: str
    event_date: date
    purpose: str
    status: str
    has_run_on_date: bool
    run_end_at: datetime | None


@dataclass(frozen=True)
class BlockBenchmarkFact:
    block_uid: str
    version: int
    version_created_at: datetime
    planned_date: date | None
    review_date: date
    kind: str | None
    event_id: str | None
    status: str
    activity_id: str | None
    local_date: date | None
    evidence_at: datetime | None
    protocol: str | None = None
    match_method: str | None = None
    distance_m: int | None = None
    result_s: int | None = None
    rpe: float | None = None


@dataclass(frozen=True)
class DetectionInputs:
    today: date
    now: datetime
    tz: str
    checkins: tuple[CheckinFact, ...] = ()
    runs: tuple[RpeRun, ...] = ()
    sessions: tuple[SessionFact, ...] = ()
    planned_actual: Mapping[str, PlannedActualFact] = field(default_factory=dict)
    recovery_adverse_dates: frozenset[date] = frozenset()
    events: tuple[EventFact, ...] = ()
    block_benchmark: BlockBenchmarkFact | None = None
    clinician_restriction: str | None = None
    clinician_restriction_at: datetime | None = None


@dataclass(frozen=True)
class Candidate:
    rule_code: str
    category: Category
    severity: Severity
    entity_key: str
    evidence_at: datetime
    evidence: list[dict[str, Any]]
    summary: str
