from __future__ import annotations

import importlib
import json
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from app.calendar_models import SessionCompletion
from app.db import global_write_lock
from app.fit_models import ActivityLap, ActivityStream, ActivityWorkoutStep, FitFile
from app.metric_models import MetricConfig
from app.metric_models import MetricResult as MetricResultRow
from app.metrics.contract import (
    MetricResultData,
    RunFact,
    Status,
    canonical_json,
    completion_association_hash,
    config_hash,
    sha256_json,
)
from app.models import (
    Activity,
    ActivityAnnotation,
    ActivitySource,
    CoverageInterval,
    RawObject,
    SourceRecord,
)
from app.read.activities import eligible_runs, latest_annotation
from app.read.calendar import head_version, latest_revision
from app.services.timezone import athlete_tz

METRIC_MODULES = (
    "volume",
    "long_run",
    "srpe",
    "symptoms",
    "intensity",
    "intervals",
    "recovery",
    "planned_actual",
    "spacing",
    "aerobic",
)


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
            raise ValueError("duplicate_metric_registration")
        REGISTRY[metric_id] = RegisteredMetric(metric_id, method_version, depends_on, compute)
        return compute

    return decorator


def ordered_registry() -> list[RegisteredMetric]:
    ordered: list[RegisteredMetric] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(metric_id: str) -> None:
        if metric_id not in REGISTRY:
            raise ValueError("unknown_metric_dependency")
        if metric_id in visiting:
            raise ValueError("metric_dependency_cycle")
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


def _decoded_row(row: Any) -> dict[str, Any]:
    return {
        column.key: getattr(row, column.key)
        for column in row.__table__.columns
        if column.key not in {"id", "activity_id"}
    }


def _activity_identities(
    session: Session, activities: Sequence[Activity], annotations: Mapping[uuid.UUID, ActivityAnnotation]
) -> dict[uuid.UUID, tuple[str, dict[str, Any]]]:
    """`(source_revision, source_refs)` per activity, with one query per provenance table."""
    ids = [activity.id for activity in activities]
    if not ids:
        return {}
    sources: dict[uuid.UUID, list[dict[str, Any]]] = {uid: [] for uid in ids}
    for link, source, raw in session.execute(
        select(ActivitySource, SourceRecord, RawObject)
        .join(SourceRecord, ActivitySource.source_record_id == SourceRecord.id)
        .outerjoin(RawObject, SourceRecord.raw_object_id == RawObject.id)
        .where(ActivitySource.activity_id.in_(ids))
        .order_by(ActivitySource.activity_id, SourceRecord.id)
    ):
        sources[link.activity_id].append(
            {
                "source_record_id": str(source.id),
                "payload_hash": source.payload_hash,
                "source_modified_at": source.source_modified_at.isoformat() if source.source_modified_at else None,
                "parser_version": source.parser_version,
                "raw_sha256": raw.sha256 if raw else None,
                "selected_fields": link.selected_fields,
            }
        )
    fits = {row.activity_id: row for row in session.scalars(select(FitFile).where(FitFile.activity_id.in_(ids)))}
    streams = {
        row.activity_id: row
        for row in session.scalars(select(ActivityStream).where(ActivityStream.activity_id.in_(ids)))
    }
    laps: dict[uuid.UUID, list[dict[str, Any]]] = {uid: [] for uid in ids}
    for lap in session.scalars(
        select(ActivityLap)
        .where(ActivityLap.activity_id.in_(ids))
        .order_by(ActivityLap.activity_id, ActivityLap.lap_index)
    ):
        laps[lap.activity_id].append(_decoded_row(lap))
    steps: dict[uuid.UUID, list[dict[str, Any]]] = {uid: [] for uid in ids}
    for step in session.scalars(
        select(ActivityWorkoutStep)
        .where(ActivityWorkoutStep.activity_id.in_(ids))
        .order_by(ActivityWorkoutStep.activity_id, ActivityWorkoutStep.message_index)
    ):
        steps[step.activity_id].append(_decoded_row(step))
    identities: dict[uuid.UUID, tuple[str, dict[str, Any]]] = {}
    for activity in activities:
        uid, stream, fit = activity.id, streams.get(activity.id), fits.get(activity.id)
        decoded = {"stream": _decoded_row(stream) if stream else None, "laps": laps[uid], "steps": steps[uid]}
        flags = list(stream.quality_flags) if stream else []
        fit_refs: dict[str, Any] = (
            {"normalized_hash": sha256_json(decoded), "quality_flags": flags}
            if fit is None
            else {
                "normalized_hash": sha256_json(decoded),
                "id": str(fit.id),
                "fit_sha256": fit.fit_sha256,
                "zip_sha256": fit.zip_sha256,
                "raw_object_id": str(fit.raw_object_id),
                "sdk_version": fit.sdk_version,
                "profile_version": fit.profile_version,
                "quality_flags": flags,
            }
        )
        annotation = annotations.get(uid)
        refs = {
            "id": str(uid),
            "canonical_revision": activity.canonical_revision,
            "fit_status": activity.fit_status,
            "facts": {
                name: getattr(activity, name)
                for name in (
                    "start_at",
                    "end_at",
                    "sport",
                    "timer_s",
                    "elapsed_s",
                    "distance_m",
                    "source_workout_label",
                    "resolution_state",
                )
            },
            "annotation": {"excluded": annotation.excluded, "workout_label": annotation.workout_label}
            if annotation
            else None,
            "annotation_version": annotation.version if annotation else None,
            "source_records": sources[uid],
            "field_provenance": activity.field_provenance or {},
            "fit": fit_refs,
        }
        identities[uid] = (sha256_json(refs), refs)
    return identities


