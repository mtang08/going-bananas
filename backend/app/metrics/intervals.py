"""Structured workout execution from a plan, watch steps, laps, and timer trace."""
from __future__ import annotations

import math
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypeGuard, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.config import settings
from app.fit_models import ActivityLap, ActivityStream, ActivityWorkoutStep
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
)
from app.metrics.engine import register
from app.models import Activity, ActivityAnnotation, ActivitySource, AppState, RawObject, SourceRecord
from app.services.calendar_structure import expand_structure

METRIC_ID = 'work_interval_execution'
METHOD_VERSION = 'v1'
WINDOW_DAYS: tuple[int, ...] = ()
DEPENDS_ON: tuple[str, ...] = ()
CONFIG = {
    'segment_source': 'plan_plus_wkt_step_index',
    'work_intensities': ['active', 'interval'],
    'repeat_type': 'repeat_until_steps_cmplt',
    'max_record_gap_s': 10,
    'speed_valid_mps': [0, 10],
    'hr_valid_bpm': [30, 230],
    'hr_exclude_first_s': 60,
    'hr_min_step_timer_s': 180,
    'target_scored_modalities': ['speed'],
    'required_speed_rule': 'numeric_speed_target',
    'cv_rule': 'sample_sd_of_fully_completed_valid_reps',
    'last_first_rule': 'original_endpoints',
    'subtotal_rule': 'known_or_null.v1',
    'synthetic_provenance_rule': 'demo_fixture_raw_json_plus_normalized_trace.v1',
}


def _synthetic_provenance(rows: Sequence[Sequence[str | None]],
                          normalized_hash: object) -> bool:
    """A demo trace is usable only when every linked source has preserved raw JSON."""
    if not isinstance(normalized_hash, str) or re.fullmatch(r'[0-9a-f]{64}', normalized_hash) is None or not rows:
        return False
    for row in rows:
        if len(row) != 4:
            return False
        kind, payload, raw, media_type = row
        if (kind != 'demo_fixture' or media_type != 'application/json' or
                not isinstance(payload, str) or payload != raw or
                re.fullmatch(r'[0-9a-f]{64}', payload) is None):
            return False
    return True


@dataclass(frozen=True)
class PlanStep:
    step: int
    type: str
    duration_type: str
    duration_value: float
    step_path: str
    repeat_index: int | None = None
    target_modality: str = 'effort'
    target_low: float | None = None
    target_high: float | None = None


@dataclass(frozen=True)
class FitStep:
    message_index: int
    duration_type: str
    intensity: str | None = None
    duration_value: float | None = None
    target_type: str | None = None
    target_low: float | None = None
    target_high: float | None = None
    repeat_from: int | None = None
    repeat_count: int | None = None


@dataclass(frozen=True)
class LapIn:
    lap_index: int
    start_offset_s: float
    timer_s: float | None = None
    elapsed_s: float | None = None
    distance_m: float | None = None
    wkt_step_index: int | None = None


@dataclass(frozen=True)
class ExecStream:
    t_s: list[int]
    hr_bpm: list[float | None]
    speed_mps: list[float | None]
    timer_on: list[tuple[float, float]]
    quality_flags: tuple[str, ...] = ()


def expand_plan(structure: list[dict]) -> list[PlanStep]:
    result = []
    for item in expand_structure(structure):
        target = item.get('target') or {}
        result.append(PlanStep(
            step=item['expanded_step'], type=item['type'], duration_type=item['duration_type'],
            duration_value=item['duration_value'], step_path=item['step_path'],
            repeat_index=item['repeat_index'], target_modality=target.get('modality', 'effort'),
            target_low=target.get('low'), target_high=target.get('high')))
    return result


def expand_fit(steps: list[FitStep]) -> list[FitStep]:
    ordered = sorted(steps, key=lambda x: x.message_index)
    if len({step.message_index for step in ordered}) != len(ordered):
        raise ValueError('MALFORMED_REPEAT')
    expanded: list[FitStep] = []
    starts: dict[int, int] = {}
    for step in ordered:
        if step.duration_type.startswith('repeat'):
            if step.duration_type != 'repeat_until_steps_cmplt':
                raise ValueError('UNSUPPORTED_REPEAT')
            if (step.repeat_from not in starts or type(step.repeat_count) is not int
                    or step.repeat_count < 2):
                raise ValueError('MALFORMED_REPEAT')
            start = starts[step.repeat_from]
            segment = expanded[start:].copy()
            for _ in range(step.repeat_count - 1):
                expanded.extend(segment)
                if len(expanded) > 100:
                    raise ValueError('UNSUPPORTED_REPEAT')
        else:
            starts[step.message_index] = len(expanded)
            expanded.append(step)
            if len(expanded) > 100:
                raise ValueError('UNSUPPORTED_REPEAT')
    return expanded


