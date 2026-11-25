"""Delayed response and reminder state for recorded runs."""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.checkin_models import Checkin, SymptomReport
from app.metric_models import Prompt
from app.models import Activity

DELAYED_RESPONSE_HOURS = 16


def reminder_status(status: str, opens_at: datetime, closes_at: datetime | None, now: datetime) -> str:
    if status == "open":
        if opens_at > now:
            return "scheduled"
        if closes_at is not None and closes_at <= now:
            return "expired"
    return status


def load_workout_feedback(session: Session, activity_ids: Collection[UUID], now: datetime) -> dict[UUID, dict]:
    if not activity_ids:
        return {}
    prompts = session.scalars(
        select(Prompt).where(Prompt.kind == "delayed_symptom", Prompt.activity_id.in_(activity_ids))
    ).all()
    checkins: dict[UUID, Checkin] = {}
    for row in session.scalars(
        select(Checkin)
        .where(
            Checkin.kind == "delayed_followup",
            Checkin.activity_id.in_(activity_ids),
            Checkin.observed_at <= now,
            Checkin.recorded_at <= now,
        )
        .order_by(Checkin.observed_at.desc(), Checkin.recorded_at.desc(), Checkin.id.desc())
    ):
        if row.activity_id is not None:
            checkins.setdefault(row.activity_id, row)
    symptoms: dict[UUID, list[dict]] = {}
    if checkins:
        for report in session.scalars(
            select(SymptomReport)
            .where(SymptomReport.checkin_id.in_([row.id for row in checkins.values()]))
            .order_by(SymptomReport.id)
        ):
            symptoms.setdefault(report.checkin_id, []).append(
                {key: getattr(report, key) for key in ("site", "side", "severity", "timing")}
            )
    by_activity = {row.activity_id: row for row in prompts if row.activity_id is not None}
    relevant = by_activity.keys() | checkins.keys()
    if not relevant:
        return {}
    end_times = dict(
        session.execute(select(Activity.id, Activity.end_at).where(Activity.id.in_(relevant))).tuples().all()
    )
    result = {}
    for activity_id in relevant:
        checkin = checkins.get(activity_id)
        prompt = by_activity.get(activity_id)
        end_at = end_times.get(activity_id)
        result[activity_id] = {
            "prompt": {
                "id": prompt.id,
                "kind": prompt.kind,
                "activity_id": prompt.activity_id,
                "session_uid": prompt.session_uid,
                "opens_at": prompt.opens_at,
                "closes_at": prompt.closes_at,
                "status": reminder_status(prompt.status, prompt.opens_at, prompt.closes_at, now),
            }
            if prompt is not None
            else None,
            "checkin_id": checkin.id if checkin else None,
            "observed_at": checkin.observed_at if checkin else None,
            "recorded_at": checkin.recorded_at if checkin else None,
            "hours_after_end": (
                round((checkin.observed_at - end_at).total_seconds() / 3600, 1)
                if checkin is not None and end_at is not None and checkin.observed_at >= end_at
                else None
            ),
            "pain_reported": checkin.pain_reported if checkin else None,
            "gait_change": checkin.gait_change if checkin else None,
            "symptoms": symptoms.get(checkin.id, []) if checkin else [],
        }
    return result