def load_runs(session: Session, start_date: date | None = None, end_date_excl: date | None = None) -> list[RunFact]:
    runs = eligible_runs(session, start_date, end_date_excl)
    identities = _activity_identities(
        session, [run.activity for run in runs], {run.activity.id: run.annotation for run in runs if run.annotation}
    )
    result: list[RunFact] = []
    for run in runs:
        activity, annotation = run.activity, run.annotation
        source_revision, refs = identities[activity.id]
        result.append(
            RunFact(
                activity.id,
                activity.start_at,
                activity.end_at,
                run.local_date,
                activity.sport,
                activity.timer_s,
                activity.distance_m,
                annotation.workout_label if annotation and annotation.workout_label else activity.source_workout_label,
                refs,
                source_revision,
            )
        )
    return result


def activities_coverage_complete(session: Session, start_date: date, end_date_excl: date) -> bool:
    if start_date >= end_date_excl:
        return True
    intervals = session.scalars(
        select(CoverageInterval)
        .where(
            CoverageInterval.dataset == "activities",
            CoverageInterval.status == "complete",
            CoverageInterval.fully_enumerated.is_(True),
            CoverageInterval.end_date >= start_date,
            CoverageInterval.start_date < end_date_excl,
        )
        .order_by(CoverageInterval.start_date)
    ).all()
    covered_until = start_date
    for interval in intervals:
        if interval.start_date > covered_until:
            return False
        covered_until = max(covered_until, interval.end_date + timedelta(days=1))
        if covered_until >= end_date_excl:
            return True
    return False


def latest_results(
    session: Session, metric_id: str, method_version: str, subject_keys: list[str] | tuple[str, ...]
) -> dict[str, MetricResultRow]:
    if not subject_keys:
        return {}
    rows = session.scalars(
        select(MetricResultRow).where(
            MetricResultRow.metric_id == metric_id,
            MetricResultRow.method_version == method_version,
            MetricResultRow.subject_key.in_(subject_keys),
            MetricResultRow.is_current.is_(True),
        )
    ).all()
    return {row.subject_key: row for row in rows}


def current_results(session: Session, metric_id: str, subject_keys: Sequence[str]) -> dict[str, MetricResultRow]:
    metric_modules()
    if metric_id not in REGISTRY:
        raise ValueError("unknown_metric")
    return latest_results(session, metric_id, REGISTRY[metric_id].method_version, list(subject_keys))


_WINDOW_PART = re.compile(r"(w\d+:\d{4}-\d{2}-\d{2}):(?:run|strength)")


def registered_config_hash(metric_id: str) -> str:
    for module in metric_modules():
        if module.METRIC_ID == metric_id:
            return config_hash(module.CONFIG)
    raise ValueError("unknown_metric")


def result_data(row: MetricResultRow) -> dict[str, Any]:
    return {column.key: getattr(row, column.key) for column in MetricResultRow.__table__.columns}


