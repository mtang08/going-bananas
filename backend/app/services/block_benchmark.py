"""Block-ending benchmark status (D16): one status function, four statuses."""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.calendar_models import SessionCompletion
from app.checkin_models import SessionRpe
from app.domain.local_time import date_in_zone
from app.domain.session_class import RECIPE_CLASS
from app.models import Activity
from app.planning_models import BlockBenchmarkResult, BlockVersion, Event
from app.read.calendar import head_version
from app.services.run_rpe import effective_run_rpe
from app.services.timezone import athlete_tz

BenchmarkOutcome = Literal["progress", "consolidate", "recalibrate_only", "inconclusive"]
BenchmarkStatusValue = Literal["not_set", "pending", "completed", "missed"]
MatchMethod = Literal["auto", "manual"]
AUTO_BEFORE_DAYS = 3
AUTO_AFTER_DAYS = 7
PENDING_GRACE_DAYS = 2
ACTIVE_STATUSES = ("active", "consolidating")
BENCHMARK_RECIPES = frozenset(r for r, c in RECIPE_CLASS.items() if c == "benchmark")


@dataclass(frozen=True)
class BenchmarkSpec:
    kind: str
    event_id: uuid.UUID | None
    protocol: str
    distance_m: int | None
    planned_date: date


@dataclass(frozen=True)
class MatchFact:
    activity_id: uuid.UUID
    local_date: date
    distance_m: int | None
    result_s: int | None
    rpe: float | None
    end_at: datetime


@dataclass(frozen=True)
class BenchmarkStatus:
    status: BenchmarkStatusValue
    match_method: MatchMethod | None
    activity_id: uuid.UUID | None
    event_id: uuid.UUID | None
    local_date: date | None
    distance_m: int | None
    result_s: int | None
    rpe: float | None
    scheduled_date: date | None
    evidence_at: datetime | None


def active_block_version(session: Session) -> BlockVersion | None:
    latest = (
        select(BlockVersion.block_uid, func.max(BlockVersion.version).label("version"))
        .group_by(BlockVersion.block_uid)
        .subquery()
    )
    return session.scalar(
        select(BlockVersion)
        .join(latest, (BlockVersion.block_uid == latest.c.block_uid) & (BlockVersion.version == latest.c.version))
        .where(BlockVersion.status.in_(ACTIVE_STATUSES))
        .order_by(desc(BlockVersion.created_at), desc(BlockVersion.version), desc(BlockVersion.id))
        .limit(1)
    )


def benchmark_spec(version: Any) -> BenchmarkSpec | None:
    data = version.benchmark
    if not data:
        return None
    return BenchmarkSpec(
        kind=data["kind"],
        event_id=uuid.UUID(data["event_id"]) if data.get("event_id") else None,
        protocol=data["protocol"],
        distance_m=data.get("distance_m"),
        planned_date=date.fromisoformat(data["planned_date"]),
    )


def _decide(
    spec: BenchmarkSpec | None,
    review_date: date,
    today: date,
    manual: MatchFact | None,
    auto: MatchFact | None,
    scheduled_date: date | None,
) -> BenchmarkStatus:
    if spec is None:
        return BenchmarkStatus("not_set", None, None, None, None, None, None, None, None, None)
    method: MatchMethod = "manual" if manual is not None else "auto"
    match = manual if manual is not None else auto
    if match is not None:
        return BenchmarkStatus(
            "completed",
            method,
            match.activity_id,
            spec.event_id,
            match.local_date,
            match.distance_m,
            match.result_s,
            match.rpe,
            scheduled_date,
            match.end_at,
        )
    status: BenchmarkStatusValue = "pending" if today <= review_date + timedelta(days=PENDING_GRACE_DAYS) else "missed"
    return BenchmarkStatus(status, None, None, spec.event_id, None, None, None, None, scheduled_date, None)


def _match(
    session: Session, activity_id: uuid.UUID, tz: ZoneInfo, result_override: int | None = None
) -> MatchFact | None:
    activity = session.get(Activity, activity_id)
    if activity is None:
        return None
    rpe = effective_run_rpe(
        session.scalars(select(SessionRpe).where(SessionRpe.activity_id == activity_id)).all(), activity.workout_rpe
    )[0]
    return MatchFact(
        activity_id=activity.id,
        local_date=date_in_zone(activity.start_at, tz),
        distance_m=round(activity.distance_m) if activity.distance_m is not None else None,
        result_s=result_override
        if result_override is not None
        else (round(activity.timer_s) if activity.timer_s is not None else None),
        rpe=rpe,
        end_at=activity.end_at or activity.start_at,
    )


def benchmark_status(session: Session, block_version: BlockVersion, today: date) -> BenchmarkStatus:
    from app.metrics.engine import load_runs
    from app.services.calendar import state_at

    spec = benchmark_spec(block_version)
    if spec is None:
        return _decide(None, block_version.review_date, today, None, None, None)
    tz = athlete_tz(session)
    row = session.scalar(
        select(BlockBenchmarkResult).where(
            BlockBenchmarkResult.block_uid == block_version.block_uid,
            BlockBenchmarkResult.block_version == block_version.version,
        )
    )
    manual = (
        _match(session, row.activity_id, tz)
        if row is not None and row.match_method == "manual" and row.activity_id
        else None
    )
    first = spec.planned_date - timedelta(days=AUTO_BEFORE_DAYS)
    last = block_version.review_date + timedelta(days=AUTO_AFTER_DAYS)
    head = head_version(session)
    bench = sorted(
        [
            r
            for r in state_at(session, head)
            if r["kind"] == "run" and r["recipe_id"] in BENCHMARK_RECIPES and first <= r["local_date"] <= last
        ],
        key=lambda r: (r["local_date"], str(r["session_uid"])),
    )
    scheduled_date = bench[-1]["local_date"] if bench else None
    auto: MatchFact | None = None
    if manual is None and spec.kind == "event":
        event = session.get(Event, spec.event_id) if spec.event_id else None
        if event is not None and first <= event.event_date <= last:
            runs = load_runs(session, event.event_date, event.event_date + timedelta(days=1))
            best = max(runs, key=lambda r: (r.distance_m or 0, r.start_at), default=None)
            if best is not None:
                auto = _match(session, best.activity_id, tz, result_override=event.result_s)
    elif manual is None and spec.kind == "time_trial" and bench:
        completions = {
            c.session_uid: c
            for c in session.scalars(
                select(SessionCompletion).where(
                    SessionCompletion.session_uid.in_([r["session_uid"] for r in bench]),
                    SessionCompletion.activity_id.is_not(None),
                )
            )
        }
        for r in reversed(bench):
            completion = completions.get(r["session_uid"])
            if completion is not None and completion.activity_id is not None:
                auto = _match(session, completion.activity_id, tz)
                break
    return _decide(spec, block_version.review_date, today, manual, auto, scheduled_date)


def status_data(status: BenchmarkStatus) -> dict[str, Any]:
    return dataclasses.asdict(status)
