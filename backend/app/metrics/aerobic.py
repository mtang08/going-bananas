"""Descriptive aerobic efficiency (EF) and HR drift on steady runs; never a fitness score."""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, cast

from app.metrics.contract import (
    QualityStatus,
    Status,
    coverage_label,
    integrate_timer_on,
    plausible_hr,
    plausible_speed,
)
from app.metrics.intervals import after_timer_seconds

METRIC_ID = 'aerobic_efficiency'
METHOD_VERSION = 'v1'
WINDOW_DAYS = (28, 84)
DEPENDS_ON: tuple[str, ...] = ()

CONFIG: dict[str, Any] = {
    'interpretation': 'descriptive_only.v1',
    'eligibility_rule': 'plan_class_then_label_then_watch.v1',
    'eligible_classes': ['easy', 'long', 'unplanned'],
    'structured_min_work_steps': 2,
    'max_record_gap_s': 10,
    'hr_valid_bpm': [30, 230],
    'speed_valid_mps': [0, 10],
    'moving_speed_min_mps': 1.5,
    'warmup_exclude_s': 600,
    'resume_exclude_s': 60,
    'min_analysis_s': 1200,
    'min_decoupling_analysis_s': 2400,
    'coverage_good': 0.9,
    'coverage_limited': 0.7,
    'stopped_max_fraction': 0.1,
    'steady_bin_s': 60,
    'steady_cv_max_pct': 15.0,
    'ef_rule': 'sixty_x_mean_speed_over_mean_hr.v1',
    'decoupling_rule': 'first_minus_second_over_first_equal_timer_halves.v1',
    'altitude_smoothing_s': 30,
    'hilly_gain_m_per_km': 15.0,
    'half_grade_diff_max_pct': 1.0,
    'window_rule': 'median_and_early_late_half_median.v1',
    'trend_min_runs_per_half': 3,
    'window_excluded_flags': ['TREADMILL'],
}

_TIMER_FLAGS = ('TIMER_EVENTS_MISSING', 'TIMER_EVENTS_AMBIGUOUS', 'TIMER_MISMATCH')


@dataclass(frozen=True)
class AeroStream:
    t_s: list[int]
    hr_bpm: list[float | None]
    speed_mps: list[float | None]
    altitude_m: list[float | None]
    timer_on: list[tuple[float, float]]
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Sample:
    index: int | None
    seconds: float
    first_half: bool
    speed: float | None
    hr: float | None


def _early(status: Status, reason: str) -> dict[str, Any]:
    return {'status': status.value, 'quality_status': None, 'value': None,
            'reason_codes': [reason], 'quality_flags': []}


def analysis_spans(timer_on: list[tuple[float, float]], warmup_s: float,
                   resume_s: float) -> list[tuple[float, float]]:
    spans, _ = _trimmed_spans(timer_on, warmup_s, resume_s)
    return spans


def _trimmed_spans(timer_on: list[tuple[float, float]], warmup_s: float,
                   resume_s: float) -> tuple[list[tuple[float, float]], int]:
    spans: list[tuple[float, float]] = []
    pauses_trimmed = 0
    for index, (start, end) in enumerate(after_timer_seconds(timer_on, 0)):
        warmup_used = min(warmup_s, end - start)
        warmup_s -= warmup_used
        analysis_start = start + warmup_used
        resume_end = min(start + resume_s, end)
        if index and analysis_start < resume_end:
            analysis_start = resume_end
            pauses_trimmed += 1
        if analysis_start < end:
            spans.append((analysis_start, end))
    return spans, pauses_trimmed


def _stopped(sample: Sample) -> bool:
    return sample.speed is not None and sample.speed < CONFIG['moving_speed_min_mps']


def _means(paired: list[Sample]) -> tuple[float, float]:
    weight = sum(s.seconds for s in paired)
    return (sum(cast(float, s.speed) * s.seconds for s in paired) / weight,
            sum(cast(float, s.hr) * s.seconds for s in paired) / weight)


def speed_cv_pct(paired: list[Sample], bin_s: float) -> float | None:
    assert bin_s > 0
    bins: list[float] = []
    total = weight = 0.0
    for sample in paired:
        speed = sample.speed
        assert speed is not None
        seconds = sample.seconds
        while seconds >= bin_s - weight:
            needed = bin_s - weight
            bins.append((total + speed * needed) / bin_s)
            seconds -= needed
            total = weight = 0.0
        total += speed * seconds
        weight += seconds
    if len(bins) < 2:
        return None
    return 100 * statistics.stdev(bins) / statistics.fmean(bins)


