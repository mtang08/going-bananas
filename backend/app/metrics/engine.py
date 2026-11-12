from __future__ import annotations

import importlib
import json
import re
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.fit_models import ActivityStream, FitFile
from app.metric_models import MetricConfig
from app.metric_models import MetricResult as MetricResultRow
from app.metrics.contract import (
    MetricResultData,
    RunFact,
    canonical_json,
    completion_association_hash,
    config_hash,
    sha256_json,
)
from app.models import (
    Activity,
    ActivityAnnotation,
    ActivitySource,
    AppState,
    CoverageInterval,
    ProfileVersion,
    RawObject,
    SourceRecord,
)

METRIC_MODULES = ('volume', 'long_run', 'srpe', 'symptoms', 'intensity', 'intervals', 'recovery', 'planned_actual', 'spacing')


@dataclass(frozen=True)
class RegisteredMetric:
    metric_id: str
    method_version: str
    depends_on: tuple[str, ...]
    compute: Callable[[Session, str], list[MetricResultData]]


REGISTRY: dict[str, RegisteredMetric] = {}


def register(metric_id: str, method_version: str, depends_on: tuple[str, ...]):
    def decorator(compute: Callable[[Session, str], list[MetricResultData]]):
        if metric_id in REGISTRY:
            raise ValueError('duplicate_metric_registration')
        REGISTRY[metric_id] = RegisteredMetric(metric_id, method_version, depends_on, compute)
        return compute
    return decorator


def _ordered_registry() -> list[RegisteredMetric]:
    ordered: list[RegisteredMetric] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(metric_id: str) -> None:
        if metric_id not in REGISTRY:
            raise ValueError('unknown_metric_dependency')
        if metric_id in visiting:
            raise ValueError('metric_dependency_cycle')
        if metric_id in visited:
            return
        visiting.add(metric_id)
        item = REGISTRY[metric_id]
        for dependency in item.depends_on:
            visit(dependency)
        visiting.remove(metric_id)
        visited.add(metric_id)
        ordered.append(item)

    for key in REGISTRY:
        visit(key)
    return ordered


def parse_scope(scope: str) -> tuple[str, str | tuple[date, ...] | uuid.UUID | None]:
    if scope in ('calendar', 'timezone'):
        return scope, None
    if scope.startswith(('activity:', 'checkin:')):
        kind, raw = scope.split(':', 1)
        try:
            return kind, uuid.UUID(raw)
        except ValueError as exc:
            raise ValueError('invalid_scope') from exc
    if scope.startswith('strength:'):
        parts = scope.split(':')
        if len(parts) == 3 and parts[1] in ('strong', 'manual'):
            try:
                return 'strength:' + parts[1], uuid.UUID(parts[2])
            except ValueError as exc:
                raise ValueError('invalid_scope') from exc
    if scope.startswith(('anchors:', 'all:')):
        kind, raw = scope.split(':', 1)
        try:
            value = date.fromisoformat(raw)
            if value.isoformat() == raw:
                return kind, (value,)
        except ValueError:
            pass
    if scope.startswith('recovery_dates:'):
        values = scope.split(':', 1)[1].split(',')
        try:
            parsed = tuple(date.fromisoformat(value) for value in values)
            if values and all(date_value.isoformat() == raw for date_value, raw in zip(parsed, values)):
                return 'recovery_dates', parsed
        except ValueError:
            pass
    raise ValueError('invalid_scope')


def _profile_timezone(session: Session) -> str:
    profile = session.scalar(select(ProfileVersion).order_by(ProfileVersion.version.desc()).limit(1))
    return profile.timezone if profile else 'America/New_York'