def _preview(data: MetricResultData, dependency_hash: str, calculated_at: datetime) -> dict[str, Any]:
    """Return a result in the stored row's shape, with no saved identity."""
    return {
        "id": None,
        "metric_id": data.metric_id,
        "method_version": data.method_version,
        "subject_type": data.subject_type,
        "subject_key": data.subject_key,
        "window_start": data.window_start,
        "window_end": data.window_end,
        "window_label": data.window_label,
        "status": str(data.status),
        "quality_status": str(data.quality_status) if data.quality_status else None,
        "value": data.value,
        "unit": data.unit,
        "reason_codes": list(data.reason_codes),
        "quality_flags": list(data.quality_flags),
        "source_refs": data.source_refs,
        "anchor_keys": list(data.anchor_keys),
        "config_hash": data.config_hash,
        "anchor_set_hash": data.anchor_set_hash,
        "calculated_at": data.calculated_at or calculated_at,
        "dependency_hash": dependency_hash,
        "timezone": data.timezone,
        "is_current": False,
    }


def read_results(session: Session, metric_id: str, subject_keys: Sequence[str]) -> dict[str, dict[str, Any] | None]:
    """Read each subject using the registered method and configuration.

    Missing or outdated rows are computed in memory with a null ID. Subjects
    without a result map to None. Run and strength windows share one calculation.
    """
    expected = registered_config_hash(metric_id)
    stored = current_results(session, metric_id, subject_keys)
    timezone: str | None = None
    calculated_at = session.info.get("metrics_now") or datetime.now(UTC)
    computed: dict[str, list[MetricResultData]] = {}
    found: dict[str, dict[str, Any] | None] = {}
    for key in dict.fromkeys(subject_keys):
        row = stored.get(key)
        if row is not None and row.config_hash == expected:
            found[key] = result_data(row)
            continue
        timezone = timezone or _profile_timezone(session)
        part = _WINDOW_PART.fullmatch(key)
        base = part[1] if part else key
        if base not in computed:
            computed[base] = REGISTRY[metric_id].compute(session, base)
        raw = next((item for item in computed[base] if item.subject_key == key), None)
        found[key] = None if raw is None else _preview(*_prepare(raw, timezone), calculated_at)
    return found


def current_result_filter() -> ColumnElement[bool]:
    """Select current rows for the registered version of each metric."""
    metric_modules()
    versions = [(metric.metric_id, metric.method_version) for metric in REGISTRY.values()]
    return and_(
        MetricResultRow.is_current.is_(True),
        tuple_(MetricResultRow.metric_id, MetricResultRow.method_version).in_(versions),
    )


def ensure_metric_config(session: Session, metric_id: str, method_version: str, config: Mapping[str, Any]) -> str:
    digest = config_hash(config)
    stmt = (
        insert(MetricConfig)
        .values(
            id=uuid.uuid4(), metric_id=metric_id, method_version=method_version, config=dict(config), config_hash=digest
        )
        .on_conflict_do_nothing(index_elements=["metric_id", "method_version", "config_hash"])
    )
    session.execute(stmt)
    return digest


def _result_dependency(result: MetricResultData) -> tuple[str, bool]:
    refs = result.source_refs
    required = bool(result.config_hash) and bool(result.timezone)
    identities = (
        isinstance(refs.get("activity"), dict)
        and bool(refs["activity"].get("id"))
        and bool(refs["activity"].get("source_revision")),
        isinstance(refs.get("plan"), dict)
        and bool(refs["plan"].get("revision_id"))
        and refs["plan"].get("calendar_version") is not None,
        isinstance(refs.get("checkin"), dict)
        and bool(refs["checkin"].get("id"))
        and refs["checkin"].get("version") is not None,
        isinstance(refs.get("recovery"), (dict, list)) and bool(refs["recovery"]),
        isinstance(refs.get("source_records"), list)
        and any(isinstance(row, dict) and row.get("payload_hash") for row in refs["source_records"]),
        isinstance(refs.get("sources"), (dict, list)) and bool(refs["sources"]),
        isinstance(refs.get("input_hash"), str) and bool(refs["input_hash"]),
        isinstance(refs.get("completion_association_hash"), str) and bool(refs["completion_association_hash"]),
    )
    required = required and any(identities)
    return sha256_json(
        {
            "source_refs": refs,
            "config_hash": result.config_hash,
            "anchor_set_hash": result.anchor_set_hash,
            "timezone": result.timezone,
            "calculator_dependency_hash": result.dependency_hash,
        }
    ), required