def clip(timer_on: list[tuple[float, float]], a: float, b: float) -> list[tuple[float, float]]:
    return [(max(start, a), min(end, b)) for start, end in timer_on
            if min(end, b) > max(start, a)]


def _union(timer_on: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for a, b in sorted(timer_on):
        if b < a:
            raise ValueError('invalid_timer')
        if b == a:
            continue
        if result and a <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], b))
        else:
            result.append((a, b))
    return result


def after_timer_seconds(timer_on: list[tuple[float, float]], seconds: float) -> list[tuple[float, float]]:
    remaining = seconds
    result = []
    for a, b in _union(timer_on):
        used = min(max(remaining, 0), b - a)
        remaining -= used
        if a + used < b:
            result.append((a + used, b))
    return result


def weighted_median(samples: list[tuple[float, float]]) -> float | None:
    valid = sorted((v, w) for v, w in samples if math.isfinite(v) and math.isfinite(w) and w > 0)
    if not valid:
        return None
    half = sum(w for _, w in valid) / 2
    cumulative = 0.0
    for i, (v, w) in enumerate(valid):
        cumulative += w
        if cumulative == half and i + 1 < len(valid):
            return (v + valid[i + 1][0]) / 2
        if cumulative >= half:
            return v
    return valid[-1][0]


def _number(value: float | None) -> TypeGuard[float]:
    return value is not None and isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def _rounded(value: float | None, places: int) -> float | None:
    return round(value, places) if _number(value) else None


def _early(status: Status, reason: str) -> dict[str, Any]:
    return {'status': status.value, 'quality_status': None, 'value': None,
            'reason_codes': [reason], 'quality_flags': []}