def _activity_sources(session: Session, activity_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = session.execute(select(ActivitySource, SourceRecord, RawObject)
        .join(SourceRecord, ActivitySource.source_record_id == SourceRecord.id)
        .outerjoin(RawObject, SourceRecord.raw_object_id == RawObject.id)
        .where(ActivitySource.activity_id == activity_id)
        .order_by(SourceRecord.id)).all()
    return [{'source_record_id': str(source.id), 'payload_hash': source.payload_hash,
             'source_modified_at': source.source_modified_at.isoformat() if source.source_modified_at else None,
             'parser_version': source.parser_version, 'raw_sha256': raw.sha256 if raw else None,
             'selected_fields': link.selected_fields}
            for link, source, raw in rows]


def _fit_refs(session: Session, activity_id: uuid.UUID) -> dict[str, Any] | None:
    fit = session.scalar(select(FitFile).where(FitFile.activity_id == activity_id))
    stream = session.get(ActivityStream, activity_id)
    from app.fit_models import ActivityLap, ActivityWorkoutStep
    def normalized(row):
        return {column.key: getattr(row, column.key) for column in row.__table__.columns
                if column.key not in {'id', 'activity_id'}}
    decoded = {'stream': normalized(stream) if stream else None,
        'laps': [normalized(row) for row in session.scalars(select(ActivityLap).where(
            ActivityLap.activity_id == activity_id).order_by(ActivityLap.lap_index))],
        'steps': [normalized(row) for row in session.scalars(select(ActivityWorkoutStep).where(
            ActivityWorkoutStep.activity_id == activity_id).order_by(ActivityWorkoutStep.message_index))]}
    if fit is None:
        return {'normalized_hash': sha256_json(decoded), 'quality_flags': list(stream.quality_flags) if stream else []}
    return {'normalized_hash': sha256_json(decoded), 'id': str(fit.id), 'fit_sha256': fit.fit_sha256, 'zip_sha256': fit.zip_sha256,
            'raw_object_id': str(fit.raw_object_id), 'sdk_version': fit.sdk_version,
            'profile_version': fit.profile_version,
            'quality_flags': list(stream.quality_flags) if stream else []}


def _activity_identity(session: Session, activity: Activity,
                       annotation: ActivityAnnotation | None) -> tuple[str, dict[str, Any]]:
    refs = {'id': str(activity.id), 'canonical_revision': activity.canonical_revision,
            'fit_status': activity.fit_status,
            'facts': {name: getattr(activity, name) for name in ('start_at', 'end_at', 'sport',
                'timer_s', 'elapsed_s', 'distance_m', 'source_workout_label', 'resolution_state')},
            'annotation': {'excluded': annotation.excluded, 'workout_label': annotation.workout_label} if annotation else None,
            'annotation_version': annotation.version if annotation else None,
            'source_records': _activity_sources(session, activity.id),
            'field_provenance': activity.field_provenance or {},
            'fit': _fit_refs(session, activity.id)}
    return sha256_json(refs), refs


def load_runs(session: Session, start_date: date, end_date_excl: date) -> list[RunFact]:
    zone = ZoneInfo(_profile_timezone(session))
    start_utc = datetime.combine(start_date - timedelta(days=1), datetime.min.time(), tzinfo=zone).astimezone(UTC)
    end_utc = datetime.combine(end_date_excl + timedelta(days=1), datetime.min.time(), tzinfo=zone).astimezone(UTC)
    activities = session.scalars(select(Activity).where(
        Activity.sport.in_(('running', 'trail_running', 'treadmill_running')),
        Activity.resolution_state == 'resolved', Activity.start_at >= start_utc,
        Activity.start_at < end_utc).order_by(Activity.start_at, Activity.id)).all()
    result: list[RunFact] = []
    for activity in activities:
        local_date = activity.start_at.astimezone(zone).date()
        if not start_date <= local_date < end_date_excl:
            continue
        annotation = session.scalar(select(ActivityAnnotation).where(ActivityAnnotation.activity_id == activity.id)
                                    .order_by(ActivityAnnotation.version.desc()).limit(1))
        if annotation and annotation.excluded:
            continue
        source_revision, refs = _activity_identity(session, activity, annotation)
        result.append(RunFact(activity.id, activity.start_at, activity.end_at, local_date,
                              activity.sport, activity.timer_s, activity.distance_m,
                              annotation.workout_label if annotation and annotation.workout_label else activity.source_workout_label,
                              refs, source_revision))
    return result


def activities_coverage_complete(session: Session, start_date: date, end_date_excl: date) -> bool:
    if start_date >= end_date_excl:
        return True
    intervals = session.scalars(select(CoverageInterval).where(
        CoverageInterval.dataset == 'activities', CoverageInterval.status == 'complete',
        CoverageInterval.fully_enumerated.is_(True),
        CoverageInterval.end_date >= start_date,
        CoverageInterval.start_date < end_date_excl).order_by(CoverageInterval.start_date)).all()
    covered_until = start_date
    for interval in intervals:
        if interval.start_date > covered_until:
            return False
        covered_until = max(covered_until, interval.end_date + timedelta(days=1))
        if covered_until >= end_date_excl:
            return True
    return False


def latest_results(session: Session, metric_id: str, method_version: str,
                   subject_keys: list[str] | tuple[str, ...]) -> dict[str, MetricResultRow]:
    if not subject_keys:
        return {}
    rows = session.scalars(select(MetricResultRow).where(
        MetricResultRow.metric_id == metric_id, MetricResultRow.method_version == method_version,
        MetricResultRow.subject_key.in_(subject_keys), MetricResultRow.is_current.is_(True))).all()
    return {row.subject_key: row for row in rows}


def ensure_metric_config(session: Session, metric_id: str, method_version: str,
                         config: Mapping[str, Any]) -> str:
    digest = config_hash(config)
    stmt = insert(MetricConfig).values(id=uuid.uuid4(), metric_id=metric_id,
                                       method_version=method_version, config=dict(config),
                                       config_hash=digest).on_conflict_do_nothing(
        index_elements=['metric_id', 'method_version', 'config_hash'])
    session.execute(stmt)
    return digest


def _result_dependency(result: MetricResultData) -> tuple[str, bool]:
    refs = result.source_refs
    required = bool(result.config_hash) and bool(result.timezone)
    identities = (
        isinstance(refs.get('activity'), dict) and bool(refs['activity'].get('id'))
        and bool(refs['activity'].get('source_revision')),
        isinstance(refs.get('plan'), dict) and bool(refs['plan'].get('revision_id'))
        and refs['plan'].get('calendar_version') is not None,
        isinstance(refs.get('checkin'), dict) and bool(refs['checkin'].get('id'))
        and refs['checkin'].get('version') is not None,
        isinstance(refs.get('recovery'), (dict, list)) and bool(refs['recovery']),
        isinstance(refs.get('source_records'), list) and any(
            isinstance(row, dict) and row.get('payload_hash') for row in refs['source_records']),
        isinstance(refs.get('sources'), (dict, list)) and bool(refs['sources']),
        isinstance(refs.get('input_hash'), str) and bool(refs['input_hash']),
        isinstance(refs.get('completion_association_hash'), str)
        and bool(refs['completion_association_hash']),
    )
    required = required and any(identities)
    return sha256_json({'source_refs': refs, 'config_hash': result.config_hash,
                        'anchor_set_hash': result.anchor_set_hash, 'timezone': result.timezone,
                        'calculator_dependency_hash': result.dependency_hash}), required


def upsert_results(session: Session, results: list[MetricResultData]) -> None:
    if not results:
        return
    session.execute(text('SELECT pg_advisory_xact_lock(71382413)'))
    calculated_at = session.info.get('metrics_now') or datetime.now(UTC)
    timezone = _profile_timezone(session)
    for raw in results:
        supplied = replace(raw, timezone=raw.timezone or timezone,
                           source_refs=json.loads(canonical_json(raw.source_refs)),
                           value=json.loads(canonical_json(raw.value)))
        dependency_hash, complete = _result_dependency(supplied)
        reason_codes = supplied.reason_codes
        status = str(supplied.status)
        if not complete:
            status = 'invalid'
            reason_codes = tuple(dict.fromkeys((*reason_codes, 'MISSING_PROVENANCE')))
        if not complete:
            dependency_hash = sha256_json({'missing_provenance': True, 'computed': dependency_hash})
        session.query(MetricResultRow).filter(
            MetricResultRow.metric_id == supplied.metric_id,
            MetricResultRow.method_version == supplied.method_version,
            MetricResultRow.subject_key == supplied.subject_key,
            MetricResultRow.is_current.is_(True)).update({'is_current': False}, synchronize_session='fetch')
        existing = session.scalar(select(MetricResultRow).where(
            MetricResultRow.metric_id == supplied.metric_id,
            MetricResultRow.method_version == supplied.method_version,
            MetricResultRow.subject_key == supplied.subject_key,
            MetricResultRow.config_hash == supplied.config_hash,
            func.coalesce(MetricResultRow.anchor_set_hash, '') == (supplied.anchor_set_hash or ''),
            MetricResultRow.dependency_hash == dependency_hash))
        values = {'window_start': supplied.window_start, 'window_end': supplied.window_end,
                  'window_label': supplied.window_label, 'status': str(status),
                  'quality_status': str(supplied.quality_status) if supplied.quality_status else None,
                  'value': supplied.value if complete else None, 'unit': supplied.unit,
                  'reason_codes': list(reason_codes), 'quality_flags': list(supplied.quality_flags),
                  'source_refs': supplied.source_refs, 'anchor_keys': list(supplied.anchor_keys),
                  'calculated_at': supplied.calculated_at or calculated_at, 'is_current': True}
        if existing:
            existing.is_current = True
        else:
            session.add(MetricResultRow(metric_id=supplied.metric_id,
                method_version=supplied.method_version, subject_type=supplied.subject_type,
                subject_key=supplied.subject_key, config_hash=supplied.config_hash,
                anchor_set_hash=supplied.anchor_set_hash, dependency_hash=dependency_hash,
                timezone=supplied.timezone, **values))
        session.flush()


def metric_source_refs(session: Session, activity_id: uuid.UUID, session_uid: uuid.UUID | None = None,
                       calendar_version: int | None = None) -> dict[str, Any]:
    activity = session.get(Activity, activity_id)
    if activity is None:
        raise ValueError('activity_not_found')
    annotation = session.scalar(select(ActivityAnnotation).where(ActivityAnnotation.activity_id == activity_id)
                                .order_by(ActivityAnnotation.version.desc()).limit(1))
    source_revision, activity_refs = _activity_identity(session, activity, annotation)
    selected_version = calendar_version
    if selected_version is None:
        state = session.get(AppState, 1)
        selected_version = state.calendar_head_version if state else 0
    plan: dict[str, Any] | None = None
    if session_uid and selected_version > 0:
        revision = session.scalar(select(CalendarSessionRevision).where(
            CalendarSessionRevision.session_uid == session_uid,
            CalendarSessionRevision.calendar_version_number <= selected_version)
            .order_by(CalendarSessionRevision.calendar_version_number.desc()).limit(1))
        if revision and not revision.deleted:
            plan = {'session_uid': str(session_uid), 'revision_id': str(revision.id),
                    'calendar_version': selected_version, 'structure_hash': sha256_json(revision.structure)}
    completion = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == session_uid)) if session_uid else None
    return {'activity': {'id': str(activity_id), 'source_revision': source_revision,
                         'source_refs': activity_refs}, 'fit': _fit_refs(session, activity_id),
            'plan': plan, 'completion_association_hash': completion_association_hash(completion) if completion else None}


