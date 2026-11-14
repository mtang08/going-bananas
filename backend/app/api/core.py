from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import bump_data_revision, get_revision, get_session
from app.domain.analytics import (
    RUN_SPORTS,
    pace_s_per_km,
    utc_date_bounds,
)
from app.errors import fail
from app.models import (
    Activity,
    ActivityAnnotation,
    ActivitySource,
    AppState,
    ProfileVersion,
)
from app.services.coverage import coverage
from app.services.profile import current_profile, profile_data
from app.services.run_classification import RunObservation, classify_history
from app.services.timezone import DEFAULT_TIMEZONE, athlete_today, athlete_tz

router = APIRouter()


def envelope(session: Session, data: Any) -> dict:
    return {'schema_version': 'v1', 'data_revision': get_revision(session), 'mode': settings.app_mode, 'data': data}


def _profile_authority(session: Session) -> str:
    state = session.get(AppState, 1)
    return state.planning_authority if state else 'legacy'


def date_window(session: Session, start_date: date | None, end_date: date | None) -> tuple[date, date]:
    today = athlete_today(session)
    end = end_date or today
    start = start_date or end - timedelta(days=27)
    if start > end or (end-start).days >= 366:
        fail('invalid_date_range', 'Date range must be ordered and at most 366 days')
    return start, end


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
    zone = athlete_tz(session)
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
              'local_date': a.start_at.astimezone(athlete_tz(session)).date(), 'source_local_date': a.local_date, 'sport': a.sport, 'subtype': a.subtype,
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


class ProfileInput(BaseModel):
    expected_version: int = Field(ge=0)
    timezone: str = DEFAULT_TIMEZONE
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
    lower, upper = utc_date_bounds(start, end, athlete_tz(session).key)
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
                              'next_cursor': next_cursor, 'timezone': athlete_tz(session).key, 'coverage': coverage(session, start, end)})


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
