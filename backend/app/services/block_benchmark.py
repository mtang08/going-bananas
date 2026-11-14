"""Block-ending benchmark status (D16): one status function, four statuses."""
from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.domain.session_class import RECIPE_CLASS
from app.planning_models import BlockVersion

BenchmarkOutcome = Literal['progress', 'consolidate', 'recalibrate_only', 'inconclusive']
BenchmarkStatusValue = Literal['not_set', 'pending', 'completed', 'missed']
MatchMethod = Literal['auto', 'manual']
AUTO_BEFORE_DAYS = 3
AUTO_AFTER_DAYS = 7
PENDING_GRACE_DAYS = 2
ACTIVE_STATUSES = ('active', 'consolidating')
RUN_SPORTS = ('running', 'trail_running', 'treadmill_running')
BENCHMARK_RECIPES = frozenset(r for r, c in RECIPE_CLASS.items() if c == 'benchmark')


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
    latest = select(BlockVersion.block_uid, func.max(BlockVersion.version).label('version'))\
        .group_by(BlockVersion.block_uid).subquery()
    return session.scalar(select(BlockVersion).join(latest,
        (BlockVersion.block_uid == latest.c.block_uid) & (BlockVersion.version == latest.c.version))
        .where(BlockVersion.status.in_(ACTIVE_STATUSES))
        .order_by(desc(BlockVersion.created_at), desc(BlockVersion.version), desc(BlockVersion.id)).limit(1))


def benchmark_spec(version: Any) -> BenchmarkSpec | None:
    data = version.benchmark
    if not data:
        return None
    return BenchmarkSpec(kind=data['kind'],
                         event_id=uuid.UUID(data['event_id']) if data.get('event_id') else None,
                         protocol=data['protocol'], distance_m=data.get('distance_m'),
                         planned_date=date.fromisoformat(data['planned_date']))


def _decide(spec: BenchmarkSpec | None, review_date: date, today: date, manual: MatchFact | None,
            auto: MatchFact | None, scheduled_date: date | None) -> BenchmarkStatus:
    if spec is None:
        return BenchmarkStatus('not_set', None, None, None, None, None, None, None, None, None)
    method: MatchMethod = 'manual' if manual is not None else 'auto'
    match = manual if manual is not None else auto
    if match is not None:
        return BenchmarkStatus('completed', method, match.activity_id, spec.event_id, match.local_date,
                               match.distance_m, match.result_s, match.rpe, scheduled_date, match.end_at)
    status: BenchmarkStatusValue = 'pending' if today <= review_date + timedelta(days=PENDING_GRACE_DAYS) else 'missed'
    return BenchmarkStatus(status, None, None, spec.event_id, None, None, None, None, scheduled_date, None)


def status_data(status: BenchmarkStatus) -> dict[str, Any]:
    return dataclasses.asdict(status)
