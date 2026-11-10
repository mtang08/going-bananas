from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from datetime import date as DateType
from datetime import time as TimeType
from typing import Any, Literal, NoReturn
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import bump_data_revision, get_revision, get_session
from app.domain.analytics import (
    ActivityFact,
    aggregate,
    pace_s_per_km,
    summary,
    trailing_mean,
    utc_date_bounds,
    week_start,
)
from app.domain.associations import preceding_sessions
from app.domain.cycle import opportunities, validate_acceptance
from app.models import (
    Activity,
    ActivityAnnotation,
    ActivitySource,
    Checkin,
    CheckinRevision,
    CompletionLink,
    Conflict,
    CoverageInterval,
    ManualSession,
    PlannedSession,
    PlanVersion,
    ProfileVersion,
    RecoveryObservation,
    WeeklySnapshot,
)
from app.services.sync import detect_import_conflicts_for_manual

router = APIRouter()


def envelope(session: Session, data: Any) -> dict:
    return {'schema_version': 'v1', 'data_revision': get_revision(session), 'mode': settings.app_mode, 'data': data}


def fail(code: str, message: str, status: int = 422) -> NoReturn:
    raise HTTPException(status_code=status, detail={'code': code, 'message': message})


def current_profile(session: Session) -> ProfileVersion | None:
    return session.scalar(select(ProfileVersion).order_by(desc(ProfileVersion.version)).limit(1))


def profile_data(profile: ProfileVersion | None) -> dict:
    if profile is None:
        return {'version': 0, 'timezone': 'America/New_York', 'cycle_anchor': None,
                'anchor_confirmed': False, 'strength_days_confirmed': False,
                'scheduled_strength_days': [], 'facts': {}, 'preferences': {}, 'unknowns': []}
    return {key: getattr(profile, key) for key in ('version', 'timezone', 'cycle_anchor', 'anchor_confirmed',
            'strength_days_confirmed', 'scheduled_strength_days', 'facts', 'preferences', 'unknowns')}


def tz(session: Session) -> str:
    profile = current_profile(session)
    return profile.timezone if profile else 'America/New_York'


def date_window(session: Session, start_date: date | None, end_date: date | None) -> tuple[date, date]:
    today = datetime.now(ZoneInfo(tz(session))).date()
    end = end_date or today
    start = start_date or end - timedelta(days=27)
    if start > end or (end-start).days >= 366:
        fail('invalid_date_range', 'Date range must be ordered and at most 366 days')
    return start, end


def coverage(session: Session, start: date, end: date) -> list[dict]:
    rows = session.scalars(select(CoverageInterval).where(CoverageInterval.end_date >= start,
                    CoverageInterval.start_date <= end).order_by(CoverageInterval.dataset, CoverageInterval.start_date)).all()
    return [{'dataset': x.dataset, 'start_date': x.start_date, 'end_date': x.end_date,
             'status': x.status, 'fully_enumerated': x.fully_enumerated, 'completed_at': x.completed_at,
             'reason': x.reason} for x in rows]


def strength_coverage(session: Session, start: date, end: date) -> dict:
    profile = current_profile(session)
    source = (profile.preferences or {}).get('strength_source', 'unknown') if profile else 'unknown'
    manual_count = session.scalar(select(func.count()).select_from(ManualSession).where(
        ManualSession.kind == 'strength', ManualSession.date >= start, ManualSession.date <= end,
        ManualSession.linked_activity_id.is_(None))) or 0
    lo, hi = utc_date_bounds(start, end, tz(session))
    imported_count = session.scalar(select(func.count()).select_from(Activity).where(
        Activity.sport == 'strength', Activity.start_at >= lo, Activity.start_at < hi,
        Activity.resolution_state == 'resolved')) or 0
    if source == 'strong':
        return {'source': 'strong', 'status': 'unavailable', 'reason': 'strong_not_connected',
                'complete': False, 'observed_manual_count': manual_count,
                'observed_imported_count': imported_count}
    return {'source': source, 'status': 'partial', 'reason': 'strength_source_unverified',
            'complete': False, 'observed_manual_count': manual_count,
            'observed_imported_count': imported_count}


def annotation(session: Session, activity_id: uuid.UUID) -> ActivityAnnotation | None:
    return session.scalar(select(ActivityAnnotation).where(ActivityAnnotation.activity_id == activity_id)
                          .order_by(desc(ActivityAnnotation.version)).limit(1))


def activity_data(session: Session, a: Activity, detail: bool = False) -> dict:
    ann = annotation(session, a.id)
    label = ann.workout_label if ann and ann.workout_label else a.source_workout_label
    result = {'id': a.id, 'start_at': a.start_at, 'original_start': a.original_start,
              'local_date': a.start_at.astimezone(ZoneInfo(tz(session))).date(), 'source_local_date': a.local_date, 'sport': a.sport, 'subtype': a.subtype,
              'distance_m': a.distance_m, 'elapsed_s': a.elapsed_s, 'moving_s': a.moving_s,
              'moving_pace_s_per_km': pace_s_per_km(a.distance_m, a.moving_s),
              'workout_label': label or 'unknown', 'resolution_state': a.resolution_state,
              'source': 'garmin' if a.garmin_id else 'import', 'provenance': a.field_provenance,
              'annotations': {'version': ann.version if ann else 0, 'workout_label': ann.workout_label if ann else None,
                              'notes': ann.notes if ann else None, 'excluded': ann.excluded if ann else False}}
    if detail:
        links = session.scalars(select(ActivitySource).where(ActivitySource.activity_id == a.id)).all()
        result['sources'] = [{'source_record_id': link.source_record_id, 'selected_fields': link.selected_fields}
                             for link in links]
    return result


