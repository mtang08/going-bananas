"""Build the detector's plain-value inputs from the database."""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar_models import SessionCompletion
from app.checkin_models import Checkin, SessionRpe, SymptomReport
from app.domain.analytics import utc_date_bounds
from app.metrics.engine import load_runs
from app.metrics.symptoms import linked_activity_for_checkin
from app.models import Activity
from app.services.exceptions.facts import CheckinFact, DetectionInputs, RpeRun, SymptomFact
from app.services.exceptions.rules import CHECKIN_LOOKBACK_DAYS
from app.services.run_rpe import effective_run_rpe
from app.services.timezone import athlete_tz

RUN_DAYS = 21
SESSION_PAST_DAYS = 21
SESSION_FUTURE_DAYS = 6
RECOVERY_DAYS = 4


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _checkins(session: Session, now: datetime, today: date, zone: ZoneInfo) -> tuple[CheckinFact, ...]:
    start, _ = utc_date_bounds(today - timedelta(days=CHECKIN_LOOKBACK_DAYS - 1), today, zone.key)
    rows = session.scalars(select(Checkin).where(Checkin.observed_at >= start, Checkin.observed_at <= now)
                           .order_by(Checkin.observed_at, Checkin.recorded_at, Checkin.id)).all()
    symptoms: dict[uuid.UUID, list[SymptomReport]] = {}
    ids = [r.id for r in rows]
    if ids:
        for report in session.scalars(select(SymptomReport).where(SymptomReport.checkin_id.in_(ids))
                                      .order_by(SymptomReport.checkin_id, SymptomReport.id)):
            symptoms.setdefault(report.checkin_id, []).append(report)
    facts: list[CheckinFact] = []
    for r in rows:
        reports = symptoms.get(r.id, [])
        linked: str | None = None
        if r.activity_id is not None:
            linked = str(r.activity_id)
        elif reports:
            found = linked_activity_for_checkin(session, r)
            linked = str(found) if found else None
        facts.append(CheckinFact(
            id=str(r.id), kind=r.kind, observed_at=_utc(r.observed_at), recorded_at=_utc(r.recorded_at),
            local_date=r.observed_at.astimezone(zone).date(), fatigue=r.fatigue, illness=r.illness,
            gait_change=r.gait_change, context_tags=tuple(r.context_tags or ()),
            activity_id=str(r.activity_id) if r.activity_id else None, linked_activity_id=linked,
            symptoms=tuple(SymptomFact(str(s.id), s.site, s.side, float(s.severity), s.timing) for s in reports)))
    return tuple(facts)


def _runs(session: Session, run_facts: Sequence[Any], completions: Sequence[SessionCompletion]) -> tuple[RpeRun, ...]:
    ids = [f.activity_id for f in run_facts]
    if not ids:
        return ()
    rows_by_activity: dict[Any, list[SessionRpe]] = {}
    for row in session.scalars(select(SessionRpe).where(SessionRpe.activity_id.in_(ids))):
        rows_by_activity.setdefault(row.activity_id, []).append(row)
    workout = dict(session.execute(select(Activity.id, Activity.workout_rpe).where(Activity.id.in_(ids))).tuples().all())
    by_activity = {c.activity_id: c for c in completions if c.activity_id}
    out: list[RpeRun] = []
    for f in run_facts:
        rpe, source, rpe_at = effective_run_rpe(rows_by_activity.get(f.activity_id, []), workout.get(f.activity_id))
        link = by_activity.get(f.activity_id)
        out.append(RpeRun(str(f.activity_id), f.local_date, _utc(f.start_at), _utc(f.end_at) if f.end_at else None,
                          rpe, source, _utc(rpe_at) if rpe_at else None, str(link.session_uid) if link else None))
    return tuple(out)


def collect_detection_inputs(session: Session, now: datetime) -> DetectionInputs:
    zone = athlete_tz(session)
    today = now.astimezone(zone).date()
    run_facts = load_runs(session, today - timedelta(days=RUN_DAYS - 1), today + timedelta(days=1))
    completions = session.scalars(select(SessionCompletion)).all()
    return DetectionInputs(
        today=today,
        now=_utc(now),
        tz=zone.key,
        checkins=_checkins(session, now, today, zone),
        runs=_runs(session, run_facts, completions),
    )
