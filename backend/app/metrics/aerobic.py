"""Descriptive aerobic efficiency (EF) and HR drift on steady runs; never a fitness score."""
from __future__ import annotations

import math
import re
import statistics
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.domain.analytics import utc_date_bounds
from app.domain.session_class import classify
from app.fit_models import ActivityStream, ActivityWorkoutStep
from app.metrics.contract import (
    MetricResultData,
    QualityStatus,
    Status,
    config_hash,
    coverage_label,
    integrate_timer_on,
    metric_source_refs,
    plausible_hr,
    plausible_speed,
    sha256_json,
)
from app.metrics.engine import activities_coverage_complete, latest_results, load_runs, register
from app.metrics.intervals import FitStep, after_timer_seconds, expand_fit
from app.models import Activity, ActivityAnnotation, AppState
from app.services.calendar_structure import expand_structure
from app.services.timezone import athlete_tz, local_date

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


_NO_ELEVATION: dict[str, Any] = {'status': Status.missing.value, 'gain_m': None, 'loss_m': None,
                 'gain_m_per_km': None, 'half_grade_diff_pct': None}


def smoothed(t_s: list[int], values: list[float | None], half_window_s: float) -> list[float | None]:
    result: list[float | None] = []
    lo = hi = 0
    total, count = 0.0, 0
    for t in t_s:
        while hi < len(t_s) and t_s[hi] <= t + half_window_s:
            v = values[hi] if hi < len(values) else None
            if v is not None and math.isfinite(v):
                total, count = total + v, count + 1
            hi += 1
        while t_s[lo] < t - half_window_s:
            v = values[lo] if lo < len(values) else None
            if v is not None and math.isfinite(v):
                total, count = total - v, count - 1
            lo += 1
        result.append(total / count if count else None)
    return result


def elevation_summary(t_s: list[int], altitude_m: list[float | None], samples: list[Sample]) -> dict[str, Any]:
    cadence = CONFIG['altitude_smoothing_s']
    smooth = smoothed(t_s, altitude_m, cadence / 2)
    points: list[tuple[bool, float]] = []
    next_at = elapsed = 0.0
    meters = {True: 0.0, False: 0.0}
    for sample in samples:
        if sample.speed is not None and not _stopped(sample):
            meters[sample.first_half] += sample.speed * sample.seconds
        level = smooth[sample.index] if sample.index is not None else None
        elapsed += sample.seconds
        while next_at < elapsed:
            if level is not None:
                points.append((sample.first_half, level))
            next_at += cadence
    distance = meters[True] + meters[False]
    if len(points) < 2 or distance <= 0:
        return dict(_NO_ELEVATION)
    gain = sum(max(0.0, b - a) for (_, a), (_, b) in zip(points, points[1:]))
    loss = sum(max(0.0, a - b) for (_, a), (_, b) in zip(points, points[1:]))
    grades: list[float] = []
    for half in (True, False):
        levels = [level for first, level in points if first == half]
        if len(levels) < 2 or meters[half] <= 0:
            grades = []
            break
        grades.append(100 * (levels[-1] - levels[0]) / meters[half])
    return {'status': Status.available.value, 'gain_m': gain, 'loss_m': loss,
            'gain_m_per_km': 1000 * gain / distance,
            'half_grade_diff_pct': grades[1] - grades[0] if grades else None}