def metric_modules() -> tuple[Any, ...]:
    return tuple(importlib.import_module(f'app.metrics.{name}') for name in METRIC_MODULES)


def ensure_configs(session: Session) -> None:
    for module in metric_modules():
        ensure_metric_config(session, module.METRIC_ID, module.METHOD_VERSION, module.CONFIG)


def _now(session: Session) -> datetime:
    return session.info.get('metrics_now') or datetime.now(UTC)


def _today(session: Session) -> date:
    return _now(session).astimezone(ZoneInfo(_profile_timezone(session))).date()


@contextmanager
def _refreshing(session: Session):
    depth = session.info.get('metrics_depth', 0)
    old_running = session.info.get('metrics_running', False)
    session.info['metrics_running'] = True
    session.info['metrics_depth'] = depth + 1
    try:
        if depth == 0:
            session.execute(text('SELECT pg_advisory_xact_lock(71382413)'))
            session.info['metrics_computed'] = set()
            ensure_configs(session)
        yield
    finally:
        session.info['metrics_depth'] = depth
        session.info['metrics_running'] = old_running
        if depth == 0:
            session.info.pop('metrics_computed', None)
            session.info.pop('metrics_depth', None)


def compute_subjects(session: Session, metric_id: str, subject_keys: Sequence[str]) -> list[MetricResultData]:
    metric_modules()
    if metric_id not in REGISTRY:
        raise ValueError('unknown_metric')
    allowed = session.info.get('metrics_filter')
    if allowed is not None and metric_id not in allowed:
        return []
    registration = REGISTRY[metric_id]
    cache = session.info.get('metrics_computed', set())
    results = []
    for key in dict.fromkeys(subject_keys):
        if (metric_id, key) in cache:
            continue
        calculated = [replace(row, calculated_at=_now(session)) for row in registration.compute(session, key)]
        if not calculated:
            session.query(MetricResultRow).filter(MetricResultRow.metric_id == metric_id,
                MetricResultRow.method_version == registration.method_version,
                MetricResultRow.subject_key == key, MetricResultRow.is_current.is_(True)).update(
                    {'is_current': False}, synchronize_session='fetch')
        upsert_results(session, calculated)
        cache.add((metric_id, key))
        results.extend(calculated)
    return results


