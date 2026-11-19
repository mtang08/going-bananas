"""Metric recomputation: which subjects a change touches, and the explicit refresh entry points.

The commit-time session listeners call `refresh_scopes`. Snapshot, CLI, and demo seed call
`ensure_windows`, `ensure_nights`, and `assess_completion` directly. Work outside a commit runs
inside `refreshing(session)`, which takes the global write lock and caches computed subjects.
"""
from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.db import global_write_lock
from app.metric_models import MetricResult as MetricResultRow
from app.metrics.contract import MetricResultData
from app.metrics.engine import (
    REGISTRY,
    current_result_filter,
    ensure_configs,
    metric_modules,
    ordered_registry,
    upsert_results,
)
from app.models import Activity, AppState
from app.services.timezone import athlete_today, athlete_tz


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


def clock(session: Session) -> datetime:
    return session.info.get('metrics_now') or datetime.now(UTC)


def local_today(session: Session) -> date:
    return athlete_today(session, clock(session))


@contextmanager
def refreshing(session: Session):
    depth = session.info.get('metrics_depth', 0)
    old_running = session.info.get('metrics_running', False)
    session.info['metrics_running'] = True
    session.info['metrics_depth'] = depth + 1
    try:
        if depth == 0:
            global_write_lock(session)
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
        calculated = [replace(row, calculated_at=clock(session)) for row in registration.compute(session, key)]
        if not calculated:
            session.query(MetricResultRow).filter(MetricResultRow.metric_id == metric_id,
                MetricResultRow.method_version == registration.method_version,
                MetricResultRow.subject_key == key, MetricResultRow.is_current.is_(True)).update(
                    {'is_current': False}, synchronize_session='fetch')
        upsert_results(session, calculated)
        cache.add((metric_id, key))
        results.extend(calculated)
    return results


def activities_between(session: Session, start: date, end: date) -> list[uuid.UUID]:
    zone = athlete_tz(session)
    rows = session.execute(select(Activity.id, Activity.start_at).where(
        Activity.start_at >= datetime.combine(start - timedelta(days=1), datetime.min.time(), tzinfo=zone),
        Activity.start_at < datetime.combine(end + timedelta(days=2), datetime.min.time(), tzinfo=zone))
        .order_by(Activity.start_at, Activity.id)).all()
    return [uid for uid, stamp in rows if start <= stamp.astimezone(zone).date() <= end]


def refresh_runs(session: Session, activity_ids: Iterable[uuid.UUID]) -> list[MetricResultData]:
    keys = [str(uid) for uid in dict.fromkeys(activity_ids)]
    run_metrics = {'symptom_response_timeline', 'session_rpe_load', 'long_run_exposure',
                   'intensity_time_distribution', 'work_interval_execution', 'aerobic_efficiency'}
    results = []
    for item in ordered_registry():
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


def refresh_plans(session: Session, uids: Iterable[uuid.UUID]) -> list[MetricResultData]:
    keys = list(dict.fromkeys(str(uid) for uid in uids))
    linked = list(session.scalars(select(SessionCompletion.activity_id).where(
        SessionCompletion.session_uid.in_([uuid.UUID(key) for key in keys]), SessionCompletion.activity_id.is_not(None))))
    refresh_runs(session, [uid for uid in linked if uid is not None])
    return compute_subjects(session, 'planned_actual_session', keys)


def assess_completion(session: Session, session_uid: uuid.UUID) -> None:
    with refreshing(session):
        refresh_plans(session, [session_uid])
        session.flush()


def ensure_nights(session: Session, start: date, end: date) -> None:
    if start > end:
        raise ValueError('invalid_date_window')
    with refreshing(session):
        compute_subjects(session, 'recovery_multisignal_summary',
                         [f'night:{start + timedelta(days=n)}' for n in range((end - start).days + 1)])


