"""Read stored metrics or compute missing and outdated metrics in memory."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.core import envelope
from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.checkin_models import SessionRpe
from app.db import get_session, global_read_lock
from app.domain.local_time import date_in_zone
from app.domain.sports import RUN_SPORTS
from app.errors import fail
from app.fit_models import ActivityWorkoutStep
from app.metric_models import MetricConfig, MetricResult
from app.metrics import engine, refresh
from app.models import Activity
from app.read.calendar import head_version
from app.read.treadmill_intervals import activity_laps, confirmed_lap_paces
from app.read.workout_feedback import load_workout_feedback
from app.services import calendar, workout_progression
from app.services.timezone import athlete_tz

router = APIRouter()
WINDOW_DAYS = (7, 14, 28, 56)


def _window(start: date, end: date, limit: int | None = None) -> None:
    if start > end or (limit is not None and (end - start).days >= limit):
        fail("invalid_date_window", "Invalid date window")


def recovery_nights(session: Session, start: date | None, end: date | None) -> dict:
    global_read_lock(session)
    end = end or refresh.local_today(session)
    start = start or end - timedelta(days=6)
    _window(start, end, 92)
    keys = [f"night:{start + timedelta(days=offset)}" for offset in range((end - start).days + 1)]
    results = engine.read_results(session, "recovery_multisignal_summary", keys)
    nights = []
    for offset, key in enumerate(keys):
        row = results[key]
        assert row is not None
        nights.append(
            {
                **(row["value"] or {}),
                "local_date": start + timedelta(days=offset),
                "status": row["status"],
                "quality_status": row["quality_status"],
                "reason_codes": row["reason_codes"],
                "quality_flags": row["quality_flags"],
            }
        )
    return {"start": start, "end": end, "nights": nights}


def activity_execution(session: Session, activity_id: UUID) -> dict:
    global_read_lock(session)
    activity = session.get(Activity, activity_id, populate_existing=True)
    if activity is None:
        fail("activity_not_found", "Activity not found", 404)
    if activity.sport not in RUN_SPORTS:
        fail("not_run_activity", "Activity is not a run")
    completion = session.scalar(select(SessionCompletion).where(SessionCompletion.activity_id == activity_id))
    activity_key = str(activity_id)
    metrics = {
        metric: engine.read_results(session, metric, [activity_key])[activity_key]
        for metric in (
            "work_interval_execution",
            "intensity_time_distribution",
            "aerobic_efficiency",
            "session_rpe_load",
            "symptom_response_timeline",
        )
    }
    planned_actual = None
    if completion and completion.session_uid:
        session_key = str(completion.session_uid)
        planned_actual = engine.read_results(session, "planned_actual_session", [session_key])[session_key]
    head = head_version(session, populate_existing=True)
    planned = (
        next(
            (
                row
                for row in calendar.state_at(session, head)
                if completion and row["session_uid"] == completion.session_uid
            ),
            None,
        )
        if head
        else None
    )
    if planned is None and completion and completion.session_uid and head:
        # An imported, completed legacy session can be absent from current
        # membership while its original prescription remains part of history.
        historical = session.scalar(
            select(CalendarSessionRevision).where(
                CalendarSessionRevision.session_uid == completion.session_uid,
                CalendarSessionRevision.calendar_version_number == 1,
                CalendarSessionRevision.deleted,
                CalendarSessionRevision.legacy_payload.is_not(None),
            )
        )
        if historical is not None:
            planned = calendar.row_data(historical)

    def value(metric: str) -> dict:
        row = metrics[metric]
        return (row["value"] or {}) if row else {}

    rpes = {
        row.source: row.rpe for row in session.scalars(select(SessionRpe).where(SessionRpe.activity_id == activity_id))
    }
    if "garmin_fit" not in rpes and activity.workout_rpe is not None:
        rpes["garmin_fit"] = activity.workout_rpe
    effective = rpes.get("manual", rpes.get("garmin_fit"))

    def decoded(rows: Any) -> list[dict]:
        return [
            {
                column.key: getattr(row, column.key)
                for column in row.__table__.columns
                if column.key not in {"id", "activity_id"}
            }
            for row in rows
        ]

    lap_rows = activity_laps(session, activity_id)
    laps = decoded(lap_rows)
    if activity.sport == "treadmill_running":
        confirmed_paces = confirmed_lap_paces(activity, lap_rows)
        for lap in laps:
            lap["confirmed_pace_s_per_mile"] = confirmed_paces.get(lap["lap_index"])
    watch_rows = session.scalars(
        select(ActivityWorkoutStep)
        .where(ActivityWorkoutStep.activity_id == activity_id)
        .order_by(ActivityWorkoutStep.message_index)
    )

    return {
        "activity": {
            "id": activity.id,
            "start_at": activity.start_at,
            "end_at": activity.end_at,
            "local_date": date_in_zone(activity.start_at, athlete_tz(session)),
            "sport": activity.sport,
            "distance_m": activity.distance_m,
            "timer_s": activity.timer_s,
            "elapsed_s": activity.elapsed_s,
            "fit_status": activity.fit_status,
        },
        "planned": planned,
        "completion": calendar.completion_data(session, completion) if completion else None,
        "laps": laps,
        "watch_steps": decoded(watch_rows),
        "planned_actual": planned_actual,
        "intervals": metrics["work_interval_execution"],
        "intensity": metrics["intensity_time_distribution"],
        "aerobic": metrics["aerobic_efficiency"],
        "rpe": {
            "effective": effective,
            "source": "manual" if "manual" in rpes else "garmin_fit" if "garmin_fit" in rpes else None,
            "manual": rpes.get("manual"),
            "garmin_fit": rpes.get("garmin_fit"),
            "srpe_load_au": value("session_rpe_load").get("load_au"),
        },
        "delayed_response": load_workout_feedback(session, [activity_id], refresh.clock(session)).get(activity_id),
        "symptoms": value("symptom_response_timeline").get("reports", []),
    }


def explain_metric(session: Session, result_id: UUID) -> dict:
    row = session.get(MetricResult, result_id)
    if row is None:
        fail("metric_result_not_found", "Metric result not found", 404)
    config = session.scalar(
        select(MetricConfig).where(
            MetricConfig.metric_id == row.metric_id,
            MetricConfig.method_version == row.method_version,
            MetricConfig.config_hash == row.config_hash,
        )
    )
    return {
        **engine.result_data(row),
        "config": config.config if config else None,
        "source_availability": {
            "config_available": config is not None,
            "provenance_complete": "MISSING_PROVENANCE" not in row.reason_codes,
        },
    }


def long_run_history(session: Session, start: date, end: date) -> list[dict]:
    _window(start, end)
    global_read_lock(session)
    keys = [str(uid) for uid in refresh.activities_between(session, start, end)]
    rows = [
        row
        for row in engine.read_results(session, "long_run_exposure", keys).values()
        if row and row["value"] and row["value"].get("classification") == "long"
    ]
    return sorted(rows, key=lambda row: (row["window_start"] is None, row["window_start"], row["subject_key"]))


def workout_progression_data(session: Session, start: date | None, end: date | None, group_by: str) -> dict:
    global_read_lock(session)
    today = refresh.local_today(session)
    end = min(end or today, today)
    start = start or end - timedelta(days=179)
    _window(start, end, 366)
    return {
        "start": start,
        "end": end,
        "group_by": group_by,
        "groups": workout_progression.progression_groups(session, start, end, group_by),
    }


def activity_workout_history(session: Session, activity_id: UUID, limit: int) -> dict:
    global_read_lock(session)
    activity = session.get(Activity, activity_id)
    if activity is None:
        fail("activity_not_found", "Activity not found", 404)
    if activity.sport not in RUN_SPORTS:
        fail("not_run_activity", "Activity is not a run")
    return workout_progression.workout_history(session, activity, limit)


@router.get("/metrics/windows")
def get_windows(as_of: date | None = None, session: Session = Depends(get_session)) -> dict:
    global_read_lock(session)
    as_of = as_of or refresh.local_today(session)
    window_keys = [f"w{n}:{as_of}" for n in WINDOW_DAYS]
    volume = engine.read_results(session, "run_volume_frequency", window_keys)
    intensity = engine.read_results(session, "intensity_time_distribution", window_keys)
    long_run = engine.read_results(session, "long_run_exposure", window_keys)
    srpe = engine.read_results(
        session, "session_rpe_load", [f"{key}:{part}" for key in window_keys for part in ("run", "strength")]
    )
    windows = [
        {
            "days": n,
            "volume": volume[key],
            "srpe": srpe[f"{key}:run"],
            "srpe_strength": srpe[f"{key}:strength"],
            "intensity": intensity[key],
            "long_run": long_run[key],
        }
        for n, key in zip(WINDOW_DAYS, window_keys, strict=True)
    ]
    spacing_key, symptoms_key = f"w14:{as_of}", f"w28:{as_of}"
    aerobic_keys = {f"w{n}": f"w{n}:{as_of}" for n in (28, 84)}
    aerobic = engine.read_results(session, "aerobic_efficiency", list(aerobic_keys.values()))
    data = {
        "as_of": as_of,
        "windows": windows,
        "spacing": engine.read_results(session, "hard_session_spacing", [spacing_key])[spacing_key],
        "aerobic": {label: aerobic[key] for label, key in aerobic_keys.items()},
        "symptoms": engine.read_results(session, "symptom_response_timeline", [symptoms_key])[symptoms_key],
    }
    return envelope(session, data)


@router.get("/metrics/recovery")
def get_recovery(start: date | None = None, end: date | None = None, session: Session = Depends(get_session)) -> dict:
    data = recovery_nights(session, start, end)
    return envelope(session, data)


@router.get("/activities/{activity_id}/execution")
def get_execution(activity_id: UUID, session: Session = Depends(get_session)) -> dict:
    data = activity_execution(session, activity_id)
    return envelope(session, data)


@router.get("/metrics/long-runs")
def get_long_runs(start: date, end: date, session: Session = Depends(get_session)) -> dict:
    data = long_run_history(session, start, end)
    return envelope(session, data)


@router.get("/metrics/workout-progression")
def get_workout_progression(
    start: date | None = None,
    end: date | None = None,
    group_by: Literal["signature", "recipe"] = "signature",
    session: Session = Depends(get_session),
) -> dict:
    data = workout_progression_data(session, start, end, group_by)
    return envelope(session, data)


@router.get("/activities/{activity_id}/workout-history")
def get_workout_history(
    activity_id: UUID, limit: int = Query(6, ge=2, le=20), session: Session = Depends(get_session)
) -> dict:
    data = activity_workout_history(session, activity_id, limit)
    return envelope(session, data)
