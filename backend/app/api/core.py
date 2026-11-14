from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from datetime import date as DateType
from datetime import time as TimeType
from typing import Any, Literal, NoReturn
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import bump_data_revision, get_revision, get_session
from app.domain.analytics import (
    RUN_SPORTS,
    ActivityFact,
    pace_s_per_km,
    summary,
    trailing_mean,
    utc_date_bounds,
    week_start,
)
from app.domain.associations import preceding_sessions
from app.domain.cycle import opportunities, recurring_sessions, validate_acceptance
from app.models import (
    Activity,
    ActivityAnnotation,
    ActivitySource,
    AppState,
    Checkin,
    CheckinRevision,
    CompletionLink,
    CoverageInterval,
    ImportBatch,
    ManualSession,
    PlannedSession,
    PlanVersion,
    ProfileVersion,
    RecoveryObservation,
)
from app.services.coaching import run_intent
from app.services.run_classification import RunObservation, classify_history
from app.services.strength_history import strong_history
from app.services.sync import detect_import_conflicts_for_manual
from app.strong_models import StrongWorkoutRow

router = APIRouter()


def envelope(session: Session, data: Any) -> dict:
    return {'schema_version': 'v1', 'data_revision': get_revision(session), 'mode': settings.app_mode, 'data': data}


def fail(code: str, message: str, status: int = 422) -> NoReturn:
    raise HTTPException(status_code=status, detail={'code': code, 'message': message})


def current_profile(session: Session) -> ProfileVersion | None:
    return session.scalar(select(ProfileVersion).order_by(desc(ProfileVersion.version)).limit(1))


def _profile_authority(session: Session) -> str:
    state = session.get(AppState, 1)
    return state.planning_authority if state else 'legacy'


def profile_data(profile: ProfileVersion | None, planning_authority: str = 'legacy') -> dict:
    if profile is None:
        return {'version': 0, 'planning_authority': planning_authority, 'timezone': 'America/New_York', 'cycle_anchor': None,
                'anchor_confirmed': False, 'strength_days_confirmed': False,
                'scheduled_strength_days': [], 'strength_schedule_mode': 'weekly',
                'strength_week_a_start': None, 'strength_week_a_days': [], 'strength_week_b_days': [],
                'mobility_week_a_days': [], 'mobility_week_b_days': [], 'mobility_optional_days': [],
                'facts': {}, 'preferences': {}, 'unknowns': []}
    return {'planning_authority': planning_authority, **{key: getattr(profile, key) for key in ('version', 'timezone', 'cycle_anchor', 'anchor_confirmed',
            'strength_days_confirmed', 'scheduled_strength_days', 'strength_schedule_mode',
            'strength_week_a_start', 'strength_week_a_days', 'strength_week_b_days',
            'mobility_week_a_days', 'mobility_week_b_days', 'mobility_optional_days',
            'facts', 'preferences', 'unknowns')}}


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
    strong = strong_history(session, start, end)
    latest_strong = session.scalar(select(func.max(StrongWorkoutRow.local_date)))
    if latest_strong is not None:
        return {'source': 'strong', 'status': 'partial', 'reason': 'strong_export_snapshot',
                'complete': False, 'observed_manual_count': manual_count,
                'observed_imported_count': imported_count + strong['session_count'],
                'observed_strong_count': strong['session_count'],
                'latest_observation': latest_strong,
                'message': 'Strong export connected; later workouts require another CSV import. Missing recordings do not mean missed lifting.'}
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


def run_classifications(session: Session, rows: Sequence[Activity]) -> dict[str, dict]:
    targets = [a for a in rows if a.sport in RUN_SPORTS]
    if not targets:
        return {}
    first = min(a.start_at for a in targets) - timedelta(days=84)
    last = max(a.start_at for a in targets)
    history = session.scalars(select(Activity).where(Activity.start_at >= first, Activity.start_at <= last,
                              Activity.sport.in_(RUN_SPORTS)).order_by(Activity.start_at)).all()
    zone = ZoneInfo(tz(session))
    observations = []
    for a in history:
        ann = annotation(session, a.id)
        observations.append(RunObservation(
            id=str(a.id), local_date=a.start_at.astimezone(zone).date(), start_at=a.start_at,
            sport=a.sport, distance_m=a.distance_m, elapsed_s=a.elapsed_s, moving_s=a.moving_s,
            avg_hr_bpm=a.avg_hr_bpm, manual_label=ann.workout_label if ann else None,
            source_label=a.source_workout_label, excluded=ann.excluded if ann else False,
            resolution_state=a.resolution_state,
        ))
    profile = current_profile(session)
    preference = (profile.preferences or {}).get('long_run_weekdays', [5, 6]) if profile else [5, 6]
    long_days = tuple(preference) if isinstance(preference, list) and preference and all(
        isinstance(day, int) and day in range(7) for day in preference) else (5, 6)
    return classify_history(observations, long_run_weekdays=long_days)


