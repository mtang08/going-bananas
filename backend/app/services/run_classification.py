"""Read-only, past-only suggestions for historical run labels.

Whole-run averages cannot reveal intervals, heart-rate drift, or intent. The
suggestion remains provisional; an athlete annotation and source label win.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import isfinite
from statistics import median
from typing import Any

from app.domain.analytics import RUN_SPORTS

METHOD = 'historical_relative_v1'
WINDOW_DAYS = 84
MIN_PRIOR = 6
MIN_HR = 4
LABELS = {'easy', 'quality', 'long', 'other'}
LIMITATION = (
    'Whole-run averages do not show intervals or heart-rate drift; route, weather, '
    'effort, and sensor differences are unmeasured.'
)


@dataclass(frozen=True)
class RunObservation:
    id: str
    local_date: date
    start_at: datetime
    sport: str
    distance_m: float | None = None
    elapsed_s: float | None = None
    moving_s: float | None = None
    avg_hr_bpm: float | None = None
    manual_label: str | None = None
    source_label: str | None = None
    excluded: bool = False
    resolution_state: str = 'resolved'


def _positive(value: float | None) -> float | None:
    if value is None or not isfinite(value) or value <= 0:
        return None
    return value


def _pace(row: RunObservation) -> float | None:
    distance = _positive(row.distance_m)
    moving = _positive(row.moving_s)
    return moving / distance if distance is not None and moving is not None else None


def _median(values: list[float], minimum: int) -> float | None:
    return median(values) if len(values) >= minimum else None


def _ratio(value: float | None, baseline: float | None) -> float | None:
    return round(value / baseline, 3) if value is not None and baseline is not None and baseline > 0 else None


def _eligible(row: RunObservation) -> bool:
    return row.sport in RUN_SPORTS and not row.excluded and row.resolution_state == 'resolved'


def classify_history(
    runs: list[RunObservation], *, long_run_weekdays: tuple[int, ...] = (5, 6)
) -> dict[str, dict[str, Any]]:
    """Classify each run using only earlier resolved runs in the preceding 12 weeks.

    A weekend long suggestion needs relative distance and duration; average HR
    supplies a separate effort signal. Quality/easy suggestions require agreeing
    relative average-HR and moving-pace evidence. No absolute HR zones or
    training targets are inferred. Unsupported records remain unknown.
    """
    if len(runs) > 10_000:
        raise ValueError('too_many_runs')
    if len({row.id for row in runs}) != len(runs):
        raise ValueError('duplicate_run_id')
    if not long_run_weekdays or any(day not in range(7) for day in long_run_weekdays):
        raise ValueError('invalid_long_run_weekdays')
    ordered = sorted(runs, key=lambda row: (row.start_at, row.id))
    result: dict[str, dict[str, Any]] = {}
    for row in ordered:
        if not _eligible(row):
            continue
        prior = [candidate for candidate in ordered if _eligible(candidate)
                 and row.start_at - timedelta(days=WINDOW_DAYS) <= candidate.start_at < row.start_at]
        durations = [value for candidate in prior if (value := _positive(candidate.elapsed_s)) is not None]
        distances = [value for candidate in prior if (value := _positive(candidate.distance_m)) is not None]
        paces = [value for candidate in prior if (value := _pace(candidate)) is not None]
        heart_rates = [value for candidate in prior if (value := _positive(candidate.avg_hr_bpm)) is not None]
        duration_ratio = _ratio(_positive(row.elapsed_s), _median(durations, MIN_PRIOR))
        distance_ratio = _ratio(_positive(row.distance_m), _median(distances, MIN_PRIOR))
        pace_ratio = _ratio(_pace(row), _median(paces, MIN_HR))
        hr_ratio = _ratio(_positive(row.avg_hr_bpm), _median(heart_rates, MIN_HR))
        effort_signal = 'unavailable'
        if hr_ratio is not None:
            effort_signal = 'higher_average_hr' if hr_ratio >= 1.08 else (
                'lower_average_hr' if hr_ratio <= 0.93 else 'similar_average_hr'
            )
        metrics = {
            'window_days': WINDOW_DAYS, 'prior_runs': len(prior),
            'duration_samples': len(durations), 'distance_samples': len(distances),
            'pace_samples': len(paces), 'average_hr_samples': len(heart_rates),
            'relative_duration': duration_ratio, 'relative_distance': distance_ratio,
            'relative_moving_pace': pace_ratio, 'relative_average_hr': hr_ratio,
            'effort_signal': effort_signal,
        }
        suggested: str | None = None
        confidence = 'insufficient'
        reasons: list[str] = []
        manual = row.manual_label if row.manual_label in LABELS else None
        source = row.source_label if row.source_label in LABELS else None
        if manual:
            label, origin, confidence = manual, 'manual', 'confirmed'
            reasons.append('Athlete correction takes precedence over source and relative suggestion.')
        elif source:
            label, origin, confidence = source, 'source', 'confirmed'
            reasons.append('Explicit source workout label takes precedence over relative suggestion.')
        else:
            if len(prior) < MIN_PRIOR:
                reasons.append('Fewer than six earlier runs in the preceding 12 weeks.')
            elif (row.local_date.weekday() in long_run_weekdays
                  and duration_ratio is not None and distance_ratio is not None
                  and row.elapsed_s is not None and row.elapsed_s >= 45 * 60
                  and duration_ratio >= 1.25 and distance_ratio >= 1.2):
                suggested, confidence = 'long', 'medium'
                reasons.append('Weekend run is longer in both time and distance than recent personal runs.')
            elif hr_ratio is not None and pace_ratio is not None and hr_ratio >= 1.08 and pace_ratio <= 0.93:
                suggested, confidence = 'quality', 'low'
                reasons.append('Average heart rate is higher and moving pace faster than recent personal runs.')
            elif hr_ratio is not None and pace_ratio is not None and hr_ratio <= 0.98 and pace_ratio >= 0.97:
                suggested, confidence = 'easy', 'low'
                reasons.append('Average heart rate is lower and moving pace is not notably faster than recent personal runs.')
            else:
                reasons.append('Available relative measures do not jointly support a run-type suggestion.')
            label, origin = suggested or 'unknown', 'heuristic' if suggested else 'unknown'
        if row.local_date.weekday() not in long_run_weekdays and label == 'long':
            reasons.append('Explicit weekday long label is preserved; weekend restriction applies to suggestions.')
        if hr_ratio is None:
            reasons.append('Average heart rate is missing or lacks enough prior comparable values.')
        reasons.append(LIMITATION)
        result[row.id] = {
            'method': METHOD, 'suggested_label': suggested, 'effective_label': label,
            'label_source': origin, 'confidence': confidence, 'reasons': reasons,
            'metrics': metrics,
        }
    return result