def facts(session: Session, start: date, end: date) -> list[ActivityFact]:
    lo, hi = utc_date_bounds(start, end, tz(session))
    rows = session.scalars(select(Activity).where(Activity.start_at >= lo, Activity.start_at < hi)).all()
    zone = ZoneInfo(tz(session))
    result = [ActivityFact(id=str(a.id), local_date=a.start_at.astimezone(zone).date(), start_at=a.start_at, sport=a.sport,
            distance_m=a.distance_m, elapsed_s=a.elapsed_s, moving_s=a.moving_s,
            workout_label=(ann.workout_label if ann and ann.workout_label else a.source_workout_label),
            excluded=ann.excluded if ann else False, resolution_state=a.resolution_state)
            for a in rows for ann in [annotation(session, a.id)]]
    manuals = session.scalars(select(ManualSession).where(ManualSession.date >= start, ManualSession.date <= end,
                               ManualSession.linked_activity_id.is_(None))).all()
    for m in manuals:
        start_at = datetime.combine(m.date, m.time or datetime.min.time(), zone).astimezone(UTC)
        result.append(ActivityFact(id=str(m.id), local_date=m.date, start_at=start_at, sport=m.kind,
                                   elapsed_s=m.duration_s))
    return result


class ProfileInput(BaseModel):
    expected_version: int = Field(ge=0)
    timezone: str = 'America/New_York'
    cycle_anchor: date | None = None
    anchor_confirmed: bool = False
    strength_days_confirmed: bool = False
    scheduled_strength_days: list[int] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)
    unknowns: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def confirmed_anchor_has_date(self) -> ProfileInput:
        if self.anchor_confirmed and self.cycle_anchor is None:
            raise ValueError('Confirmed cycle anchor requires a date')
        return self

    @field_validator('timezone')
    @classmethod
    def valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError('Unknown timezone') from exc
        return value

    @field_validator('scheduled_strength_days')
    @classmethod
    def valid_days(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)) or any(d not in range(7) for d in value):
            raise ValueError('Weekdays must be unique integers 0..6')
        return value


@router.get('/profile')
def get_profile(session: Session = Depends(get_session)) -> dict:
    return envelope(session, profile_data(current_profile(session)))


@router.put('/profile')
def put_profile(body: ProfileInput, session: Session = Depends(get_session)) -> dict:
    current = current_profile(session)
    version = current.version if current else 0
    if body.expected_version != version:
        fail('version_conflict', 'Profile changed; reload /api/v1/profile', 409)
    profile = ProfileVersion(version=version+1, effective_at=datetime.now(UTC),
        **body.model_dump(exclude={'expected_version'}))
    session.add(profile)
    bump_data_revision(session)
    session.commit()
    return envelope(session, profile_data(profile))


@router.get('/activities')
def get_activities(start_date: date | None = None, end_date: date | None = None,
                   sport: str | None = None, cursor: str | None = None, limit: int = Query(50, ge=1, le=200),
                   session: Session = Depends(get_session)) -> dict:
    start, end = date_window(session, start_date, end_date)
    lower, upper = utc_date_bounds(start, end, tz(session))
    q = select(Activity).where(Activity.start_at >= lower, Activity.start_at < upper)
    if sport:
        q = q.where(Activity.sport == sport)
    if cursor:
        try:
            cursor_time, cursor_id = cursor.split('|', 1)
            cd, cid = datetime.fromisoformat(cursor_time), uuid.UUID(cursor_id)
            if cd.tzinfo is None:
                raise ValueError('offset required')
        except (ValueError, AttributeError):
            fail('invalid_cursor', 'Invalid activity cursor')
        q = q.where((Activity.start_at < cd) | ((Activity.start_at == cd) & (Activity.id < cid)))
    rows = session.scalars(q.order_by(desc(Activity.start_at), desc(Activity.id)).limit(limit+1)).all()
    next_cursor = f'{rows[limit-1].start_at.isoformat()}|{rows[limit-1].id}' if len(rows) > limit else None
    return envelope(session, {'items': [activity_data(session, a) for a in rows[:limit]],
                              'next_cursor': next_cursor, 'timezone': tz(session), 'coverage': coverage(session, start, end)})