def _activity_ids(session: Session, start: date, end: date) -> list[uuid.UUID]:
    zone = ZoneInfo(_profile_timezone(session))
    rows = session.execute(select(Activity.id, Activity.start_at).where(
        Activity.start_at >= datetime.combine(start - timedelta(days=1), datetime.min.time(), tzinfo=zone),
        Activity.start_at < datetime.combine(end + timedelta(days=2), datetime.min.time(), tzinfo=zone))
        .order_by(Activity.start_at, Activity.id)).all()
    return [uid for uid, stamp in rows if start <= stamp.astimezone(zone).date() <= end]


def _refresh_runs(session: Session, activity_ids: Iterable[uuid.UUID]) -> list[MetricResultData]:
    keys = [str(uid) for uid in dict.fromkeys(activity_ids)]
    run_metrics = {'symptom_response_timeline', 'session_rpe_load', 'long_run_exposure',
                   'intensity_time_distribution', 'work_interval_execution'}
    results = []
    for item in _ordered_registry():
        if item.metric_id in run_metrics:
            results.extend(compute_subjects(session, item.metric_id, keys))
    return results


def _refresh_strength(session: Session, start: date, end: date) -> list[MetricResultData]:
    from app.models import ManualSession
    from app.strong_models import StrongWorkoutRow
    keys = [f'strong:{uid}' for uid in session.scalars(select(StrongWorkoutRow.id).where(
        StrongWorkoutRow.local_date >= start, StrongWorkoutRow.local_date <= end).order_by(StrongWorkoutRow.id))]
    keys += [f'manual:{uid}' for uid in session.scalars(select(ManualSession.id).where(
        ManualSession.date >= start, ManualSession.date <= end).order_by(ManualSession.id))]
    return compute_subjects(session, 'session_rpe_load', keys)


