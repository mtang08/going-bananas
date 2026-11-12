from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.fit_models import ActivityStream, FitFile
from app.metric_models import MetricConfig
from app.metric_models import MetricResult as MetricResultRow
from app.metrics.contract import MetricResultData, RunFact, completion_association_hash, config_hash, sha256_json
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

METRIC_MODULES: tuple[str, ...] = ()


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


def recompute(session: Session, scope: str) -> list[MetricResultData]:
    parse_scope(scope)
    ordered = _ordered_registry()
    if not ordered:
        return []
    results: list[MetricResultData] = []
    for item in ordered:
        calculated = item.compute(session, scope)
        upsert_results(session, calculated)
        results.extend(calculated)
    return results


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
    if fit is None:
        return None
    stream = session.get(ActivityStream, activity_id)
    return {'id': str(fit.id), 'fit_sha256': fit.fit_sha256, 'zip_sha256': fit.zip_sha256,
            'raw_object_id': str(fit.raw_object_id), 'sdk_version': fit.sdk_version,
            'profile_version': fit.profile_version,
            'quality_flags': list(stream.quality_flags) if stream else []}


def _activity_identity(session: Session, activity: Activity,
                       annotation: ActivityAnnotation | None) -> tuple[str, dict[str, Any]]:
    refs = {'id': str(activity.id), 'canonical_revision': activity.canonical_revision,
            'fit_status': activity.fit_status,
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
    calculated_at = datetime.now(UTC)
    timezone = _profile_timezone(session)
    for raw in results:
        supplied = replace(raw, timezone=raw.timezone or timezone)
        dependency_hash, complete = _result_dependency(supplied)
        reason_codes = supplied.reason_codes
        status = str(supplied.status)
        if not complete:
            status = 'invalid'
            reason_codes = tuple(dict.fromkeys((*reason_codes, 'INPUT_PROVENANCE_MISSING')))
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
            existing.calculated_at = supplied.calculated_at or calculated_at
            existing.value = supplied.value if complete else None
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