def aerobic_outcome(stream: AeroStream | None, *, treadmill: bool = False) -> dict[str, Any]:
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
        index = i if known else None
        first_seconds = min(seconds, max(0.0, midpoint - elapsed))
        if first_seconds:
            samples.append(Sample(index, first_seconds, True, speed, hr))
        if seconds > first_seconds:
            samples.append(Sample(index, seconds - first_seconds, False, speed, hr))
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
    elevation = (dict(_NO_ELEVATION, status=Status.not_applicable.value) if treadmill
                 else elevation_summary(stream.t_s, stream.altitude_m, samples))
    decoupling = _decoupling(moving, analysis_s)
    diff = elevation['half_grade_diff_pct']
    if decoupling['pct'] is not None and diff is not None and abs(diff) > CONFIG['half_grade_diff_max_pct']:
        decoupling.update(status=Status.not_assessable.value, reason_codes=['HALF_GRADE_DIFFERS'], pct=None)
    flags += ['TREADMILL'] if treadmill else []
    flags += ['ELEVATION_UNKNOWN'] if elevation['status'] == Status.missing.value else []
    gain_per_km = elevation['gain_m_per_km']
    flags += ['HILLY_ROUTE'] if gain_per_km is not None and gain_per_km > CONFIG['hilly_gain_m_per_km'] else []
    for key, places in (('gain_m', 1), ('loss_m', 1), ('gain_m_per_km', 2), ('half_grade_diff_pct', 2)):
        if elevation[key] is not None:
            elevation[key] = round(elevation[key], places)
    value = {'analysis_s': round(analysis_s, 1), 'moving_s': round(moving_s, 1),
             'paired_s': round(paired_s, 1), 'stopped_s': round(stopped_s, 1),
             'coverage': round(paired_s / moving_s, 3), 'mean_speed_mps': round(speed, 3),
             'mean_hr_bpm': round(hr, 1), 'ef_m_per_beat': round(60 * speed / hr, 3),
             'speed_cv_pct': round(cv, 2) if cv is not None else None, 'pauses_trimmed': pauses_trimmed,
             'decoupling': decoupling, 'elevation': elevation}
    return {'status': (Status.available if quality == QualityStatus.good else Status.partial).value,
            'quality_status': quality.value, 'value': value,
            'reason_codes': [] if quality == QualityStatus.good else ['LOW_COVERAGE'],
            'quality_flags': sorted(flags)}


RUN_SPORTS = ('running', 'trail_running', 'treadmill_running')


def run_class(plan: dict | None, watch_work_steps: int, label: str | None) -> tuple[str, str | None]:
    """Return (session_class, not_applicable_reason or None) per D11."""
    if plan is not None:
        structure = plan.get('structure')
        work = sum(step['type'] == 'work' for step in expand_structure(structure)) if structure else 0
        if work >= CONFIG['structured_min_work_steps']:
            return 'structured', 'STRUCTURED_SESSION'
        cls = classify('run', plan.get('recipe_id'), plan.get('intent'))
        if cls in ('easy', 'long'):
            return cls, None
        if cls != 'unknown':
            return cls, 'NOT_EASY_OR_LONG'
    if label in ('easy', 'long'):
        return label, None
    if label in ('quality', 'other'):
        return label, 'NOT_EASY_OR_LONG'
    if watch_work_steps >= CONFIG['structured_min_work_steps']:
        return 'structured', 'STRUCTURED_SESSION'
    return 'unplanned', None


def _watch_work_steps(session: Session, activity_id: uuid.UUID) -> int:
    rows = session.scalars(select(ActivityWorkoutStep).where(ActivityWorkoutStep.activity_id == activity_id)
                           .order_by(ActivityWorkoutStep.message_index)).all()
    if not rows:
        return 0
    try:
        expanded = expand_fit([FitStep(r.message_index, r.duration_type, r.intensity, r.duration_value,
                                       r.target_type, r.target_low, r.target_high, r.repeat_from, r.repeat_count)
                               for r in rows])
    except ValueError:
        return CONFIG['structured_min_work_steps']  # unreadable repeat: treat as structured
    return sum(step.intensity in ('active', 'interval') for step in expanded)