def execution_outcome(plan_steps: list[PlanStep], fit_steps: list[FitStep],
                      laps: list[LapIn], stream: ExecStream | None) -> dict[str, Any]:
    work = [step for step in plan_steps if step.type == 'work']
    if not work:
        return _early(Status.not_applicable, 'NO_WORK_STEPS')
    if any(not _number(step.duration_value) or step.duration_value <= 0 for step in work):
        raise ValueError('invalid_structure')
    try:
        watch = expand_fit(fit_steps)
    except ValueError as exc:
        return _early(Status.not_assessable, str(exc))
    watch_work = [(i, step) for i, step in enumerate(watch) if step.intensity in ('active', 'interval')]
    if (len(watch_work) != len(work) or any(
        plan.duration_type != fit.duration_type for plan, (_, fit) in zip(work, watch_work))):
        return _early(Status.not_assessable, 'WATCH_WORKOUT_MISMATCH')
    ordered_laps = sorted(laps, key=lambda lap: lap.lap_index)
    if len({lap.lap_index for lap in ordered_laps}) != len(ordered_laps):
        return _early(Status.not_assessable, 'LAP_STEP_ORDER_MISMATCH')
    indexed = [(i, lap.wkt_step_index) for i, lap in enumerate(ordered_laps) if lap.wkt_step_index is not None]
    if indexed:
        first_index, last_index = indexed[0][0], indexed[-1][0]
        if (any(ordered_laps[i].wkt_step_index is None for i in range(first_index, last_index + 1))
                or [index for _, index in indexed] !=
                [step.message_index for step in watch[:len(indexed)]]):
            return _early(Status.not_assessable, 'LAP_STEP_ORDER_MISMATCH')
    lap_by_position = {i: lap for i, lap in enumerate(
        lap for lap in ordered_laps if lap.wkt_step_index is not None)}
    # Indexed laps are a prefix of watch steps. Work positions therefore map exactly.
    reasons: set[str] = set()
    flags: set[str] = set()
    reps: list[dict[str, Any]] = []
    required_eligible = required_valid = target_valid_total = target_in_total = 0.0
    required_unassessable = False
    valid_means: list[float] = []
    for rep_number, (step, (watch_position, _)) in enumerate(zip(work, watch_work), 1):
        lap = lap_by_position.get(watch_position)
        target_low, target_high = step.target_low, step.target_high
        required = (step.target_modality == 'speed' and _number(target_low)
                    and _number(target_high) and target_low <= target_high)
        rep_reasons: list[str] = []
        speed_reasons: list[str] = []
        rep_flags: list[str] = []
        actual = (lap.timer_s if step.duration_type == 'time' else lap.distance_m) if lap else None
        ratio = actual / step.duration_value if _number(actual) and step.duration_value > 0 else None
        completed = ratio is not None and ratio >= 1
        if lap is None:
            rep_reasons.append('WORK_STEP_NOT_RECORDED')
        elif ratio is None:
            rep_reasons.append('COMPLETION_VALUE_MISSING')
        elif ratio < 1:
            rep_reasons.append('INCOMPLETE_WORK_STEP')
        speed_status = Status.missing if lap is None else Status.not_assessable
        mean = coverage = target_valid = target_in = in_target = hr_median = None
        eligible = valid = 0.0
        if lap is not None:
            a = lap.start_offset_s
            next_lap = min((other for other in ordered_laps if other.start_offset_s > a),
                           key=lambda other: other.start_offset_s, default=None)
            b = a + lap.elapsed_s if _number(lap.elapsed_s) else (
                next_lap.start_offset_s if next_lap else None)
            issue = None
            if stream is None:
                issue = 'NO_STREAM'
            elif any(flag in stream.quality_flags for flag in
                     ('TIMER_EVENTS_MISSING', 'TIMER_EVENTS_AMBIGUOUS', 'TIMER_MISMATCH')):
                issue = next(flag for flag in ('TIMER_EVENTS_MISSING', 'TIMER_EVENTS_AMBIGUOUS',
                                              'TIMER_MISMATCH') if flag in stream.quality_flags)
            elif b is None:
                issue = 'LAP_END_UNKNOWN'
            elif not _number(a) or b <= a:
                issue = 'LAP_BOUNDS_INVALID'
            if issue:
                speed_reasons.append(issue)
            else:
                assert stream is not None and b is not None
                integrate_timer_on(stream.t_s, stream.timer_on, 10)
                timer = _union(clip(stream.timer_on, a, b))
                pieces = integrate_timer_on(stream.t_s, timer, 10)
                eligible = sum(weight for _, weight, _ in pieces)
                if eligible == 0:
                    speed_reasons.append('NO_TIMER_ON_DATA')
                else:
                    speed_samples: list[tuple[float, float]] = []
                    for i, weight, known in pieces:
                        if known and i is not None and i < len(stream.speed_mps):
                            speed = stream.speed_mps[i]
                            if plausible_speed(speed):
                                speed_samples.append((cast(float, speed), weight))
                    valid = sum(weight for _, weight in speed_samples)
                    coverage = valid / eligible
                    if valid == 0:
                        speed_reasons.append('NO_SPEED_SAMPLES')
                    else:
                        mean = sum(speed * weight for speed, weight in speed_samples) / valid
                        speed_status = Status.available if coverage >= .9 else Status.partial
                        if speed_status == Status.partial:
                            speed_reasons.append('LOW_COVERAGE')
                        if required:
                            assert target_low is not None and target_high is not None
                            target_valid = valid
                            target_in = sum(weight for speed, weight in speed_samples
                                            if target_low <= speed <= target_high)
                            in_target = target_low <= mean <= target_high
                if _number(lap.timer_s) and lap.timer_s >= 180:
                    hr_pieces = integrate_timer_on(stream.t_s, after_timer_seconds(timer, 60), 10)
                    hr_samples: list[tuple[float, float]] = []
                    for i, weight, known in hr_pieces:
                        if known and i is not None and i < len(stream.hr_bpm):
                            hr = stream.hr_bpm[i]
                            if plausible_hr(hr):
                                hr_samples.append((cast(float, hr), weight))
                    hr_median = weighted_median(hr_samples)
            if lap.timer_s is None:
                rep_flags.append('HR_TIMER_UNKNOWN')
            elif _number(lap.timer_s) and lap.timer_s < 180:
                rep_flags.append('HR_NOT_REPORTED_SHORT_STEP')
        if step.target_modality == 'hr':
            rep_flags.append('HR_TARGET_NOT_SCORED')
        if required and lap is not None:
            if speed_status == Status.not_assessable:
                rep_reasons.append('COMPONENT_NOT_ASSESSABLE')
                required_unassessable = True
            elif speed_status == Status.partial:
                rep_reasons.append('LOW_COVERAGE')
            if eligible > 0:
                required_eligible += eligible
                required_valid += valid
            if target_valid is not None and target_in is not None:
                target_valid_total += target_valid
                target_in_total += target_in
        if rep_reasons and lap is not None:
            reasons.update(rep_reasons)
        flags.update(rep_flags)
        if completed and speed_status == Status.available and mean is not None:
            valid_means.append(mean)
        reps.append({
            'rep': rep_number, 'planned_step': step.step, 'step_path': step.step_path,
            'repeat_index': step.repeat_index, 'lap_index': lap.lap_index if lap else None,
            'observed': lap is not None, 'fully_completed': completed,
            'status': (Status.missing if lap is None else Status.partial if rep_reasons else Status.available).value,
            'reason_codes': sorted(rep_reasons), 'planned_duration_type': step.duration_type,
            'planned_value': step.duration_value, 'actual_timer_s': _rounded(lap.timer_s, 1) if lap else None,
            'actual_distance_m': _rounded(lap.distance_m, 1) if lap else None,
            'completion_ratio': _rounded(ratio, 3), 'mean_speed_mps': _rounded(mean, 3),
            'speed_status': speed_status.value, 'speed_reason_codes': sorted(speed_reasons),
            'speed_coverage': _rounded(coverage, 3), 'target_modality': step.target_modality,
            'target_low': step.target_low, 'target_high': step.target_high,
            'target_valid_s': _rounded(target_valid, 1), 'target_in_range_s': _rounded(target_in, 1),
            'in_target': in_target, 'hr_median_bpm': _rounded(hr_median, 1), 'flags': sorted(rep_flags),
            '_mean': mean, '_raw_timer': lap.timer_s if lap and _number(lap.timer_s) else None,
            '_raw_distance': lap.distance_m if lap and _number(lap.distance_m) else None,
        })
    observed = [rep for rep in reps if rep['observed']]
    n_completed = sum(rep['fully_completed'] for rep in reps)
    if n_completed < len(work):
        reasons.add('INCOMPLETE_WORK_STEPS')
    def subtotal(key: str, flag: str) -> float | None:
        if not observed:
            return 0.0
        values = [rep[key] for rep in observed if rep[key] is not None]
        if len(values) < len(observed):
            reasons.add('WORK_MEASUREMENT_MISSING')
            if values:
                flags.add(flag)
        return round(sum(values), 1) if values else None
    completed_s = subtotal('_raw_timer', 'PARTIAL_WORK_TIMER')
    completed_m = subtotal('_raw_distance', 'PARTIAL_WORK_DISTANCE')
    cv = None
    if len(valid_means) >= 2:
        average = sum(valid_means) / len(valid_means)
        if average > 0:
            cv = 100 * math.sqrt(sum((value - average) ** 2 for value in valid_means)
                                 / (len(valid_means) - 1)) / average
        else:
            flags.add('ZERO_SPEED_DENOMINATOR')
    first_rep, last_rep = reps[0], reps[-1]
    change = None
    if (first_rep['fully_completed'] and last_rep['fully_completed']
            and first_rep['speed_status'] == Status.available.value
            and last_rep['speed_status'] == Status.available.value
            and first_rep['_mean'] is not None and last_rep['_mean'] is not None):
        if first_rep['_mean'] > 0:
            change = 100 * (last_rep['_mean'] - first_rep['_mean']) / first_rep['_mean']
        else:
            flags.add('ZERO_SPEED_DENOMINATOR')
    quality = coverage_label(required_valid, required_eligible) if required_eligible else None
    if required_unassessable and quality == QualityStatus.good:
        quality = QualityStatus.limited
    for rep in reps:
        del rep['_mean']
        del rep['_raw_timer']
        del rep['_raw_distance']
    return {
        'status': (Status.partial if reasons else Status.available).value,
        'quality_status': quality.value if quality else None,
        'reason_codes': sorted(reasons), 'quality_flags': sorted(flags),
        'value': {
            'reps': reps, 'n_planned': len(work), 'n_observed': len(observed),
            'n_completed': n_completed, 'step_completion_ratio': round(n_completed / len(work), 3),
            'cv_speed': _rounded(cv, 3), 'last_first_change_pct': _rounded(change, 3),
            'completed_work_s': completed_s, 'completed_work_m': completed_m,
            'planned_work_s': round(sum(step.duration_value for step in work), 1)
            if all(step.duration_type == 'time' for step in work) else None,
            'planned_work_m': round(sum(step.duration_value for step in work), 1)
            if all(step.duration_type == 'distance' for step in work) else None,
            'target_coverage': _rounded(target_in_total / target_valid_total, 3)
            if target_valid_total else None,
        },
    }