@router.get('/activities/{activity_id}')
def get_activity(activity_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    row = session.get(Activity, activity_id)
    if not row:
        fail('not_found', 'Activity not found', 404)
    return envelope(session, activity_data(session, row, detail=True))


class AnnotationInput(BaseModel):
    expected_version: int = Field(ge=0)
    workout_label: Literal['easy', 'quality', 'long', 'other'] | None = None
    notes: str | None = Field(default=None, max_length=4000)
    excluded: bool = False


@router.patch('/activities/{activity_id}/annotations')
def patch_annotation(activity_id: uuid.UUID, body: AnnotationInput, session: Session = Depends(get_session)) -> dict:
    row = session.get(Activity, activity_id)
    if not row:
        fail('not_found', 'Activity not found', 404)
    old = annotation(session, activity_id)
    if body.expected_version != (old.version if old else 0):
        fail('version_conflict', 'Annotation changed; reload activity', 409)
    ann = ActivityAnnotation(activity_id=activity_id, version=body.expected_version+1,
                             **body.model_dump(exclude={'expected_version'}))
    session.add(ann)
    bump_data_revision(session)
    session.commit()
    return envelope(session, activity_data(session, row, detail=True))


@router.get('/summary')
def get_summary(as_of: date | None = None, days: int = Query(28, ge=1, le=366),
                session: Session = Depends(get_session)) -> dict:
    zone = tz(session)
    today = as_of or datetime.now(ZoneInfo(zone)).date()
    start = min(today-timedelta(days=days-1), today-timedelta(days=13), week_start(today))
    items = facts(session, start, today)
    output = summary(items, today, days)
    output['timezone'] = zone
    output['coverage'] = coverage(session, start, today)
    output['strength_coverage'] = strength_coverage(session, start, today)
    recent_lower, recent_upper = utc_date_bounds(today-timedelta(days=27), today, zone)
    runs = [a for a in session.scalars(select(Activity).where(Activity.start_at >= recent_lower,
                          Activity.start_at < recent_upper, Activity.sport.in_(('running','trail_running','treadmill_running')))
                          .order_by(desc(Activity.start_at)).limit(10)).all()]
    output['recent_runs'] = [activity_data(session, a) for a in runs]
    return envelope(session, output)


@router.get('/recovery')
def get_recovery(start_date: date | None = None, end_date: date | None = None,
                 session: Session = Depends(get_session)) -> dict:
    start, end = date_window(session, start_date, end_date)
    rows = session.scalars(select(RecoveryObservation).where(RecoveryObservation.source_date >= start,
                           RecoveryObservation.source_date <= end).order_by(RecoveryObservation.source_date)).all()
    groups: dict[str, list[dict]] = {'sleep': [], 'hrv': [], 'resting_hr': []}
    for row in rows:
        groups.setdefault(row.metric, []).append({'date': row.source_date, 'value': row.value,
                                      'unit': row.unit, 'statistic': row.statistic})
    means = {metric: trailing_mean([(point['date'], point['value']) for point in points], end)
             for metric, points in groups.items()}
    return envelope(session, {'timezone': tz(session), 'series': groups, 'trailing_7': means,
                              'coverage': coverage(session, start, end)})

class CheckinInput(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=100)
    observed_at: datetime
    symptoms: Literal['none','mild','moderate','severe']
    change: Literal['better','same','worse','unsure'] | None = None
    gait: Literal['normal','affected','unsure']
    feeling: Literal['fresh','usual','tired']
    effort: int | None = Field(default=None, ge=0, le=10)
    activity_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=4000)

    @field_validator('observed_at')
    @classmethod
    def offset_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Timestamp requires UTC offset')
        return value


class CheckinPatch(BaseModel):
    expected_version: int = Field(ge=1)
    observed_at: datetime | None = None
    symptoms: Literal['none','mild','moderate','severe'] | None = None
    change: Literal['better','same','worse','unsure'] | None = None
    gait: Literal['normal','affected','unsure'] | None = None
    feeling: Literal['fresh','usual','tired'] | None = None
    effort: int | None = Field(default=None, ge=0, le=10)
    activity_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=4000)

    @field_validator('observed_at')
    @classmethod
    def offset_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError('Timestamp requires UTC offset')
        return value


def checkin_data(session: Session, row: Checkin) -> dict:
    earliest = row.observed_at - timedelta(hours=75)
    activities = session.scalars(select(Activity).where(Activity.start_at >= earliest,
                               Activity.start_at <= row.observed_at,
                               Activity.sport.in_(('running','trail_running','treadmill_running','strength')))).all()
    candidates = [{'id': a.id, 'start_at': a.start_at, 'elapsed_s': a.elapsed_s, 'sport': a.sport} for a in activities]
    manual_rows = session.scalars(select(ManualSession).where(ManualSession.date >=
                (row.observed_at.astimezone(ZoneInfo(tz(session))).date()-timedelta(days=4)),
                ManualSession.date <= row.observed_at.astimezone(ZoneInfo(tz(session))).date(),
                ManualSession.linked_activity_id.is_(None))).all()
    for m in manual_rows:
        if m.time is not None:
            candidates.append({'id': m.id, 'start_at': datetime.combine(m.date, m.time, ZoneInfo(tz(session))).astimezone(UTC),
                               'elapsed_s': m.duration_s, 'sport': m.kind})
    return {'id': row.id, 'version': row.version, 'observed_at': row.observed_at, 'recorded_at': row.recorded_at,
            'symptoms': row.symptoms, 'change': row.change, 'gait': row.gait, 'feeling': row.feeling,
            'effort': row.effort, 'activity_id': row.activity_id, 'note': row.note,
            'associations': preceding_sessions(row.observed_at, candidates, tz(session))}


def revision_payload(row: Checkin) -> dict:
    return {'observed_at': row.observed_at.isoformat(), 'symptoms': row.symptoms, 'change': row.change,
            'gait': row.gait, 'feeling': row.feeling, 'effort': row.effort,
            'activity_id': str(row.activity_id) if row.activity_id else None, 'note': row.note}