def _plan_uids(session: Session, start: date | None = None, end: date | None = None) -> list[uuid.UUID]:
    from app.services.calendar import state_at
    head = session.scalar(select(AppState.calendar_head_version).where(AppState.id == 1)) or 0
    if not head:
        return []
    rows = state_at(session, head)
    return [uuid.UUID(str(row['session_uid'])) for row in rows
            if (start is None or row['local_date'] >= start) and (end is None or row['local_date'] <= end)]


def _refresh_plans(session: Session, uids: Iterable[uuid.UUID]) -> list[MetricResultData]:
    keys = list(dict.fromkeys(str(uid) for uid in uids))
    linked = list(session.scalars(select(SessionCompletion.activity_id).where(
        SessionCompletion.session_uid.in_([uuid.UUID(key) for key in keys]), SessionCompletion.activity_id.is_not(None))))
    _refresh_runs(session, [uid for uid in linked if uid is not None])
    return compute_subjects(session, 'planned_actual_session', keys)


def assess_completion(session: Session, session_uid: uuid.UUID) -> None:
    with _refreshing(session):
        _refresh_plans(session, [session_uid])
        session.flush()


def ensure_nights(session: Session, start: date, end: date) -> None:
    if start > end:
        raise ValueError('invalid_date_window')
    with _refreshing(session):
        compute_subjects(session, 'recovery_multisignal_summary',
                         [f'night:{start + timedelta(days=n)}' for n in range((end - start).days + 1)])


def ensure_windows(session: Session, as_of: date) -> None:
    with _refreshing(session):
        start = as_of - timedelta(days=83)
        activity_ids = _activity_ids(session, start, as_of)
        _refresh_runs(session, activity_ids)
        _refresh_strength(session, start, as_of)
        linked = session.scalars(select(SessionCompletion.session_uid).where(SessionCompletion.activity_id.in_(activity_ids)))
        _refresh_plans(session, [*_plan_uids(session, as_of - timedelta(days=13), as_of + timedelta(days=13)), *linked])
        ensure_nights(session, as_of - timedelta(days=6), as_of)
        for metric_id in ('run_volume_frequency', 'long_run_exposure', 'session_rpe_load', 'intensity_time_distribution'):
            compute_subjects(session, metric_id, [f'w{n}:{as_of}' for n in (7, 14, 28, 56, 84)])
        compute_subjects(session, 'symptom_response_timeline', [f'w28:{as_of}'])
        compute_subjects(session, 'recovery_multisignal_summary', [f'w7:{as_of}'])
        compute_subjects(session, 'hard_session_spacing', [f'w14:{as_of}'])
        session.flush()


def enqueue_scopes(session: Session, scopes: Iterable[str]) -> None:
    values = list(scopes)
    for scope in values:
        parse_scope(scope)
    session.info.setdefault('metrics_scopes', set()).update(values)


