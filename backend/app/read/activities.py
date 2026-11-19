"""Activity reads shared by services, metrics, and the API."""
from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import UTC, date, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.local_time import date_in_zone
from app.domain.sports import RUN_SPORTS
from app.models import Activity, ActivityAnnotation
from app.services.timezone import athlete_tz


class EligibleRun(NamedTuple):
    activity: Activity
    annotation: ActivityAnnotation | None
    local_date: date


def latest_annotations(session: Session, activity_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, ActivityAnnotation]:
    if not activity_ids:
        return {}
    rows = session.scalars(select(ActivityAnnotation).where(ActivityAnnotation.activity_id.in_(activity_ids))
                           .order_by(ActivityAnnotation.activity_id, ActivityAnnotation.version))
    return {row.activity_id: row for row in rows}


def latest_annotation(session: Session, activity_id: uuid.UUID) -> ActivityAnnotation | None:
    return latest_annotations(session, [activity_id]).get(activity_id)


def eligible_runs(session: Session, start_date: date | None = None,
                  end_date_excl: date | None = None) -> list[EligibleRun]:
    """Resolved, not-excluded runs whose athlete-local date is in [start_date, end_date_excl), oldest first.

    A missing bound means unbounded on that side.
    """
    zone = athlete_tz(session)
    query = select(Activity).where(Activity.sport.in_(RUN_SPORTS), Activity.resolution_state == 'resolved')
    if start_date is not None:
        query = query.where(Activity.start_at >= datetime.combine(
            start_date - timedelta(days=1), datetime.min.time(), tzinfo=zone).astimezone(UTC))
    if end_date_excl is not None:
        query = query.where(Activity.start_at < datetime.combine(
            end_date_excl + timedelta(days=1), datetime.min.time(), tzinfo=zone).astimezone(UTC))
    activities = session.scalars(query.order_by(Activity.start_at, Activity.id)).all()
    annotations = latest_annotations(session, [activity.id for activity in activities])
    result: list[EligibleRun] = []
    for activity in activities:
        local = date_in_zone(activity.start_at, zone)
        if (start_date is not None and local < start_date) or (end_date_excl is not None and local >= end_date_excl):
            continue
        annotation = annotations.get(activity.id)
        if annotation is not None and annotation.excluded:
            continue
        result.append(EligibleRun(activity, annotation, local))
    return result