@router.get('/checkins')
def get_checkins(start_date: date | None = None, end_date: date | None = None,
                 cursor: str | None = None, limit: int = Query(50, ge=1, le=200),
                 session: Session = Depends(get_session)) -> dict:
    start, end = date_window(session, start_date, end_date)
    lo, hi = utc_date_bounds(start, end, tz(session))
    query = select(Checkin).where(Checkin.observed_at >= lo, Checkin.observed_at < hi)
    if cursor:
        try:
            instant_text, id_text = cursor.split('|', 1)
            instant, item_id = datetime.fromisoformat(instant_text), uuid.UUID(id_text)
            if instant.tzinfo is None:
                raise ValueError('offset required')
        except ValueError:
            fail('invalid_cursor', 'Invalid check-in cursor')
        query = query.where((Checkin.observed_at < instant) |
                            ((Checkin.observed_at == instant) & (Checkin.id < item_id)))
    rows = session.scalars(query.order_by(desc(Checkin.observed_at), desc(Checkin.id)).limit(limit+1)).all()
    next_cursor = f'{rows[limit-1].observed_at.isoformat()}|{rows[limit-1].id}' if len(rows) > limit else None
    return envelope(session, {'items': [checkin_data(session, row) for row in rows[:limit]],
                              'next_cursor': next_cursor, 'truncated': next_cursor is not None,
                              'timezone': tz(session)})


@router.post('/checkins', status_code=201)
def post_checkin(body: CheckinInput, response: Response, session: Session = Depends(get_session)) -> dict:
    old = session.scalar(select(Checkin).where(Checkin.idempotency_key == body.idempotency_key))
    if old:
        response.status_code = 200
        return envelope(session, checkin_data(session, old))
    if body.activity_id and not session.get(Activity, body.activity_id):
        fail('invalid_activity', 'Activity not found')
    row = Checkin(**body.model_dump())
    session.add(row)
    session.flush()
    session.add(CheckinRevision(checkin_id=row.id, version=1, payload=revision_payload(row)))
    bump_data_revision(session)
    session.commit()
    return envelope(session, checkin_data(session, row))


@router.patch('/checkins/{checkin_id}')
def patch_checkin(checkin_id: uuid.UUID, body: CheckinPatch, session: Session = Depends(get_session)) -> dict:
    row = session.get(Checkin, checkin_id, with_for_update=True)
    if not row:
        fail('not_found', 'Check-in not found', 404)
    if row.version != body.expected_version:
        fail('version_conflict', 'Check-in changed; reload /api/v1/checkins', 409)
    changes = body.model_dump(exclude_unset=True, exclude={'expected_version'})
    if any(changes.get(field) is None for field in ('observed_at', 'symptoms', 'gait', 'feeling') if field in changes):
        fail('null_required_field', 'Required check-in fields cannot be null')
    if 'activity_id' in changes and changes['activity_id'] and not session.get(Activity, changes['activity_id']):
        fail('invalid_activity', 'Activity not found')
    for key, value in changes.items():
        setattr(row, key, value)
    row.version += 1
    session.add(CheckinRevision(checkin_id=row.id, version=row.version, payload=revision_payload(row)))
    bump_data_revision(session)
    session.commit()
    return envelope(session, checkin_data(session, row))


class ManualInput(BaseModel):
    date: DateType
    time: TimeType | None = None
    kind: Literal['strength','cycling','elliptical','swimming','rowing','walking','mobility','rehab','other']
    duration_s: float | None = Field(default=None, ge=0)
    effort: int | None = Field(default=None, ge=0, le=10)
    note: str | None = Field(default=None, max_length=4000)


class ManualPatch(BaseModel):
    expected_version: int = Field(ge=1)
    date: DateType | None = None
    time: TimeType | None = None
    kind: Literal['strength','cycling','elliptical','swimming','rowing','walking','mobility','rehab','other'] | None = None
    duration_s: float | None = Field(default=None, ge=0)
    effort: int | None = Field(default=None, ge=0, le=10)
    note: str | None = Field(default=None, max_length=4000)
    linked_activity_id: uuid.UUID | None = None


def manual_data(row: ManualSession) -> dict:
    return {key: getattr(row, key) for key in ('id','version','date','time','kind','duration_s','effort','note','linked_activity_id')}


@router.get('/manual-sessions')
def get_manual_sessions(start_date: date | None = None, end_date: date | None = None,
                        cursor: str | None = None, limit: int = Query(50, ge=1, le=200),
                        session: Session = Depends(get_session)) -> dict:
    start, end = date_window(session, start_date, end_date)
    query = select(ManualSession).where(ManualSession.date >= start, ManualSession.date <= end)
    if cursor:
        try:
            date_text, id_text = cursor.split('|', 1)
            cursor_date, item_id = date.fromisoformat(date_text), uuid.UUID(id_text)
        except ValueError:
            fail('invalid_cursor', 'Invalid manual session cursor')
        query = query.where((ManualSession.date < cursor_date) |
                            ((ManualSession.date == cursor_date) & (ManualSession.id < item_id)))
    rows = session.scalars(query.order_by(desc(ManualSession.date), desc(ManualSession.id)).limit(limit+1)).all()
    next_cursor = f'{rows[limit-1].date.isoformat()}|{rows[limit-1].id}' if len(rows) > limit else None
    return envelope(session, {'items': [manual_data(row) for row in rows[:limit]],
                              'next_cursor': next_cursor, 'truncated': next_cursor is not None})


