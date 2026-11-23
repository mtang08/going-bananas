"""Persist athlete-confirmed lap paces alongside the imported activity."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Activity
from app.read.treadmill_intervals import activity_laps, lap_identity


def set_treadmill_interval_paces(session: Session, activity_id: UUID, paces: dict[int, float]) -> None:
    """Replace the confirmed paces, using lap indexes and seconds per mile."""
    activity = session.get(Activity, activity_id)
    if activity is None or activity.sport != "treadmill_running":
        raise ValueError("not_treadmill_activity")
    laps = {lap.lap_index: lap for lap in activity_laps(session, activity_id)}
    activity.treadmill_interval_paces = {
        str(index): {"lap_identity": lap_identity(laps[index]), "pace_s_per_mile": pace}
        for index, pace in paces.items()
    } or None
    session.flush()