@register(METRIC_ID, METHOD_VERSION, DEPENDS_ON)
def compute(session: Session, subject_key: str) -> list[MetricResultData]:
    try:
        activity_id = uuid.UUID(subject_key)
    except ValueError as exc:
        raise ValueError('invalid_subject_key') from exc
    activity = session.get(Activity, activity_id)
    if activity is None or activity.sport not in ('running', 'trail_running', 'treadmill_running'):
        return []
    annotation = session.scalar(select(ActivityAnnotation).where(
        ActivityAnnotation.activity_id == activity_id).order_by(ActivityAnnotation.version.desc()).limit(1))
    state = session.get(AppState, 1)
    head = state.calendar_head_version if state else 0
    completion = session.scalar(select(SessionCompletion).where(SessionCompletion.activity_id == activity_id))
    session_uid = completion.session_uid if completion else None
    revision = None
    if session_uid and head:
        revision = session.scalar(select(CalendarSessionRevision).where(
            CalendarSessionRevision.session_uid == session_uid,
            CalendarSessionRevision.calendar_version_number <= head)
            .order_by(CalendarSessionRevision.calendar_version_number.desc()).limit(1))
    reason = None
    if (annotation and annotation.excluded) or activity.resolution_state != 'resolved':
        reason = 'ACTIVITY_EXCLUDED'
    elif not revision or revision.deleted or revision.kind != 'run':
        reason = 'NO_PLAN_LINK'
    elif revision.structure is None:
        reason = 'NO_STRUCTURED_PLAN'
    refs = metric_source_refs(session, activity_id, session_uid, head)
    if reason:
        outcome = _early(Status.not_applicable, reason)
    else:
        assert revision is not None and revision.structure is not None
        plan = expand_plan(cast(list[dict], revision.structure))
        if not any(step.type == 'work' for step in plan):
            outcome = _early(Status.not_applicable, 'NO_WORK_STEPS')
        else:
            watch_rows = session.scalars(select(ActivityWorkoutStep).where(
                ActivityWorkoutStep.activity_id == activity_id).order_by(ActivityWorkoutStep.message_index)).all()
            fit = [FitStep(row.message_index, row.duration_type, row.intensity, row.duration_value,
                           row.target_type, row.target_low, row.target_high, row.repeat_from, row.repeat_count)
                   for row in watch_rows]
            if not fit:
                outcome = _early(Status.not_assessable, 'NO_WATCH_WORKOUT')
            else:
                lap_rows = session.scalars(select(ActivityLap).where(
                    ActivityLap.activity_id == activity_id).order_by(ActivityLap.lap_index)).all()
                laps = [LapIn(row.lap_index, (row.start_at - activity.start_at).total_seconds(),
                              row.timer_s, row.elapsed_s, row.distance_m, row.wkt_step_index)
                        for row in lap_rows]
                stream_row = session.get(ActivityStream, activity_id)
                stream = ExecStream(stream_row.t_s, stream_row.hr_bpm, stream_row.speed_mps,
                                    [tuple(pair) for pair in stream_row.timer_on],
                                    tuple(stream_row.quality_flags)) if stream_row else None
                outcome = execution_outcome(plan, fit, laps, stream)
    value = outcome['value']
    if value is not None:
        value['session_uid'] = str(session_uid) if session_uid else None
        value['calendar_version'] = head
    if value is not None and activity.fit_status == 'decoded' and (
            not isinstance(refs.get('fit'), dict) or
            refs['fit'].get('raw_object_id') is None or refs['fit'].get('zip_sha256') is None or
            refs['fit'].get('fit_sha256') is None):
        synthetic = False
        if settings.app_mode in {'demo', 'test'} and isinstance(refs.get('fit'), dict):
            sources = [tuple(row) for row in session.execute(select(SourceRecord.source_kind, SourceRecord.payload_hash,
                RawObject.sha256, RawObject.media_type).select_from(ActivitySource)
                .join(SourceRecord, SourceRecord.id == ActivitySource.source_record_id)
                .outerjoin(RawObject, RawObject.id == SourceRecord.raw_object_id)
                .where(ActivitySource.activity_id == activity_id)).all()]
            synthetic = _synthetic_provenance(sources, refs['fit'].get('normalized_hash'))
        if synthetic:
            outcome['quality_flags'] = sorted(set(outcome['quality_flags']) | {'SYNTHETIC_PROVENANCE'})
        else:
            outcome = _early(Status.invalid, 'INPUT_PROVENANCE_MISSING')
    return [MetricResultData(
        metric_id=METRIC_ID, method_version=METHOD_VERSION, subject_type='activity',
        subject_key=str(activity_id), status=Status(outcome['status']),
        quality_status=QualityStatus(outcome['quality_status']) if outcome['quality_status'] else None,
        value=outcome['value'], reason_codes=tuple(outcome['reason_codes']),
        quality_flags=tuple(outcome['quality_flags']), source_refs=refs,
        anchor_keys=(), config_hash=config_hash(CONFIG), unit=None)]
