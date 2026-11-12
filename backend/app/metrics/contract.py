from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    available = 'available'
    partial = 'partial'
    missing = 'missing'
    invalid = 'invalid'
    not_applicable = 'not_applicable'
    not_assessable = 'not_assessable'


class QualityStatus(StrEnum):
    good = 'good'
    limited = 'limited'
    insufficient = 'insufficient'


@dataclass(frozen=True)
class MetricResultData:
    metric_id: str
    method_version: str
    subject_type: str
    subject_key: str
    status: Status
    reason_codes: tuple[str, ...]
    quality_flags: tuple[str, ...]
    source_refs: dict[str, Any]
    anchor_keys: tuple[str, ...]
    config_hash: str
    window_start: datetime | None = None
    window_end: datetime | None = None
    window_label: str | None = None
    quality_status: QualityStatus | None = None
    value: Any | None = None
    unit: str | None = None
    anchor_set_hash: str | None = None
    calculated_at: datetime | None = None
    dependency_hash: str = ''
    timezone: str = ''


MetricResult = MetricResultData


@dataclass(frozen=True)
class RunFact:
    activity_id: uuid.UUID
    start_at: datetime
    end_at: datetime | None
    local_date: date
    sport: str
    timer_s: float | None
    distance_m: float | None
    workout_label: str | None
    source_refs: dict[str, Any] = field(default_factory=dict)
    source_revision: str = ''


def metric_source_refs(session: Any, activity_id: uuid.UUID,
                       session_uid: uuid.UUID | None = None,
                       calendar_version: int | None = None) -> dict[str, Any]:
    from app.metrics.engine import metric_source_refs as _metric_source_refs
    return _metric_source_refs(session, activity_id, session_uid, calendar_version)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False, default=_json_default)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('naive_datetime')
        return value.astimezone(UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, 'hex'):
        return str(value)
    raise TypeError(f'not JSON serializable: {type(value).__name__}')


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def config_hash(config: Mapping[str, Any]) -> str:
    return sha256_json(dict(config))


def coverage_label(valid_s: float, eligible_s: float) -> QualityStatus | None:
    if not all(math.isfinite(v) and v >= 0 for v in (valid_s, eligible_s)):
        raise ValueError('invalid_coverage')
    if eligible_s <= 0:
        return None
    ratio = valid_s / eligible_s
    if ratio >= 0.9:
        return QualityStatus.good
    if ratio >= 0.7:
        return QualityStatus.limited
    return QualityStatus.insufficient


def rolling_window(today: date, n: int) -> tuple[date, date]:
    if n <= 0:
        raise ValueError('invalid_window')
    return today - timedelta(days=n - 1), today


def plausible_hr(v: float | None) -> bool:
    return v is not None and math.isfinite(v) and 30 <= v <= 230


def plausible_speed(v: float | None) -> bool:
    return v is not None and math.isfinite(v) and 0 <= v <= 10


def integrate_timer_on(t_s: list[int], timer_on: list[tuple[float, float]],
                       max_gap_s: int) -> list[tuple[int | None, float, bool]]:
    if not isinstance(max_gap_s, int) or isinstance(max_gap_s, bool) or max_gap_s <= 0:
        raise ValueError('invalid_timer')
    if any(not isinstance(t, int) or isinstance(t, bool) or t < 0 for t in t_s):
        raise ValueError('invalid_stream_order')
    if any(b <= a for a, b in zip(t_s, t_s[1:])):
        raise ValueError('invalid_stream_order')
    intervals: list[tuple[float, float]] = []
    for interval in timer_on:
        if not isinstance(interval, (tuple, list)) or len(interval) != 2:
            raise ValueError('invalid_timer')
        start, end = interval
        if (isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end < start):
            raise ValueError('invalid_timer')
        if end == start:
            continue
        intervals.append((float(start), float(end)))
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = merged[-1][0], max(end, merged[-1][1])
        else:
            merged.append((start, end))
    pieces: list[tuple[int | None, float, bool]] = []
    for start, end in merged:
        cursor = start
        for i, (left, right) in enumerate(zip(t_s, t_s[1:])):
            if right <= cursor or left >= end:
                continue
            if cursor < left:
                lead_end = min(float(left), end)
                pieces.append((None, lead_end - cursor, False))
                cursor = lead_end
            if cursor >= end:
                break
            overlap_end = min(float(right), end)
            if overlap_end > cursor:
                known = right - left <= max_gap_s
                pieces.append((i, overlap_end - cursor, known))
                cursor = overlap_end
        if cursor < end:
            pieces.append((None, end - cursor, False))
    return pieces


def completion_association_hash(completion: Any) -> str:
    def get(name: str) -> Any:
        return completion.get(name) if isinstance(completion, Mapping) else getattr(completion, name, None)
    return sha256_json({key: str(get(key)) if get(key) is not None and key.endswith('_id') else get(key)
                        for key in ('session_uid', 'activity_id', 'strong_workout_id', 'manual_session_id',
                                    'match_method', 'modification_reason', 'reason_note', 'input_version')})