@router.post('/manual-sessions', status_code=201)
def post_manual_session(body: ManualInput, session: Session = Depends(get_session)) -> dict:
    row = ManualSession(**body.model_dump())
    session.add(row)
    session.flush()
    detect_import_conflicts_for_manual(session, row)
    bump_data_revision(session)
    session.commit()
    return envelope(session, manual_data(row))


@router.patch('/manual-sessions/{manual_id}')
def patch_manual_session(manual_id: uuid.UUID, body: ManualPatch, session: Session = Depends(get_session)) -> dict:
    row = session.get(ManualSession, manual_id, with_for_update=True)
    if not row:
        fail('not_found', 'Manual session not found', 404)
    if row.version != body.expected_version:
        fail('version_conflict', 'Manual session changed; reload manual sessions', 409)
    changes = body.model_dump(exclude_unset=True, exclude={'expected_version'})
    if any(changes.get(field) is None for field in ('date', 'kind') if field in changes):
        fail('null_required_field', 'Required session fields cannot be null')
    for key, value in changes.items():
        setattr(row, key, value)
    row.version += 1
    session.flush()
    detect_import_conflicts_for_manual(session, row)
    bump_data_revision(session)
    session.commit()
    return envelope(session, manual_data(row))

class PlannedInput(BaseModel):
    date: DateType
    kind: Literal['run','strength','mobility','rehab','cross_training','other']
    target: dict[str, Any] = Field(default_factory=dict)


class PlanInput(BaseModel):
    start_date: date
    end_date: date
    sessions: list[PlannedInput] = Field(max_length=366)

    @model_validator(mode='after')
    def valid_range(self) -> PlanInput:
        if self.end_date < self.start_date or (self.end_date-self.start_date).days >= 366:
            raise ValueError('Invalid plan date range')
        if any(s.date < self.start_date or s.date > self.end_date for s in self.sessions):
            raise ValueError('Session outside plan range')
        return self


class DecisionInput(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=1000)


def plan_data(session: Session, plan: PlanVersion) -> dict:
    sessions = session.scalars(select(PlannedSession).where(PlannedSession.plan_id == plan.id)
                               .order_by(PlannedSession.date)).all()
    result = []
    for item in sessions:
        link = session.scalar(select(CompletionLink).where(CompletionLink.planned_session_id == item.id))
        result.append({'id': item.id, 'date': item.date, 'kind': item.kind, 'target': item.target,
                       'completion_link_id': link.id if link else None,
                       'completion_activity_id': link.activity_id if link else None,
                       'completion_manual_session_id': link.manual_session_id if link else None})
    return {'id': plan.id, 'version': plan.version, 'status': plan.status, 'start_date': plan.start_date,
            'end_date': plan.end_date, 'profile_version': plan.profile_version, 'sessions': result,
            'created_at': plan.created_at, 'decided_at': plan.decided_at, 'reason': plan.reason}


@router.get('/plans')
def get_plans(start_date: date | None = None, end_date: date | None = None,
              session: Session = Depends(get_session)) -> dict:
    start, end = date_window(session, start_date, end_date)
    profile = current_profile(session)
    plans = session.scalars(select(PlanVersion).where(PlanVersion.end_date >= start,
                            PlanVersion.start_date <= end).order_by(desc(PlanVersion.created_at)).limit(100)).all()
    anchor = profile.cycle_anchor if profile and profile.anchor_confirmed else None
    return envelope(session, {'items': [plan_data(session, p) for p in plans],
                              'opportunities': opportunities(start, end, anchor), 'unscheduled': anchor is None,
                              'timezone': tz(session)})


@router.post('/plans', status_code=201)
def post_plan(body: PlanInput, session: Session = Depends(get_session)) -> dict:
    profile = current_profile(session)
    row = PlanVersion(start_date=body.start_date, end_date=body.end_date,
                      profile_version=profile.version if profile else 0,
                      anchor_date=profile.cycle_anchor if profile else None)
    session.add(row)
    session.flush()
    for item in body.sessions:
        session.add(PlannedSession(plan_id=row.id, **item.model_dump()))
    bump_data_revision(session)
    session.commit()
    return envelope(session, plan_data(session, row))