def activity_data(session: Session, a: Activity, detail: bool = False,
                  classifications: dict[str, dict] | None = None) -> dict:
    ann = annotation(session, a.id)
    classification = (classifications if classifications is not None else run_classifications(session, [a])).get(str(a.id))
    label = classification['effective_label'] if classification else (
        ann.workout_label if ann and ann.workout_label else a.source_workout_label)
    result = {'id': a.id, 'start_at': a.start_at, 'original_start': a.original_start,
              'local_date': a.start_at.astimezone(ZoneInfo(tz(session))).date(), 'source_local_date': a.local_date, 'sport': a.sport, 'subtype': a.subtype,
              'distance_m': a.distance_m, 'elapsed_s': a.elapsed_s, 'moving_s': a.moving_s,
              'moving_pace_s_per_km': pace_s_per_km(a.distance_m, a.moving_s),
              'avg_hr_bpm': a.avg_hr_bpm,
              'elapsed_pace_s_per_km': pace_s_per_km(a.distance_m, a.elapsed_s),
              'workout_label': label or 'unknown', 'resolution_state': a.resolution_state,
              'classification': classification,
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
    classifications = run_classifications(session, rows)
    zone = ZoneInfo(tz(session))
    result = [ActivityFact(id=str(a.id), local_date=a.start_at.astimezone(zone).date(), start_at=a.start_at, sport=a.sport,
            distance_m=a.distance_m, elapsed_s=a.elapsed_s, moving_s=a.moving_s,
            workout_label=(classifications[str(a.id)]['effective_label'] if str(a.id) in classifications
                           else ann.workout_label if ann and ann.workout_label else a.source_workout_label),
            excluded=ann.excluded if ann else False, resolution_state=a.resolution_state)
            for a in rows for ann in [annotation(session, a.id)]]
    manuals = session.scalars(select(ManualSession).where(ManualSession.date >= start, ManualSession.date <= end,
                               ManualSession.linked_activity_id.is_(None))).all()
    for m in manuals:
        start_at = datetime.combine(m.date, m.time or datetime.min.time(), zone).astimezone(UTC)
        result.append(ActivityFact(id=str(m.id), local_date=m.date, start_at=start_at, sport=m.kind,
                                   elapsed_s=m.duration_s))
    for item in strong_history(session, start, end)['sessions']:
        local_start = datetime.fromisoformat(item['local_start']).replace(tzinfo=zone)
        result.append(ActivityFact(id=item['id'], local_date=date.fromisoformat(item['date']),
                                   start_at=local_start.astimezone(UTC), sport='strength',
                                   elapsed_s=item['duration_s']))
    return result


class ProfileInput(BaseModel):
    expected_version: int = Field(ge=0)
    timezone: str = 'America/New_York'
    cycle_anchor: date | None = None
    anchor_confirmed: bool = False
    strength_days_confirmed: bool = False
    scheduled_strength_days: list[int] = Field(default_factory=list)
    strength_schedule_mode: Literal['weekly', 'alternating'] = 'weekly'
    strength_week_a_start: date | None = None
    strength_week_a_days: list[int] = Field(default_factory=list)
    strength_week_b_days: list[int] = Field(default_factory=list)
    mobility_week_a_days: list[int] = Field(default_factory=list)
    mobility_week_b_days: list[int] = Field(default_factory=list)
    mobility_optional_days: list[int] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)
    unknowns: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def confirmed_anchor_has_date(self) -> ProfileInput:
        if self.anchor_confirmed and self.cycle_anchor is None:
            raise ValueError('Confirmed cycle anchor requires a date')
        if self.strength_schedule_mode == 'alternating':
            if self.strength_week_a_start is not None and self.strength_week_a_start.weekday() != 0:
                raise ValueError('Week A start must be a Monday')
            if self.strength_days_confirmed and (
                self.strength_week_a_start is None
                or len(self.strength_week_a_days) != 2
                or len(self.strength_week_b_days) != 2
            ):
                raise ValueError('Confirmed alternating strength requires a Monday Week A start and two days in each week')
        return self

    @field_validator('timezone')
    @classmethod
    def valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError('Unknown timezone') from exc
        return value

    @field_validator('scheduled_strength_days', 'strength_week_a_days', 'strength_week_b_days',
                     'mobility_week_a_days', 'mobility_week_b_days', 'mobility_optional_days')
    @classmethod
    def valid_days(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)) or any(d not in range(7) for d in value):
            raise ValueError('Weekdays must be unique integers 0..6')
        return value


