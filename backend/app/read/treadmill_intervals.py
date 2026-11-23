"""Lap identity for athlete-confirmed treadmill paces."""

from __future__ import annotations

from datetime import UTC
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fit_models import ActivityLap
from app.models import Activity


def activity_laps(session: Session, activity_id: UUID) -> list[ActivityLap]:
    return list(
        session.scalars(
            select(ActivityLap).where(ActivityLap.activity_id == activity_id).order_by(ActivityLap.lap_index)
        )
    )


def lap_identity(lap: ActivityLap) -> str:
    # FIT replay recreates row IDs. Use the recorded bounds and step association.
    start_at = lap.start_at.astimezone(UTC).isoformat()
    end_at = lap.end_at.astimezone(UTC).isoformat() if lap.end_at is not None else ""
    return f"{start_at}|{end_at}|{lap.elapsed_s}|{lap.timer_s}|{lap.wkt_step_index}"


def confirmed_lap_paces(activity: Activity, laps: list[ActivityLap]) -> dict[int, float]:
    saved = activity.treadmill_interval_paces
    if activity.sport != "treadmill_running" or not saved:
        return {}
    return {
        lap.lap_index: pace["pace_s_per_mile"]
        for lap in laps
        if (pace := saved.get(str(lap.lap_index))) and pace["lap_identity"] == lap_identity(lap)
    }