def _prepare(raw: MetricResultData, timezone: str) -> tuple[MetricResultData, str]:
    """Normalize a result for storage or preview and calculate its dependency hash."""
    supplied = replace(
        raw,
        timezone=raw.timezone or timezone,
        source_refs=json.loads(canonical_json(raw.source_refs)),
        value=json.loads(canonical_json(raw.value)),
    )
    dependency_hash, complete = _result_dependency(supplied)
    if complete:
        return supplied, dependency_hash
    return (
        replace(
            supplied,
            status=Status.invalid,
            value=None,
            reason_codes=tuple(dict.fromkeys((*supplied.reason_codes, "MISSING_PROVENANCE"))),
        ),
        sha256_json({"missing_provenance": True, "computed": dependency_hash}),
    )


def upsert_results(session: Session, results: list[MetricResultData]) -> None:
    if not results:
        return
    global_write_lock(session)
    calculated_at = session.info.get("metrics_now") or datetime.now(UTC)
    timezone = _profile_timezone(session)
    for raw in results:
        supplied, dependency_hash = _prepare(raw, timezone)
        session.query(MetricResultRow).filter(
            MetricResultRow.metric_id == supplied.metric_id,
            MetricResultRow.method_version == supplied.method_version,
            MetricResultRow.subject_key == supplied.subject_key,
            MetricResultRow.is_current.is_(True),
        ).update({"is_current": False}, synchronize_session="fetch")
        existing = session.scalar(
            select(MetricResultRow).where(
                MetricResultRow.metric_id == supplied.metric_id,
                MetricResultRow.method_version == supplied.method_version,
                MetricResultRow.subject_key == supplied.subject_key,
                MetricResultRow.config_hash == supplied.config_hash,
                func.coalesce(MetricResultRow.anchor_set_hash, "") == (supplied.anchor_set_hash or ""),
                MetricResultRow.dependency_hash == dependency_hash,
            )
        )
        values = {
            "window_start": supplied.window_start,
            "window_end": supplied.window_end,
            "window_label": supplied.window_label,
            "status": str(supplied.status),
            "quality_status": str(supplied.quality_status) if supplied.quality_status else None,
            "value": supplied.value,
            "unit": supplied.unit,
            "reason_codes": list(supplied.reason_codes),
            "quality_flags": list(supplied.quality_flags),
            "source_refs": supplied.source_refs,
            "anchor_keys": list(supplied.anchor_keys),
            "calculated_at": supplied.calculated_at or calculated_at,
            "is_current": True,
        }
        if existing:
            existing.is_current = True
        else:
            session.add(
                MetricResultRow(
                    metric_id=supplied.metric_id,
                    method_version=supplied.method_version,
                    subject_type=supplied.subject_type,
                    subject_key=supplied.subject_key,
                    config_hash=supplied.config_hash,
                    anchor_set_hash=supplied.anchor_set_hash,
                    dependency_hash=dependency_hash,
                    timezone=supplied.timezone,
                    **values,
                )
            )
        session.flush()


def metric_source_refs(
    session: Session, activity_id: uuid.UUID, session_uid: uuid.UUID | None = None, calendar_version: int | None = None
) -> dict[str, Any]:
    activity = session.get(Activity, activity_id)
    if activity is None:
        raise ValueError("activity_not_found")
    annotation = latest_annotation(session, activity_id)
    source_revision, activity_refs = _activity_identities(
        session, [activity], {activity_id: annotation} if annotation else {}
    )[activity_id]
    selected_version = head_version(session) if calendar_version is None else calendar_version
    plan: dict[str, Any] | None = None
    revision = latest_revision(session, session_uid, selected_version) if session_uid else None
    if revision and not revision.deleted:
        plan = {
            "session_uid": str(session_uid),
            "revision_id": str(revision.id),
            "calendar_version": selected_version,
            "structure_hash": sha256_json(revision.structure),
        }
    completion = (
        session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == session_uid))
        if session_uid
        else None
    )
    return {
        "activity": {"id": str(activity_id), "source_revision": source_revision, "source_refs": activity_refs},
        "fit": activity_refs["fit"],
        "plan": plan,
        "completion_association_hash": completion_association_hash(completion) if completion else None,
    }


def metric_modules() -> tuple[Any, ...]:
    return tuple(importlib.import_module(f"app.metrics.{name}") for name in METRIC_MODULES)


def ensure_configs(session: Session) -> None:
    for module in metric_modules():
        ensure_metric_config(session, module.METRIC_ID, module.METHOD_VERSION, module.CONFIG)