def _all_dates(session: Session) -> set[date]:
    from app.models import ManualSession, RecoveryObservation
    from app.strong_models import StrongWorkoutRow
    zone = ZoneInfo(_profile_timezone(session))
    dates = {stamp.astimezone(zone).date() for stamp in session.scalars(select(Activity.start_at))}
    dates.update(session.scalars(select(ManualSession.date)))
    dates.update(session.scalars(select(StrongWorkoutRow.local_date)))
    dates.update(session.scalars(select(RecoveryObservation.source_date)))
    dates.update(session.scalars(select(CalendarSessionRevision.local_date)))
    return dates


def _refresh_scopes(session: Session, scopes: Iterable[str]) -> list[MetricResultData]:
    from app.checkin_models import Checkin
    from app.models import ManualSession
    from app.services.matching import rematch_dates
    from app.services.prompts import generate_prompts
    from app.strong_models import StrongWorkoutRow
    today = _today(session)
    dates = set(session.info.get('metrics_dates', ()))
    recovery_dates: set[date] = set()
    activity_ids: set[uuid.UUID] = set()
    strength_keys: set[str] = set()
    broad = False
    all_since = None
    for scope in scopes:
        kind, value = parse_scope(scope)
        if kind in ('calendar', 'timezone'):
            broad = True
        elif kind in ('all', 'anchors'):
            assert isinstance(value, tuple)
            all_since = min(all_since, value[0]) if all_since else value[0]
            broad = True
        elif kind == 'activity':
            assert isinstance(value, uuid.UUID)
            activity_ids.add(value)
            row = session.get(Activity, value)
            if row:
                dates.add(row.start_at.astimezone(ZoneInfo(_profile_timezone(session))).date())
        elif kind == 'checkin':
            checkin = session.get(Checkin, value)
            if checkin:
                day = checkin.observed_at.astimezone(ZoneInfo(_profile_timezone(session))).date()
                dates.update(day - timedelta(days=n) for n in range(3))
                recovery_dates.add(day)
                if checkin.activity_id:
                    activity_ids.add(checkin.activity_id)
        elif kind.startswith('strength:'):
            prefix = kind.split(':')[1]
            strength_keys.add(f'{prefix}:{value}')
            subject: Any = session.get(StrongWorkoutRow if prefix == 'strong' else ManualSession, value)
            if subject:
                dates.add(subject.local_date if prefix == 'strong' else subject.date)
        elif kind == 'recovery_dates':
            assert isinstance(value, tuple)
            recovery_dates.update(value)
            dates.update(value)
    if broad:
        all_dates = _all_dates(session)
        dates.update(d for d in all_dates if all_since is None or d >= all_since)
        recovery_dates.update(dates)
    match_dates = dates | {today}
    touched_uids = rematch_dates(session, match_dates)
    session.flush()
    for day in dates:
        activity_ids.update(_activity_ids(session, day - timedelta(days=2), day + timedelta(days=30)))
    if broad:
        activity_ids.update(session.scalars(select(Activity.id)))
    results = _refresh_runs(session, sorted(activity_ids, key=str))
    results.extend(compute_subjects(session, 'session_rpe_load', sorted(strength_keys)))
    linked = session.scalars(select(SessionCompletion.session_uid).where(SessionCompletion.activity_id.in_(activity_ids)))
    strength_links: list[uuid.UUID] = []
    for key in strength_keys:
        kind, raw_id = key.split(':', 1)
        column = SessionCompletion.strong_workout_id if kind == 'strong' else SessionCompletion.manual_session_id
        strength_links.extend(session.scalars(select(SessionCompletion.session_uid).where(column == uuid.UUID(raw_id))))
    explicit_uids = [uid for uid in session.info.get('metrics_plan_uids', ()) if uid] + strength_links
    results.extend(_refresh_plans(session, [*touched_uids, *linked, *explicit_uids, *(_plan_uids(session) if broad else ())]))
    as_ofs = {today}
    current = session.execute(select(MetricResultRow.subject_key, MetricResultRow.metric_id).where(
        MetricResultRow.is_current.is_(True), MetricResultRow.subject_type.in_(('window', 'night')))).all()
    stored_nights = set()
    for key, metric_id in current:
        match = re.fullmatch(r'w(\d+):(\d{4}-\d{2}-\d{2})(?::(?:run|strength))?', key)
        if match:
            end = date.fromisoformat(match[2])
            width = int(match[1]) * (2 if metric_id == 'run_volume_frequency' else 1)
            if broad or metric_id == 'hard_session_spacing' or any(end - timedelta(days=width - 1) <= day <= end for day in dates):
                as_ofs.add(end)
        elif key.startswith('night:'):
            stored_nights.add(date.fromisoformat(key[6:]))
    for day in recovery_dates:
        end = min(day + timedelta(days=60), today)
        if day <= end:
            ensure_nights(session, day, end)
        for stored in stored_nights:
            if day <= stored <= day + timedelta(days=60):
                ensure_nights(session, stored, stored)
        for key, metric_id in current:
            if metric_id == 'recovery_multisignal_summary' and key.startswith('w7:'):
                end = date.fromisoformat(key[3:])
                if day <= end <= day + timedelta(days=66):
                    as_ofs.add(end)
    for as_of in sorted(as_ofs):
        ensure_windows(session, as_of)
    generate_prompts(session, _now(session))
    session.flush()
    return results