def decide_plan(plan_id: uuid.UUID, body: DecisionInput, status: str, session: Session) -> dict:
    plan = session.get(PlanVersion, plan_id, with_for_update=True)
    if not plan:
        fail('not_found', 'Plan not found', 404)
    if plan.version != body.expected_version:
        fail('version_conflict', 'Plan changed; reload /api/v1/plans', 409)
    if plan.status != 'draft':
        fail('invalid_state', 'Only draft plans can be decided')
    profile = current_profile(session)
    if status == 'accepted':
        if not profile or plan.profile_version != profile.version or plan.anchor_date != profile.cycle_anchor:
            fail('profile_changed', 'Profile changed; create a new draft', 409)
        accepted = session.scalars(select(PlanVersion).where(PlanVersion.status == 'accepted',
                    PlanVersion.end_date >= plan.start_date, PlanVersion.start_date <= plan.end_date)).all()
        if any(old.start_date != plan.start_date or old.end_date != plan.end_date for old in accepted):
            fail('overlapping_plan', 'Replacement must cover the exact accepted date range')
        items = session.scalars(select(PlannedSession).where(PlannedSession.plan_id == plan.id)).all()
        errors = validate_acceptance(plan.start_date, plan.end_date,
                                     [{'date': x.date.isoformat(), 'kind': x.kind} for x in items],
                                     plan.anchor_date, bool(profile and profile.anchor_confirmed),
                                     bool(profile and profile.strength_days_confirmed))
        # Count strength in complete Monday-Sunday weeks even when the draft
        # starts or ends midweek. Adjacent accepted sessions outside this draft
        # supply the other part of a boundary week.
        first_week = week_start(plan.start_date)
        last_week = week_start(plan.end_date)
        adjacent_plans = session.scalars(select(PlanVersion).where(PlanVersion.status == 'accepted',
                          PlanVersion.end_date >= first_week, PlanVersion.start_date <= last_week)).all()
        adjacent_ids = [p.id for p in adjacent_plans]
        adjacent = session.scalars(select(PlannedSession).where(PlannedSession.plan_id.in_(adjacent_ids),
                    PlannedSession.date >= first_week, PlannedSession.date <= last_week+timedelta(days=6),
                    PlannedSession.kind == 'strength')).all() if adjacent_ids else []
        cursor = first_week
        while cursor <= last_week:
            week_end = cursor+timedelta(days=6)
            count = sum(x.kind == 'strength' and cursor <= x.date <= week_end for x in items)
            count += sum(cursor <= x.date <= week_end and (x.date < plan.start_date or x.date > plan.end_date)
                         for x in adjacent)
            if count != 2 and f'Expected two strength sessions in week {cursor.isoformat()}' not in errors:
                errors.append(f'Expected two strength sessions in week {cursor.isoformat()}')
            cursor += timedelta(days=7)
        if errors:
            fail('plan_invalid', '; '.join(errors))
        for old in accepted:
            old.status = 'superseded'
            old.version += 1
    plan.status = status
    plan.version += 1
    plan.decided_at = datetime.now(UTC)
    plan.reason = body.reason
    bump_data_revision(session)
    session.commit()
    return envelope(session, plan_data(session, plan))


@router.post('/plans/{plan_id}/accept')
def accept_plan(plan_id: uuid.UUID, body: DecisionInput, session: Session = Depends(get_session)) -> dict:
    return decide_plan(plan_id, body, 'accepted', session)


@router.post('/plans/{plan_id}/reject')
def reject_plan(plan_id: uuid.UUID, body: DecisionInput, session: Session = Depends(get_session)) -> dict:
    return decide_plan(plan_id, body, 'rejected', session)


class CompletionInput(BaseModel):
    planned_session_id: uuid.UUID
    activity_id: uuid.UUID | None = None
    manual_session_id: uuid.UUID | None = None

    @model_validator(mode='after')
    def one_actual(self) -> CompletionInput:
        if (self.activity_id is None) == (self.manual_session_id is None):
            raise ValueError('Exactly one actual session required')
        return self


@router.post('/completion-links', status_code=201)
def post_completion_link(body: CompletionInput, session: Session = Depends(get_session)) -> dict:
    planned = session.get(PlannedSession, body.planned_session_id)
    plan = session.get(PlanVersion, planned.plan_id) if planned else None
    if not planned or not plan or plan.status != 'accepted':
        fail('invalid_plan', 'Accepted planned session required')
    if body.activity_id and not session.get(Activity, body.activity_id):
        fail('not_found', 'Actual activity not found', 404)
    if body.manual_session_id and not session.get(ManualSession, body.manual_session_id):
        fail('not_found', 'Manual session not found', 404)
    existing = session.scalar(select(CompletionLink).where((CompletionLink.planned_session_id == body.planned_session_id) |
            (CompletionLink.activity_id == body.activity_id if body.activity_id else CompletionLink.manual_session_id == body.manual_session_id)))
    if existing:
        fail('duplicate_completion', 'Completion already linked', 409)
    link = CompletionLink(**body.model_dump())
    session.add(link)
    bump_data_revision(session)
    session.commit()
    return envelope(session, {'id': link.id, **body.model_dump()})