def ensure_windows(session: Session, as_of: date) -> None:
    with refreshing(session):
        start = as_of - timedelta(days=83)
        activity_ids = activities_between(session, start, as_of)
        refresh_runs(session, activity_ids)
        _refresh_strength(session, start, as_of)
        linked = session.scalars(select(SessionCompletion.session_uid).where(SessionCompletion.activity_id.in_(activity_ids)))
        refresh_plans(session, [*_plan_uids(session, as_of - timedelta(days=13), as_of + timedelta(days=13)), *linked])
        ensure_nights(session, as_of - timedelta(days=6), as_of)
        for metric_id in ('run_volume_frequency', 'long_run_exposure', 'session_rpe_load', 'intensity_time_distribution'):
            compute_subjects(session, metric_id, [f'w{n}:{as_of}' for n in (7, 14, 28, 56, 84)])
        compute_subjects(session, 'symptom_response_timeline', [f'w28:{as_of}'])
        compute_subjects(session, 'recovery_multisignal_summary', [f'w7:{as_of}'])
        compute_subjects(session, 'hard_session_spacing', [f'w14:{as_of}'])
        compute_subjects(session, 'aerobic_efficiency', [f'w{n}:{as_of}' for n in (28, 84)])
        session.flush()


def _all_dates(session: Session) -> set[date]:
    from app.models import ManualSession, RecoveryObservation
    from app.strong_models import StrongWorkoutRow
    zone = athlete_tz(session)
    dates = {stamp.astimezone(zone).date() for stamp in session.scalars(select(Activity.start_at))}
    dates.update(session.scalars(select(ManualSession.date)))
    dates.update(session.scalars(select(StrongWorkoutRow.local_date)))
    dates.update(session.scalars(select(RecoveryObservation.source_date)))
    dates.update(session.scalars(select(CalendarSessionRevision.local_date)))
    return dates


def refresh_scopes(session: Session, scopes: Iterable[str]) -> list[MetricResultData]:
    from app.checkin_models import Checkin
    from app.models import ManualSession
    from app.services.matching import rematch_dates
    from app.services.prompts import generate_prompts
    from app.strong_models import StrongWorkoutRow
    today = local_today(session)
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
                dates.add(row.start_at.astimezone(athlete_tz(session)).date())
        elif kind == 'checkin':
            checkin = session.get(Checkin, value)
            if checkin:
                day = checkin.observed_at.astimezone(athlete_tz(session)).date()
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
        activity_ids.update(activities_between(session, day - timedelta(days=2), day + timedelta(days=30)))
    if broad:
        activity_ids.update(session.scalars(select(Activity.id)))
    results = refresh_runs(session, sorted(activity_ids, key=str))
    results.extend(compute_subjects(session, 'session_rpe_load', sorted(strength_keys)))
    linked = session.scalars(select(SessionCompletion.session_uid).where(SessionCompletion.activity_id.in_(activity_ids)))
    strength_links: list[uuid.UUID] = []
    for key in strength_keys:
        kind, raw_id = key.split(':', 1)
        column = SessionCompletion.strong_workout_id if kind == 'strong' else SessionCompletion.manual_session_id
        strength_links.extend(session.scalars(select(SessionCompletion.session_uid).where(column == uuid.UUID(raw_id))))
    explicit_uids = [uid for uid in session.info.get('metrics_plan_uids', ()) if uid] + strength_links
    results.extend(refresh_plans(session, [*touched_uids, *linked, *explicit_uids, *(_plan_uids(session) if broad else ())]))
    as_ofs = {today}
    current = session.execute(select(MetricResultRow.subject_key, MetricResultRow.metric_id).where(
        current_result_filter(), MetricResultRow.subject_type.in_(('window', 'night')))).all()
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
    generate_prompts(session, clock(session))
    session.flush()
    return results


def recompute(session: Session, scope: str) -> list[MetricResultData]:
    parse_scope(scope)
    with refreshing(session):
        return refresh_scopes(session, [scope])