def recompute(session: Session, scope: str) -> list[MetricResultData]:
    parse_scope(scope)
    if session is None:  # Registry contract tests can operate without a database.
        return [row for item in _ordered_registry() for row in item.compute(session, scope)]
    with _refreshing(session):
        return _refresh_scopes(session, [scope])


def _source_types() -> tuple[type, ...]:
    from app.calendar_models import CalendarVersion
    from app.checkin_models import Checkin, SessionRpe, SymptomReport
    from app.fit_models import ActivityLap, ActivityWorkoutStep
    from app.models import ManualSession, RecoveryObservation
    from app.planning_models import (
        Block,
        BlockDecision,
        BlockVersion,
        Event,
        Goal,
        IntensityAnchor,
        StrengthRoutineSlot,
    )
    from app.strong_models import StrongWorkoutRow
    return (Activity, ActivityAnnotation, ActivitySource, FitFile, ActivityLap, ActivityWorkoutStep, ActivityStream,
            SessionRpe, StrongWorkoutRow, ManualSession, Checkin, SymptomReport, CalendarVersion,
            CalendarSessionRevision, SessionCompletion, CoverageInterval, IntensityAnchor,
            RecoveryObservation, ProfileVersion, StrengthRoutineSlot, Goal, Event, Block, BlockVersion, BlockDecision)


def _before_flush(session: Session, _context, _instances) -> None:
    if session.info.get('metrics_running'):
        return
    rows = [row for row in (*session.new, *session.dirty, *session.deleted) if isinstance(row, _source_types())]
    if not rows:
        return
    with session.no_autoflush:
        if session.scalar(select(AppState.planning_authority).where(AppState.id == 1)) != 'calendar':
            return
    pending = session.info.setdefault('metrics_pending_sources', [])
    for row in rows:
        state = inspect(row)
        changes = {attribute.key for attribute in state.attrs if attribute.history.has_changes()}
        if isinstance(row, SessionCompletion) and state.persistent and changes <= {'status', 'version', 'updated_at'}:
            continue
        if state.persistent and row not in session.deleted and not changes:
            continue
        old = {}
        if state.identity is not None:
            table = state.mapper.local_table
            predicate = [column == value for column, value in zip(state.mapper.primary_key, state.identity, strict=True)]
            stored = session.connection().execute(select(table).where(*predicate)).mappings().first()
            old = dict(stored) if stored else {}
        pending.append((row, old))


