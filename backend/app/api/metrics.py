"""Training metric read models. Refreshes persist derived data only."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.core import envelope, fail
from app.calendar_models import SessionCompletion
from app.checkin_models import SessionRpe
from app.db import get_session
from app.fit_models import ActivityLap, ActivityWorkoutStep
from app.metric_models import MetricConfig, MetricResult
from app.metrics import engine
from app.models import Activity, AppState
from app.services import calendar

router = APIRouter()


def metric_data(row: MetricResult | None) -> dict | None:
    return {column.key: getattr(row, column.key) for column in MetricResult.__table__.columns} if row else None


def current(session: Session, metric: str, key: str) -> MetricResult | None:
    return session.scalar(select(MetricResult).where(MetricResult.metric_id == metric,
        MetricResult.method_version == 'v1', MetricResult.subject_key == key, MetricResult.is_current))


def _window(start: date, end: date, limit: int | None = None) -> None:
    if start > end or (limit is not None and (end - start).days >= limit):
        fail('invalid_date_window', 'Invalid date window')


def recovery_nights(session: Session, start: date, end: date) -> dict:
    _window(start, end, 92)
    engine.ensure_nights(session, start, end)
    nights = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        row = current(session, 'recovery_multisignal_summary', f'night:{day}')
        assert row is not None
        nights.append({**(row.value or {}), 'local_date': day, 'status': row.status,
            'quality_status': row.quality_status, 'reason_codes': row.reason_codes, 'quality_flags': row.quality_flags})
    return {'start': start, 'end': end, 'nights': nights}


def activity_execution(session: Session, activity_id: UUID) -> dict:
    session.execute(text('SELECT pg_advisory_xact_lock(71382413)'))
    activity = session.get(Activity, activity_id, populate_existing=True)
    if activity is None:
        fail('activity_not_found', 'Activity not found', 404)
    if activity.sport not in ('running', 'trail_running', 'treadmill_running'):
        fail('not_run_activity', 'Activity is not a run')
    with engine._refreshing(session):
        engine._refresh_runs(session, [activity_id])
        completion = session.scalar(select(SessionCompletion).where(SessionCompletion.activity_id == activity_id))
        if completion and completion.session_uid:
            engine._refresh_plans(session, [completion.session_uid])
        session.flush()
    head = session.scalar(select(AppState.calendar_head_version).where(AppState.id == 1)) or 0
    planned = next((row for row in calendar.state_at(session, head)
                    if completion and row['session_uid'] == completion.session_uid), None) if head else None
    def value(metric: str) -> dict:
        row = current(session, metric, str(activity_id))
        return row.value or {} if row else {}
    rpes = {row.source: row.rpe for row in session.scalars(select(SessionRpe).where(SessionRpe.activity_id == activity_id))}
    if 'garmin_fit' not in rpes and activity.workout_rpe is not None:
        rpes['garmin_fit'] = activity.workout_rpe
    effective = rpes.get('manual', rpes.get('garmin_fit'))
    def decoded(model: Any, index: str) -> list[dict]:
        rows: Any = session.scalars(select(model).where(model.activity_id == activity_id).order_by(getattr(model, index)))
        return [{column.key: getattr(row, column.key) for column in model.__table__.columns
                 if column.key not in {'id', 'activity_id'}} for row in rows]
    return {'activity': {'id': activity.id, 'start_at': activity.start_at, 'end_at': activity.end_at,
        'local_date': activity.start_at.astimezone(ZoneInfo(engine._profile_timezone(session))).date(),
        'sport': activity.sport, 'distance_m': activity.distance_m, 'timer_s': activity.timer_s,
        'elapsed_s': activity.elapsed_s, 'fit_status': activity.fit_status},
        'planned': planned, 'completion': calendar.completion_data(session, completion) if completion else None,
        'laps': decoded(ActivityLap, 'lap_index'), 'watch_steps': decoded(ActivityWorkoutStep, 'message_index'),
        'planned_actual': metric_data(current(session, 'planned_actual_session', str(completion.session_uid)))
            if completion and completion.session_uid else None,
        'intervals': metric_data(current(session, 'work_interval_execution', str(activity_id))),
        'intensity': metric_data(current(session, 'intensity_time_distribution', str(activity_id))),
        'rpe': {'effective': effective, 'source': 'manual' if 'manual' in rpes else 'garmin_fit' if 'garmin_fit' in rpes else None,
            'manual': rpes.get('manual'), 'garmin_fit': rpes.get('garmin_fit'),
            'srpe_load_au': value('session_rpe_load').get('load_au')},
        'symptoms': value('symptom_response_timeline').get('reports', [])}


def explain_metric(session: Session, result_id: UUID) -> dict:
    row = session.get(MetricResult, result_id)
    if row is None:
        fail('metric_result_not_found', 'Metric result not found', 404)
    config = session.scalar(select(MetricConfig).where(MetricConfig.metric_id == row.metric_id,
        MetricConfig.method_version == row.method_version, MetricConfig.config_hash == row.config_hash))
    return {**(metric_data(row) or {}), 'config': config.config if config else None,
        'source_availability': {'config_available': config is not None,
            'provenance_complete': 'MISSING_PROVENANCE' not in row.reason_codes}}


def long_run_history(session: Session, start: date, end: date) -> list[dict]:
    _window(start, end)
    ids = engine._activity_ids(session, start, end)
    with engine._refreshing(session):
        engine._refresh_runs(session, ids)
        session.flush()
    rows = session.scalars(select(MetricResult).where(MetricResult.metric_id == 'long_run_exposure',
        MetricResult.subject_type == 'activity', MetricResult.subject_key.in_([str(uid) for uid in ids]),
        MetricResult.is_current).order_by(MetricResult.window_start, MetricResult.subject_key))
    return [metric_data(row) for row in rows if row.value and row.value.get('classification') == 'long']  # type: ignore[misc]


@router.get('/metrics/windows')
def get_windows(as_of: date | None = None, session: Session = Depends(get_session)) -> dict:
    as_of = as_of or engine._today(session)
    engine.ensure_windows(session, as_of)
    def result(metric: str, key: str) -> dict | None:
        return metric_data(current(session, metric, key))
    windows = [{'days': n, 'volume': result('run_volume_frequency', f'w{n}:{as_of}'),
        'srpe': result('session_rpe_load', f'w{n}:{as_of}:run'),
        'srpe_strength': result('session_rpe_load', f'w{n}:{as_of}:strength'),
        'intensity': result('intensity_time_distribution', f'w{n}:{as_of}'),
        'long_run': result('long_run_exposure', f'w{n}:{as_of}')} for n in (7, 14, 28, 56)]
    data = {'as_of': as_of, 'windows': windows,
        'spacing': result('hard_session_spacing', f'w14:{as_of}'),
        'symptoms': result('symptom_response_timeline', f'w28:{as_of}')}
    session.commit()
    return envelope(session, data)


@router.get('/metrics/recovery')
def get_recovery(start: date | None = None, end: date | None = None, session: Session = Depends(get_session)) -> dict:
    end = end or engine._today(session)
    data = recovery_nights(session, start or end - timedelta(days=6), end)
    session.commit()
    return envelope(session, data)


@router.get('/activities/{activity_id}/execution')
def get_execution(activity_id: UUID, session: Session = Depends(get_session)) -> dict:
    data = activity_execution(session, activity_id)
    session.commit()
    return envelope(session, data)


@router.get('/metrics/explain/{result_id}')
def get_explain(result_id: UUID, session: Session = Depends(get_session)) -> dict:
    return envelope(session, explain_metric(session, result_id))


@router.get('/metrics/long-runs')
def get_long_runs(start: date, end: date, session: Session = Depends(get_session)) -> dict:
    data = long_run_history(session, start, end)
    session.commit()
    return envelope(session, data)