def _decoupling(moving: list[Sample], analysis_s: float) -> dict[str, Any]:
    result: dict[str, Any] = {'status': Status.not_assessable.value, 'reason_codes': [], 'pct': None,
                              'first_ef_m_per_beat': None, 'second_ef_m_per_beat': None,
                              'first_mean_hr_bpm': None, 'second_mean_hr_bpm': None,
                              'first_mean_speed_mps': None, 'second_mean_speed_mps': None,
                              'half_s': round(analysis_s / 2, 1)}
    if analysis_s < CONFIG['min_decoupling_analysis_s']:
        result['reason_codes'] = ['DECOUPLING_TOO_SHORT']
        return result
    efs: list[float] = []
    qualities: list[QualityStatus] = []
    for first, prefix in ((True, 'first'), (False, 'second')):
        half = [s for s in moving if s.first_half == first]
        paired = [s for s in half if s.speed is not None and s.hr is not None]
        quality = coverage_label(sum(s.seconds for s in paired), sum(s.seconds for s in half))
        if quality is None or quality == QualityStatus.insufficient:
            result['reason_codes'] = ['HALF_LOW_COVERAGE']
            return result
        speed, hr = _means(paired)
        efs.append(60 * speed / hr)
        qualities.append(quality)
        result.update({f'{prefix}_ef_m_per_beat': round(60 * speed / hr, 3),
                       f'{prefix}_mean_hr_bpm': round(hr, 1), f'{prefix}_mean_speed_mps': round(speed, 3)})
    limited = QualityStatus.limited in qualities
    result.update(status=(Status.partial if limited else Status.available).value,
                  reason_codes=['HALF_LOW_COVERAGE'] if limited else [],
                  pct=round(100 * (efs[0] - efs[1]) / efs[0], 2))
    return result


def aerobic_outcome(stream: AeroStream | None) -> dict[str, Any]:
    if stream is None:
        return _early(Status.not_assessable, 'NO_STREAM')
    timer_flags = [flag for flag in _TIMER_FLAGS if flag in stream.quality_flags]
    if timer_flags:
        return _early(Status.not_assessable, timer_flags[0])
    if all(v is None for v in stream.hr_bpm):
        return _early(Status.not_assessable, 'HR_NOT_RECORDED')
    if all(v is None for v in stream.speed_mps):
        return _early(Status.not_assessable, 'SPEED_NOT_RECORDED')
    spans, pauses_trimmed = _trimmed_spans(
        [(float(a), float(b)) for a, b in stream.timer_on],
        CONFIG['warmup_exclude_s'], CONFIG['resume_exclude_s'],
    )
    pieces = integrate_timer_on(stream.t_s, spans, CONFIG['max_record_gap_s']) if spans else []
    analysis_s = sum(seconds for _, seconds, _ in pieces)
    if analysis_s < CONFIG['min_analysis_s']:
        return _early(Status.not_assessable, 'TOO_SHORT')
    samples: list[Sample] = []
    elapsed = 0.0
    midpoint = analysis_s / 2
    for i, seconds, known in pieces:
        speed = stream.speed_mps[i] if known and i is not None and i < len(stream.speed_mps) else None
        hr = stream.hr_bpm[i] if known and i is not None and i < len(stream.hr_bpm) else None
        speed = speed if plausible_speed(speed) else None
        hr = hr if plausible_hr(hr) else None
        first_seconds = min(seconds, max(0.0, midpoint - elapsed))
        if first_seconds:
            samples.append(Sample(i, first_seconds, True, speed, hr))
        if seconds > first_seconds:
            samples.append(Sample(i, seconds - first_seconds, False, speed, hr))
        elapsed += seconds
    stopped_s = float(sum(s.seconds for s in samples if _stopped(s)))
    if stopped_s / analysis_s > CONFIG['stopped_max_fraction']:
        return _early(Status.not_assessable, 'TOO_MANY_STOPS')
    moving = [s for s in samples if not _stopped(s)]
    paired = [s for s in moving if s.speed is not None and s.hr is not None]
    moving_s = analysis_s - stopped_s
    paired_s = sum(s.seconds for s in paired)
    quality = coverage_label(paired_s, moving_s)
    if quality is None or quality == QualityStatus.insufficient:
        return _early(Status.not_assessable, 'LOW_COVERAGE')
    cv = speed_cv_pct(paired, CONFIG['steady_bin_s'])
    if cv is not None and cv > CONFIG['steady_cv_max_pct']:
        return _early(Status.not_assessable, 'PACE_NOT_STEADY')
    speed, hr = _means(paired)
    flags = (['STOPS_EXCLUDED'] if stopped_s else []) + (['PAUSES_TRIMMED'] if pauses_trimmed else [])
    value = {'analysis_s': round(analysis_s, 1), 'moving_s': round(moving_s, 1),
             'paired_s': round(paired_s, 1), 'stopped_s': round(stopped_s, 1),
             'coverage': round(paired_s / moving_s, 3), 'mean_speed_mps': round(speed, 3),
             'mean_hr_bpm': round(hr, 1), 'ef_m_per_beat': round(60 * speed / hr, 3),
             'speed_cv_pct': round(cv, 2) if cv is not None else None, 'pauses_trimmed': pauses_trimmed,
             'decoupling': _decoupling(moving, analysis_s)}
    return {'status': (Status.available if quality == QualityStatus.good else Status.partial).value,
            'quality_status': quality.value, 'value': value,
            'reason_codes': [] if quality == QualityStatus.good else ['LOW_COVERAGE'],
            'quality_flags': sorted(flags)}
