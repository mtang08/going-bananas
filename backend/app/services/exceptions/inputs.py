"""Build the detector's plain-value inputs from the database."""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarVersion, SessionCompletion
from app.checkin_models import Checkin, SessionRpe, SymptomReport
from app.domain.analytics import utc_date_bounds
from app.domain.athlete_facts import clinical_restriction
from app.domain.local_time import date_in_zone
from app.domain.session_class import classify, expected_rpe
from app.metrics.engine import current_results, load_runs
from app.metrics.recovery import SIGNALS
from app.metrics.symptoms import linked_activity_for_checkin
from app.models import Activity, AppState, ProfileVersion
from app.planning_models import Event
from app.services.block_benchmark import active_block_version, benchmark_spec, benchmark_status
from app.services.calendar import state_at
from app.services.exceptions.facts import (
    BlockBenchmarkFact,
    CheckinFact,
    DetectionInputs,
    EventFact,
    PlannedActualFact,
    RpeRun,
    SessionFact,
    SymptomFact,
)
from app.services.exceptions.rules import CHECKIN_LOOKBACK_DAYS, EVENT_REVIEW_DAYS
from app.services.proposals import derive_certainty
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
            local_date=date_in_zone(r.observed_at, zone), fatigue=r.fatigue, illness=r.illness,
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


def _sessions(session: Session, today: date, completions: Sequence[SessionCompletion]) -> tuple[SessionFact, ...]:
    state = session.get(AppState, 1)
    head = state.calendar_head_version if state else 0
    rows = [r for r in state_at(session, head)
            if today - timedelta(days=SESSION_PAST_DAYS) <= r['local_date'] <= today + timedelta(days=SESSION_FUTURE_DAYS)]
    numbers = {r['calendar_version_number'] for r in rows}
    created = dict(session.execute(select(CalendarVersion.number, CalendarVersion.created_at)
                                   .where(CalendarVersion.number.in_(numbers))).tuples().all()) if numbers else {}
    by_session = {c.session_uid: c for c in completions}
    out: list[SessionFact] = []
    for r in rows:
        cls = classify(r['kind'], r['recipe_id'], r['intent'])
        c = by_session.get(r['session_uid'])
        out.append(SessionFact(
            session_uid=str(r['session_uid']), local_date=r['local_date'], kind=r['kind'], recipe_id=r['recipe_id'],
            intent=r['intent'] or '', certainty=derive_certainty(r['local_date'], today), session_class=cls,
            expected_rpe=expected_rpe(r['recipe_id'], cls),
            completion_status=c.status if c else None, modification_reason=c.modification_reason if c else None,
            activity_id=str(c.activity_id) if c and c.activity_id else None,
            planned_at=_utc(created[r['calendar_version_number']]),
            completion_updated_at=_utc(c.updated_at) if c else None))
    return tuple(out)


def _planned_actual(session: Session, uids: list[str]) -> dict[str, PlannedActualFact]:
    out: dict[str, PlannedActualFact] = {}
    for row in current_results(session, 'planned_actual_session', uids).values():
        components = row.value.get('components', []) if isinstance(row.value, dict) else []
        coverage = next((c.get('status') for c in components if c.get('name') == 'target_coverage'), None)
        out[row.subject_key] = PlannedActualFact(tuple(row.reason_codes), coverage)
    return out


def _recovery_adverse(session: Session, today: date) -> frozenset[date]:
    nights = [f"night:{(today - timedelta(days=n)).isoformat()}" for n in range(RECOVERY_DAYS)]
    return frozenset(date.fromisoformat(row.subject_key.removeprefix('night:'))
                     for row in current_results(session, 'recovery_multisignal_summary', nights).values()
                     if isinstance(row.value, dict) and any(
                         isinstance(row.value.get(m), dict) and row.value[m].get('adverse') is True for m in SIGNALS))


def _events(session: Session, today: date, run_facts: Sequence[Any]) -> tuple[EventFact, ...]:
    rows = session.scalars(select(Event).where(Event.event_date >= today - timedelta(days=EVENT_REVIEW_DAYS),
                                               Event.event_date <= today).order_by(Event.event_date, Event.id)).all()
    out: list[EventFact] = []
    for e in rows:
        ends = [f.end_at for f in run_facts if f.local_date == e.event_date and f.end_at]
        out.append(EventFact(str(e.id), e.name, e.event_date, e.priority, e.status,
                             any(f.local_date == e.event_date for f in run_facts),
                             _utc(max(ends)) if ends else None))
    return tuple(out)


def _clinician(session: Session) -> tuple[str | None, datetime | None]:
    profiles = session.scalars(select(ProfileVersion).order_by(desc(ProfileVersion.version))).all()
    value = clinical_restriction(profiles[0].facts) if profiles else None
    at: datetime | None = None
    if value is not None:
        for p in profiles:
            if clinical_restriction(p.facts) != value:
                break
            at = p.recorded_at
    return value, _utc(at) if at else None


def _block_benchmark(session: Session, today: date) -> BlockBenchmarkFact | None:
    version = active_block_version(session)
    if version is None:
        return None
    st = benchmark_status(session, version, today)
    spec = benchmark_spec(version)
    return BlockBenchmarkFact(
        block_uid=str(version.block_uid), version=version.version, version_created_at=_utc(version.created_at),
        planned_date=spec.planned_date if spec else None, review_date=version.review_date,
        kind=spec.kind if spec else None, event_id=str(st.event_id) if st.event_id else None, status=st.status,
        activity_id=str(st.activity_id) if st.activity_id else None, local_date=st.local_date,
        evidence_at=_utc(st.evidence_at) if st.evidence_at else None, protocol=spec.protocol if spec else None,
        match_method=st.match_method, distance_m=st.distance_m, result_s=st.result_s, rpe=st.rpe)


def collect_detection_inputs(session: Session, now: datetime) -> DetectionInputs:
    zone = athlete_tz(session)
    today = date_in_zone(now, zone)
    run_facts = load_runs(session, today - timedelta(days=RUN_DAYS - 1), today + timedelta(days=1))
    completions = session.scalars(select(SessionCompletion)).all()
    sessions = _sessions(session, today, completions)
    restriction, restriction_at = _clinician(session)
    return DetectionInputs(
        today=today,
        now=_utc(now),
        tz=zone.key,
        checkins=_checkins(session, now, today, zone),
        runs=_runs(session, run_facts, completions),
        sessions=sessions,
        planned_actual=_planned_actual(session, [s.session_uid for s in sessions if s.local_date <= today]),
        recovery_adverse_dates=_recovery_adverse(session, today),
        events=_events(session, today, run_facts),
        block_benchmark=_block_benchmark(session, today),
        clinician_restriction=restriction,
        clinician_restriction_at=restriction_at,
    )