def _after_flush(session: Session, _context) -> None:
    if session.info.get('metrics_running'):
        return
    from app.calendar_models import CalendarVersion
    from app.checkin_models import Checkin, SessionRpe, SymptomReport
    from app.models import ManualSession, RecoveryObservation
    from app.planning_models import (
        Block,
        BlockDecision,
        BlockVersion,
        Event,
        Goal,
        IntensityAnchor,
        StrengthRoutineSlot,
    )
    from app.strong_models import StrongWorkoutRow
    pending = session.info.pop('metrics_pending_sources', [])
    if not pending:
        return
    zone = ZoneInfo(_profile_timezone(session))
    scopes = session.info.setdefault('metrics_scopes', set())
    dates = session.info.setdefault('metrics_dates', set())
    for row, old in pending:
        new = {column.key: getattr(row, column.key, None) for column in inspect(row).mapper.columns}
        for facts in (old, new):
            uid = facts.get('id')
            for name in ('local_date', 'date', 'source_date', 'valid_from'):
                value = facts.get(name)
                if isinstance(value, date) and not isinstance(value, datetime):
                    dates.add(value)
            for name in ('start_at', 'end_at', 'observed_at'):
                value = facts.get(name)
                if isinstance(value, datetime):
                    dates.add(value.astimezone(zone).date())
            if isinstance(row, Activity) and uid:
                scopes.add(f'activity:{uid}')
            elif isinstance(row, Checkin) and uid:
                scopes.add(f'checkin:{uid}')
                observed = facts.get('observed_at')
                if isinstance(observed, datetime):
                    day = observed.astimezone(zone).date()
                    dates.update(day - timedelta(days=n) for n in range(3))
                    scopes.add(f'recovery_dates:{day}')
            elif isinstance(row, StrongWorkoutRow) and uid:
                scopes.add(f'strength:strong:{uid}')
            elif isinstance(row, ManualSession) and uid:
                scopes.add(f'strength:manual:{uid}')
            elif isinstance(row, RecoveryObservation) and facts.get('source_date'):
                scopes.add(f"recovery_dates:{facts['source_date']}")
            elif isinstance(row, IntensityAnchor) and facts.get('valid_from'):
                scopes.add(f"anchors:{facts['valid_from']}")
            elif isinstance(row, ProfileVersion):
                scopes.add('timezone')
            elif isinstance(row, (CalendarVersion, CalendarSessionRevision, StrengthRoutineSlot, Goal, Event, Block, BlockVersion, BlockDecision)):
                scopes.add('calendar')
                if isinstance(row, CalendarSessionRevision):
                    session.info.setdefault('metrics_plan_uids', set()).add(facts.get('session_uid'))
            elif isinstance(row, CoverageInterval) and facts.get('dataset') == 'activities':
                scopes.add(f"all:{facts['start_date']}")
            if facts.get('activity_id'):
                scopes.add(f"activity:{facts['activity_id']}")
            if isinstance(row, SymptomReport) and facts.get('checkin_id'):
                scopes.add(f"checkin:{facts['checkin_id']}")
            if isinstance(row, (SessionRpe, SessionCompletion)):
                for column, kind in (('strong_workout_id', 'strong'), ('manual_session_id', 'manual')):
                    if facts.get(column):
                        scopes.add(f"strength:{kind}:{facts[column]}")
            if isinstance(row, SessionCompletion):
                # Capture both old and new subject linkage before identity changes.
                session.info.setdefault('metrics_plan_uids', set()).add(facts.get('session_uid'))
                if not any(facts.get(key) for key in ('activity_id', 'strong_workout_id', 'manual_session_id')):
                    scopes.add('calendar')


def _before_commit(session: Session) -> None:
    if session.info.get('metrics_running') or session.in_nested_transaction():
        return
    session.flush()
    scopes = set(session.info.get('metrics_scopes', ()))
    if not scopes:
        return
    if session.scalar(select(AppState.planning_authority).where(AppState.id == 1)) != 'calendar':
        return
    from app.db import bump_data_revision
    with _refreshing(session):
        session.execute(select(AppState.id).where(AppState.id == 1).with_for_update())
        bump_data_revision(session)
        _refresh_scopes(session, scopes)
        session.flush()
    for key in ('metrics_scopes', 'metrics_dates', 'metrics_plan_uids', 'metrics_pending_sources'):
        session.info.pop(key, None)


_SCOPE_KEYS = ('metrics_scopes', 'metrics_dates', 'metrics_plan_uids')


def _save_nested_scopes(session: Session, transaction) -> None:
    if transaction.nested:
        transaction._metrics_inherited_scopes = {key: set(session.info.get(key, ())) for key in _SCOPE_KEYS}


def _restore_nested_scopes(session: Session, transaction) -> None:
    if transaction.nested:
        for key, value in getattr(transaction, '_metrics_inherited_scopes', {}).items():
            session.info[key] = value
    else:
        for key in _SCOPE_KEYS:
            session.info.pop(key, None)
    session.info.pop('metrics_pending_sources', None)
    session.info.pop('metrics_computed', None)


def _clear_transaction_scopes(session: Session, transaction) -> None:
    if transaction.parent is None:
        for key in (*_SCOPE_KEYS, 'metrics_pending_sources', 'metrics_running', 'metrics_computed', 'metrics_depth'):
            session.info.pop(key, None)


def install_triggers() -> None:
    listeners = (('before_flush', _before_flush), ('after_flush_postexec', _after_flush),
                 ('before_commit', _before_commit), ('after_transaction_create', _save_nested_scopes),
                 ('after_soft_rollback', _restore_nested_scopes), ('after_transaction_end', _clear_transaction_scopes))
    for name, listener in listeners:
        if not event.contains(Session, name, listener):
            event.listen(Session, name, listener)