@router.delete('/completion-links/{link_id}')
def delete_completion_link(link_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    link = session.get(CompletionLink, link_id)
    if not link:
        fail('not_found', 'Completion link not found', 404)
    session.delete(link)
    bump_data_revision(session)
    session.commit()
    return envelope(session, {'deleted': True})


@router.get('/conflicts')
def get_conflicts(session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(select(Conflict).order_by(desc(Conflict.id)).limit(200)).all()
    return envelope(session, {'items': [{'id': c.id, 'kind': c.kind, 'status': c.status,
        'activity_ids': c.activity_ids, 'manual_session_id': c.manual_session_id,
        'details': c.details, 'resolution': c.resolution} for c in rows]})


class ConflictInput(BaseModel):
    resolution: Literal['merge','keep_separate','reverse']
    canonical_activity_id: uuid.UUID | None = None


@router.post('/conflicts/{conflict_id}/resolve')
def resolve_conflict(conflict_id: uuid.UUID, body: ConflictInput, session: Session = Depends(get_session)) -> dict:
    row = session.get(Conflict, conflict_id, with_for_update=True)
    if not row:
        fail('not_found', 'Conflict not found', 404)
    if body.resolution == 'merge' and not body.canonical_activity_id:
        fail('canonical_required', 'Choose canonical activity')
    if body.canonical_activity_id and str(body.canonical_activity_id) not in row.activity_ids:
        fail('invalid_canonical', 'Canonical activity must be a conflict candidate')
    candidates = [session.get(Activity, uuid.UUID(activity_id)) for activity_id in row.activity_ids]
    if body.resolution == 'merge':
        if not row.details.get('prior_states'):
            row.details = {**row.details, 'prior_states': {str(a.id): a.resolution_state for a in candidates if a}}
        for activity in candidates:
            if activity:
                activity.resolution_state = 'resolved' if activity.id == body.canonical_activity_id else 'merged'
        if row.manual_session_id:
            manual = session.get(ManualSession, row.manual_session_id)
            if manual:
                manual.linked_activity_id = body.canonical_activity_id
    elif body.resolution == 'keep_separate':
        if not row.details.get('prior_states'):
            row.details = {**row.details, 'prior_states': {str(a.id): a.resolution_state for a in candidates if a}}
        for activity in candidates:
            if activity:
                activity.resolution_state = 'resolved'
        if row.manual_session_id:
            manual = session.get(ManualSession, row.manual_session_id)
            if manual:
                manual.linked_activity_id = None
    else:
        prior = row.details.get('prior_states', {})
        for activity in candidates:
            if activity:
                activity.resolution_state = prior.get(str(activity.id), 'pending')
        if row.manual_session_id:
            manual = session.get(ManualSession, row.manual_session_id)
            if manual:
                manual.linked_activity_id = None
    row.resolution = body.resolution
    row.status = 'open' if body.resolution == 'reverse' else 'resolved'
    row.resolved_at = datetime.now(UTC)
    bump_data_revision(session)
    session.commit()
    return envelope(session, {'id': row.id, 'status': row.status, 'resolution': row.resolution})


def weekly_data(session: Session, start: date) -> dict:
    end = start + timedelta(days=6)
    selected = facts(session, start, end)
    aggregate_data = aggregate(selected, start, end)
    zone = ZoneInfo(tz(session))
    lo = datetime.combine(start, datetime.min.time(), zone).astimezone(UTC)
    hi = datetime.combine(end+timedelta(days=1), datetime.min.time(), zone).astimezone(UTC)
    checkins = session.scalars(select(Checkin).where(Checkin.observed_at >= lo, Checkin.observed_at < hi)).all()
    accepted = session.scalars(select(PlanVersion).where(PlanVersion.status == 'accepted',
                    PlanVersion.end_date >= start, PlanVersion.start_date <= end)).all()
    plans = [plan_data(session, p) for p in accepted]
    planned_sessions = [item for plan in plans for item in plan['sessions'] if start <= item['date'] <= end]
    comparison: dict[str, Any] = {'planned': {}, 'completed': {}, 'unlinked': {}, 'sessions': []}
    for item in planned_sessions:
        kind = item['kind']
        linked = bool(item['completion_activity_id'] or item['completion_manual_session_id'])
        comparison['planned'][kind] = comparison['planned'].get(kind, 0) + 1
        bucket = 'completed' if linked else 'unlinked'
        comparison[bucket][kind] = comparison[bucket].get(kind, 0) + 1
        comparison['sessions'].append({'planned_session_id': item['id'], 'date': item['date'],
                                       'kind': kind, 'status': 'completed' if linked else 'unlinked'})
    recovery_data = get_recovery(start_date=start, end_date=end, session=session)['data']
    recovery_missing = {metric: 7-len({point['date'] for point in points})
                        for metric, points in recovery_data['series'].items()}
    week_coverage = coverage(session, start, end)
    questions = []
    if all(missing == 7 for missing in recovery_missing.values()):
        questions.append('Recovery data unavailable for this week')
    if comparison['unlinked']:
        questions.append('Planned sessions have no confirmed completion link')
    return {'week_start': start, 'week_end': end, 'timezone': tz(session), 'metric_version': 'analytics.v1',
            'summary': aggregate_data, 'plan_comparison': comparison,
            'strength_coverage': strength_coverage(session, start, end),
            'recovery': recovery_data,
            'missingness': {'run_distance_count': aggregate_data['missing_distance_count'],
                            'run_elapsed_count': aggregate_data['missing_elapsed_count'],
                            'recovery_missing_dates': recovery_missing,
                            'coverage_incomplete': [c['dataset'] for c in week_coverage if not c['fully_enumerated']]},
            'checkins': [{'observed_at': c.observed_at, 'symptoms': c.symptoms, 'gait': c.gait, 'feeling': c.feeling}
                         for c in checkins],
            'plan': plans, 'coverage': week_coverage, 'questions': questions}


@router.get('/weekly-summary')
def get_weekly_summary(week_start_date: date | None = Query(None, alias='week_start'),
                       session: Session = Depends(get_session)) -> dict:
    today = datetime.now(ZoneInfo(tz(session))).date()
    start = week_start_date or week_start(today)
    if start.weekday() != 0:
        fail('invalid_week', 'week_start must be Monday')
    return envelope(session, weekly_data(session, start))


class SnapshotInput(BaseModel):
    week_start: date


@router.post('/weekly-snapshots', status_code=201)
def post_weekly_snapshot(body: SnapshotInput, session: Session = Depends(get_session)) -> dict:
    if body.week_start.weekday() != 0:
        fail('invalid_week', 'week_start must be Monday')
    profile = current_profile(session)
    latest_plan = session.scalar(select(PlanVersion).where(PlanVersion.status == 'accepted')
                                 .order_by(desc(PlanVersion.decided_at)).limit(1))
    payload = weekly_data(session, body.week_start)
    row = WeeklySnapshot(week_start=body.week_start, week_end=body.week_start+timedelta(days=6),
                         data_revision=get_revision(session), profile_version=profile.version if profile else 0,
                         plan_version=latest_plan.version if latest_plan else 0, summary=jsonable_encoder(payload))
    session.add(row)
    session.commit()
    return envelope(session, {'id': row.id, 'generated_at': row.generated_at,
        'data_revision': row.data_revision, 'profile_version': row.profile_version,
        'plan_version': row.plan_version, 'summary': row.summary})


@router.get('/context')
def get_context(as_of: date | None = None, include_notes: bool = False,
                session: Session = Depends(get_session)) -> dict:
    today = as_of or datetime.now(ZoneInfo(tz(session))).date()
    profile = current_profile(session)
    recent = facts(session, today-timedelta(days=13), today)
    prior = facts(session, today-timedelta(days=83), today)
    weeks = []
    cursor = week_start(today-timedelta(days=83))
    while cursor <= today:
        weeks.append({'week_start': cursor, **aggregate(prior, cursor, cursor+timedelta(days=6)),
                      'coverage': coverage(session, cursor, cursor+timedelta(days=6))})
        cursor += timedelta(days=7)
    recent_lower, recent_upper = utc_date_bounds(today-timedelta(days=13), today, tz(session))
    activities = session.scalars(select(Activity).where(Activity.start_at >= recent_lower,
                  Activity.start_at < recent_upper).order_by(desc(Activity.start_at)).limit(100)).all()
    lower, upper = utc_date_bounds(today-timedelta(days=13), today, tz(session))
    checkins = session.scalars(select(Checkin).where(Checkin.observed_at >= lower, Checkin.observed_at < upper)
                  .order_by(desc(Checkin.observed_at)).limit(100)).all()
    accepted = session.scalars(select(PlanVersion).where(PlanVersion.status == 'accepted',
                     PlanVersion.end_date >= today, PlanVersion.start_date <= today+timedelta(days=13))).all()
    latest_plan = session.scalar(select(PlanVersion).where(PlanVersion.status == 'accepted')
                                 .order_by(desc(PlanVersion.decided_at)).limit(1))
    recovery_data = get_recovery(start_date=today-timedelta(days=13), end_date=today, session=session)['data']
    manual_rows = session.scalars(select(ManualSession).where(ManualSession.date >= today-timedelta(days=13),
                  ManualSession.date <= today).order_by(desc(ManualSession.date)).limit(100)).all()
    recent_activities = [activity_data(session, a) for a in activities]
    recent_activities.extend({'id': m.id, 'local_date': m.date, 'start_at': None, 'sport': m.kind,
                              'distance_m': None, 'elapsed_s': m.duration_s, 'moving_s': None,
                              'workout_label': 'unknown', 'resolution_state': 'resolved', 'source': 'manual',
                              'linked_activity_id': m.linked_activity_id}
                             for m in manual_rows if m.linked_activity_id is None)
    out = {'context_version': 'coach_context.v1', 'generated_at': datetime.now(UTC),
           'as_of': today, 'timezone': tz(session), 'data_revision': get_revision(session),
           'profile_version': profile.version if profile else 0,
           'plan_version': latest_plan.version if latest_plan else 0,
           'profile': profile_data(profile), 'last_14_days': summary(recent, today, 14),
           'strength_coverage': strength_coverage(session, today-timedelta(days=13), today),
           'prior_12_weeks': weeks,
           'recent_activities': recent_activities,
           'recent_manual_sessions': [manual_data(m) for m in manual_rows],
           'recovery': recovery_data,
           'recent_checkins': [checkin_data(session, c) for c in checkins],
           'next_14_days_plan': [plan_data(session, p) for p in accepted],
           'conflicts': [{'id': c.id, 'kind': c.kind, 'status': c.status} for c in
                         session.scalars(select(Conflict).where(Conflict.status == 'open').limit(100)).all()],
           'omitted': ['coordinates','raw_payloads','credentials'], 'metric_version': 'analytics.v1'}
    if not include_notes:
        out['omitted'].append('notes')
        def strip_notes(value):
            if isinstance(value, dict):
                return {k: strip_notes(v) for k, v in value.items() if 'note' not in k.lower()}
            if isinstance(value, list):
                return [strip_notes(v) for v in value]
            return value
        out = strip_notes(out)
    return envelope(session, out)


@router.get('/weekly-snapshots')
def get_weekly_snapshots(session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(select(WeeklySnapshot).order_by(desc(WeeklySnapshot.generated_at)).limit(100)).all()
    profile = current_profile(session)
    latest_plan = session.scalar(select(PlanVersion).where(PlanVersion.status == 'accepted')
                                 .order_by(desc(PlanVersion.decided_at)).limit(1))
    return envelope(session, {'items': [{'id': r.id, 'week_start': r.week_start, 'week_end': r.week_end,
             'generated_at': r.generated_at, 'data_revision': r.data_revision,
             'profile_version': r.profile_version, 'plan_version': r.plan_version,
             'stale': r.data_revision != get_revision(session) or
                      r.profile_version != (profile.version if profile else 0) or
                      r.plan_version != (latest_plan.version if latest_plan else 0),
             'summary': r.summary} for r in rows]})