@router.get('/imports')
def get_imports(session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(select(ImportBatch).where(ImportBatch.source_kind == 'garmin_export')
                           .order_by(desc(ImportBatch.started_at)).limit(20)).all()
    public_keys = {'archive_sha256', 'activities', 'recovery', 'datasets', 'preserved_only',
                   'seen', 'new_revisions', 'changed', 'rejected', 'replayed'}
    return envelope(session, {'items': [
        {'id': row.id, 'source_kind': row.source_kind, 'status': row.status,
         'started_at': row.started_at, 'finished_at': row.finished_at,
         'adapter_version': row.adapter_version,
         'counters': {key: value for key, value in (row.counters or {}).items() if key in public_keys}}
        for row in rows]})


@router.get('/profile')
def get_profile(session: Session = Depends(get_session)) -> dict:
    return envelope(session, profile_data(current_profile(session), _profile_authority(session)))


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
    return envelope(session, profile_data(profile, _profile_authority(session)))


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
    classifications = run_classifications(session, rows[:limit])
    return envelope(session, {'items': [activity_data(session, a, classifications=classifications) for a in rows[:limit]],
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
    classifications = run_classifications(session, runs)
    output['recent_runs'] = [activity_data(session, a, classifications=classifications) for a in runs]
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
    from app.services.legacy_cutover import require_legacy_write
    require_legacy_write(session)
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
    from app.services.legacy_cutover import require_legacy_write
    require_legacy_write(session)
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
    from app.agent_models import CoachPlanRevision
    revision = session.scalar(select(CoachPlanRevision).where(CoachPlanRevision.plan_id == plan.id)
                              .order_by(desc(CoachPlanRevision.created_at)).limit(1))
    member_ids = revision.payload.get('active_session_ids', []) if revision else None
    condition = (PlannedSession.id.in_([uuid.UUID(x) for x in member_ids])
                 if member_ids is not None else PlannedSession.plan_id == plan.id)
    sessions = session.scalars(select(PlannedSession).where(condition).order_by(PlannedSession.date)).all()
    result = []
    for item in sessions:
        link = session.scalar(select(CompletionLink).where(CompletionLink.planned_session_id == item.id))
        result.append({'id': item.id, 'date': item.date, 'kind': item.kind, 'target': item.target,
                       'completion_link_id': link.id if link else None,
                       'completion_activity_id': link.activity_id if link else None,
                       'completion_manual_session_id': link.manual_session_id if link else None})
    return {'id': plan.id, 'version': plan.version, 'status': plan.status, 'start_date': plan.start_date,
            'end_date': plan.end_date, 'profile_version': plan.profile_version, 'sessions': result,
            'created_at': plan.created_at, 'decided_at': plan.decided_at, 'reason': plan.reason,
            'parent_id': plan.parent_id, 'agent_revision_id': revision.id if revision else None}


@router.get('/plans')
def get_plans(start_date: date | None = None, end_date: date | None = None,
              session: Session = Depends(get_session)) -> dict:
    start, end = date_window(session, start_date, end_date)
    profile = current_profile(session)
    plans = session.scalars(select(PlanVersion).where(PlanVersion.end_date >= start,
                            PlanVersion.start_date <= end).order_by(desc(PlanVersion.created_at)).limit(100)).all()
    anchor = profile.cycle_anchor if profile and profile.anchor_confirmed else None
    accepted_ranges = [(p.start_date, p.end_date) for p in plans if p.status == 'accepted']
    run_opportunities = [slot for slot in opportunities(start, end, anchor)
                         if not any(first <= date.fromisoformat(slot['date']) <= last
                                    for first, last in accepted_ranges)]
    for slot in run_opportunities:
        intent = run_intent({'profile': profile_data(profile)}, date.fromisoformat(slot['date']))
        slot.update({'kind': 'run', 'source': 'run_cycle', 'intent': intent,
                     'conditional': intent in {'quality', 'long'}, 'optional': False})
    return envelope(session, {'items': [plan_data(session, p) for p in plans],
                              'opportunities': run_opportunities, 'unscheduled': anchor is None,
                              'recurring_sessions': recurring_sessions(
                                  start, end, profile, accepted_ranges,
                              ),
                              'timezone': tz(session)})


@router.post('/plans', status_code=201)
def post_plan(body: PlanInput, session: Session = Depends(get_session)) -> dict:
    from app.services.legacy_cutover import require_legacy_write
    require_legacy_write(session)
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
    from app.services.legacy_cutover import require_legacy_write
    require_legacy_write(session)
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
