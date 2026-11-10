from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

RUN_SPORTS = {'running', 'trail_running', 'treadmill_running'}
LOW_IMPACT_SPORTS = {'cycling', 'elliptical', 'swimming', 'rowing', 'walking'}
LABELS = ('easy', 'quality', 'long', 'other', 'unknown')
METRIC_VERSION = 'analytics.v1'


@dataclass(frozen=True)
class ActivityFact:
    id: str
    local_date: date
    start_at: datetime
    sport: str
    distance_m: float | None = None
    elapsed_s: float | None = None
    moving_s: float | None = None
    workout_label: str | None = None
    excluded: bool = False
    resolution_state: str = 'resolved'


def pace_s_per_km(distance_m: float | None, moving_s: float | None) -> float | None:
    if distance_m is None or moving_s is None or distance_m <= 0 or moving_s <= 0:
        return None
    if not isfinite(distance_m) or not isfinite(moving_s):
        raise ValueError('Non-finite measurement')
    return moving_s / (distance_m / 1000)


def utc_date_bounds(start_date: date, end_date: date, timezone_name: str) -> tuple[datetime, datetime]:
    if end_date < start_date:
        raise ValueError('Inverted date range')
    zone = ZoneInfo(timezone_name)
    start = datetime.combine(start_date, datetime.min.time(), zone).astimezone(UTC)
    end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), zone).astimezone(UTC)
    return start, end


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def aggregate(activities: list[ActivityFact], start_date: date, end_date: date) -> dict:
    selected = [a for a in activities if start_date <= a.local_date <= end_date and not a.excluded and a.resolution_state == 'resolved']
    runs = [a for a in selected if a.sport in RUN_SPORTS]
    strength = [a for a in selected if a.sport == 'strength']
    low = [a for a in selected if a.sport in LOW_IMPACT_SPORTS]
    dist = Counter({label: 0 for label in LABELS})
    for run in runs:
        label = run.workout_label if run.workout_label in LABELS else 'unknown'
        dist[label] += 1
    elapsed = [a.elapsed_s for a in runs if a.elapsed_s is not None]
    return {
        'distance_m': sum(a.distance_m for a in runs if a.distance_m is not None),
        'run_count': len(runs),
        'missing_distance_count': sum(a.distance_m is None for a in runs),
        'longest_elapsed_s': max(elapsed, default=None),
        'missing_elapsed_count': len(runs) - len(elapsed),
        'strength_count': len(strength),
        'strength_duration_s': sum(a.elapsed_s for a in strength if a.elapsed_s is not None),
        'strength_unknown_duration_count': sum(a.elapsed_s is None for a in strength),
        'low_impact_count': len(low),
        'low_impact_duration_s': sum(a.elapsed_s for a in low if a.elapsed_s is not None),
        'workout_distribution': dict(dist),
    }


def summary(activities: list[ActivityFact], as_of: date, days: int = 28) -> dict:
    if not 1 <= days <= 366:
        raise ValueError('days must be 1..366')
    start = as_of - timedelta(days=days-1)
    weekly = []
    cursor = week_start(start)
    while cursor <= as_of:
        values = aggregate(activities, max(cursor, start), min(cursor + timedelta(days=6), as_of))
        weekly.append({'start_date': cursor.isoformat(), 'end_date': (cursor+timedelta(days=6)).isoformat(), **values})
        cursor += timedelta(days=7)
    return {
        'metric_version': METRIC_VERSION,
        'as_of': as_of.isoformat(),
        'window': {'start_date': start.isoformat(), 'end_date': as_of.isoformat()},
        'current_week': aggregate(activities, week_start(as_of), as_of),
        'rolling_7': aggregate(activities, as_of-timedelta(days=6), as_of),
        'rolling_14': aggregate(activities, as_of-timedelta(days=13), as_of),
        'selected': aggregate(activities, start, as_of),
        'weekly': weekly,
    }


def trailing_mean(values: list[tuple[date, float]], as_of: date, days: int = 7) -> dict:
    included = [value for day, value in values if as_of-timedelta(days=days-1) <= day <= as_of]
    return {'mean': sum(included)/len(included) if included else None, 'n': len(included), 'days': days}
