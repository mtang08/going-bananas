from __future__ import annotations

import importlib
import json
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, event, func, inspect, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.db import global_write_lock
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
from app.services.timezone import athlete_tz

METRIC_MODULES = ('volume', 'long_run', 'srpe', 'symptoms', 'intensity', 'intervals', 'recovery', 'planned_actual', 'spacing', 'aerobic')


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


def ordered_registry() -> list[RegisteredMetric]:
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


def _profile_timezone(session: Session) -> str:
    return athlete_tz(session).key


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


def current_results(session: Session, metric_id: str, subject_keys: Sequence[str]) -> dict[str, MetricResultRow]:
    metric_modules()
    if metric_id not in REGISTRY:
        raise ValueError('unknown_metric')
    return latest_results(session, metric_id, REGISTRY[metric_id].method_version, list(subject_keys))


def current_result_filter() -> ColumnElement[bool]:
    """Select current rows for the registered version of each metric."""
    metric_modules()
    versions = [(metric.metric_id, metric.method_version) for metric in REGISTRY.values()]
    return and_(
        MetricResultRow.is_current.is_(True),
        tuple_(MetricResultRow.metric_id, MetricResultRow.method_version).in_(versions),
    )


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
    global_write_lock(session)
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


def enqueue_scopes(session: Session, scopes: Iterable[str]) -> None:
    from app.metrics.refresh import parse_scope
    values = list(scopes)
    for scope in values:
        parse_scope(scope)
    session.info.setdefault('metrics_scopes', set()).update(values)


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
    pending = session.info.setdefault('metrics_pending_sources', [])
    for row in rows:
        state = inspect(row)
        changes = {attribute.key for attribute in state.attrs if attribute.history.has_changes()}
        if isinstance(row, SessionCompletion) and state.persistent and changes <= {'status', 'version', 'updated_at'}:
            continue
        if state.persistent and row not in session.deleted:
            if not changes:
                continue
            # Retry diagnostics do not change the decoded FIT inputs.
            if isinstance(row, FitFile) and changes <= {'last_attempt_at', 'last_error'}:
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
    from app.db import bump_data_revision
    from app.metrics import refresh
    with refresh.refreshing(session):
        session.execute(select(AppState.id).where(AppState.id == 1).with_for_update())
        bump_data_revision(session)
        refresh.refresh_scopes(session, scopes)
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