def _result(subject_type: str, key: str, outcome: dict, refs: dict, tz: str, label: str,
            start=None, end=None) -> MetricResultData:
    return MetricResultData(METRIC_ID, METHOD_VERSION, subject_type, key, Status(outcome['status']),
                            tuple(outcome['reason_codes']), tuple(outcome['quality_flags']), refs, (),
                            config_hash(CONFIG), window_start=start, window_end=end, window_label=label,
                            quality_status=QualityStatus(outcome['quality_status']) if outcome['quality_status'] else None,
                            value=outcome['value'], unit='m_per_beat', timezone=tz)


def window_outcome(entries: list[dict], start: date, days: int, coverage_complete: bool) -> dict[str, Any]:
    counted: list[dict] = []
    not_counted: dict[str, int] = {}
    for entry in entries:
        result = entry['result']
        if result is None:
            key = 'NO_RESULT'
        elif result['status'] in ('available', 'partial') and result['value'] is not None:
            if not set(result['quality_flags']) & set(CONFIG['window_excluded_flags']):
                counted.append(entry)
                continue
            key = next(f for f in CONFIG['window_excluded_flags'] if f in result['quality_flags'])
        else:
            key = (list(result['reason_codes']) or [str(result['status']).upper()])[0]
        not_counted[key] = not_counted.get(key, 0) + 1
    points = [{'activity_id': e['activity_id'], 'local_date': e['local_date'].isoformat(),
               'session_class': e['result']['value'].get('session_class'),
               'ef_m_per_beat': e['result']['value']['ef_m_per_beat'],
               'mean_speed_mps': e['result']['value']['mean_speed_mps'],
               'mean_hr_bpm': e['result']['value']['mean_hr_bpm'],
               'decoupling_pct': e['result']['value']['decoupling']['pct'],
               'quality_flags': list(e['result']['quality_flags'])}
              for e in sorted(counted, key=lambda e: (e['local_date'], e['activity_id']))]
    middle = (start + timedelta(days=days // 2)).isoformat()
    efs = [p['ef_m_per_beat'] for p in points]
    early = [p['ef_m_per_beat'] for p in points if p['local_date'] < middle]
    late = [p['ef_m_per_beat'] for p in points if p['local_date'] >= middle]
    decs = [p['decoupling_pct'] for p in points if p['decoupling_pct'] is not None]
    enough = min(len(early), len(late)) >= CONFIG['trend_min_runs_per_half']
    value = {'window_days': days, 'runs_total': len(entries), 'runs_counted': len(points),
             'runs_without_result': not_counted.get('NO_RESULT', 0),
             'not_counted': dict(sorted(not_counted.items())),
             'ef_median_m_per_beat': round(median(efs), 3) if efs else None,
             'ef_early_median_m_per_beat': round(median(early), 3) if early else None,
             'ef_late_median_m_per_beat': round(median(late), 3) if late else None,
             'ef_change_pct': round(100 * (median(late) - median(early)) / median(early), 2) if enough else None,
             'decoupling_runs_counted': len(decs),
             'decoupling_median_pct': round(median(decs), 2) if decs else None,
             'points': points}
    reasons: list[str] = []
    if not points:
        status = Status.not_assessable.value
        reasons.append('NO_ELIGIBLE_RUNS')
    else:
        if value['runs_without_result']:
            reasons.append('ACTIVITY_RESULT_MISSING')
        status = (Status.partial if reasons or not coverage_complete else Status.available).value
    if not coverage_complete:
        reasons.append('SYNC_COVERAGE_INCOMPLETE')
    return {'status': status, 'quality_status': None, 'value': value, 'reason_codes': reasons,
            'quality_flags': ['TREND_TOO_FEW_RUNS'] if points and not enough else []}


def _window(session: Session, subject_key: str, tz) -> MetricResultData:
    match = re.fullmatch(r'w(\d+):(\d{4}-\d{2}-\d{2})', subject_key)
    if match is None or int(match[1]) not in WINDOW_DAYS:
        raise ValueError('invalid_subject_key')
    days, as_of = int(match[1]), date.fromisoformat(match[2])
    first = as_of - timedelta(days=days - 1)
    runs = load_runs(session, first, as_of + timedelta(days=1))
    keys = [str(run.activity_id) for run in runs]
    rows = latest_results(session, METRIC_ID, METHOD_VERSION, keys)
    entries = [{'activity_id': key, 'local_date': run.local_date,
                'result': {'status': rows[key].status, 'reason_codes': rows[key].reason_codes,
                           'quality_flags': rows[key].quality_flags, 'value': rows[key].value}
                if key in rows else None} for key, run in zip(keys, runs)]
    coverage = activities_coverage_complete(session, first, as_of + timedelta(days=1))
    sources = [{'activity_id': key, 'source_revision': run.source_revision,
                'metric_result_id': str(rows[key].id) if key in rows else None,
                'metric_dependency_hash': rows[key].dependency_hash if key in rows else None}
               for key, run in zip(keys, runs)]
    refs = {'activity_ids': keys, 'sources': sources, 'coverage_complete': coverage,
            'input_hash': sha256_json({'sources': sources, 'coverage_complete': coverage})}
    start, end = utc_date_bounds(first, as_of, tz.key)
    return _result('window', subject_key, window_outcome(entries, first, days, coverage), refs, tz.key,
                   subject_key, start, end)


@register(METRIC_ID, METHOD_VERSION, DEPENDS_ON)
def compute(session: Session, subject_key: str) -> list[MetricResultData]:
    tz = athlete_tz(session)
    if subject_key.startswith('w'):
        return [_window(session, subject_key, tz)]
    try:
        activity_id = uuid.UUID(subject_key)
    except ValueError as exc:
        raise ValueError('invalid_subject_key') from exc
    activity = session.get(Activity, activity_id)
    if activity is None or activity.sport not in RUN_SPORTS:
        return []
    annotation = session.scalar(select(ActivityAnnotation).where(ActivityAnnotation.activity_id == activity_id)
                                .order_by(ActivityAnnotation.version.desc()).limit(1))
    state = session.get(AppState, 1)
    head = state.calendar_head_version if state else 0
    completion = session.scalar(select(SessionCompletion).where(SessionCompletion.activity_id == activity_id))
    session_uid = completion.session_uid if completion else None
    revision = session.scalar(select(CalendarSessionRevision).where(
        CalendarSessionRevision.session_uid == session_uid,
        CalendarSessionRevision.calendar_version_number <= head)
        .order_by(CalendarSessionRevision.calendar_version_number.desc()).limit(1)) if session_uid and head else None
    plan = ({'recipe_id': revision.recipe_id, 'intent': revision.intent, 'structure': revision.structure}
            if revision and not revision.deleted and revision.kind == 'run' else None)
    refs = metric_source_refs(session, activity_id, session_uid, head)
    day = local_date(activity.start_at, tz)
    cls: str | None = None
    if (annotation and annotation.excluded) or activity.resolution_state != 'resolved':
        outcome = _early(Status.not_applicable, 'ACTIVITY_EXCLUDED')
    else:
        cls, ineligible = run_class(plan, _watch_work_steps(session, activity_id),
                                    annotation.workout_label if annotation else None)
        if ineligible:
            outcome = _early(Status.not_applicable, ineligible)
        else:
            row = session.get(ActivityStream, activity_id)
            stream = AeroStream(row.t_s, row.hr_bpm, row.speed_mps, row.altitude_m,
                                [tuple(pair) for pair in row.timer_on], tuple(row.quality_flags)) if row else None
            outcome = aerobic_outcome(stream, treadmill=activity.sport == 'treadmill_running')
    if outcome['value'] is not None:
        outcome['value'].update(activity_id=str(activity_id), local_date=day.isoformat(),
                                sport=activity.sport, session_class=cls)
    return [_result('activity', subject_key, outcome, refs, tz.key, day.isoformat(),
                    activity.start_at, activity.end_at)]
