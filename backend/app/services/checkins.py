"""Calendar-authority check-ins, revisions, prompts and manual RPE."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.core import current_profile, fail
from app.checkin_models import Checkin, CheckinRevision, SessionRpe, SymptomReport
from app.coach_v2_models import DailyGuidance
from app.metric_models import Prompt
from app.models import Activity, ManualSession
from app.services.calendar import _lock
from app.services.daily_guidance import guidance_data, persist_daily_guidance
from app.strong_models import StrongWorkoutRow

CONTEXT_TAGS = {'heat', 'travel', 'poor_sleep', 'unusual_surface', 'equipment'}
RUN_SPORTS = {'running', 'trail_running', 'treadmill_running'}


def _measurement(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError('measurement must be numeric')
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('measurement must be numeric') from None
    if not decimal.is_finite() or not 0 <= decimal <= 10 or cast(int, decimal.as_tuple().exponent) < -1:
        raise ValueError('measurement must be 0–10 with at most one decimal place')
    return float(decimal)


class SymptomInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    site: str
    side: Literal['left', 'right', 'both', 'na']
    severity: float
    timing: Literal['during', 'immediately_after', 'next_morning', 'hours_24_48', 'later', 'unknown']

    @field_validator('site')
    @classmethod
    def valid_site(cls, value: str) -> str:
        if not value.strip() or len(value.strip()) > 60:
            raise ValueError('site must be 1–60 characters')
        return value.strip()

    @field_validator('severity', mode='before')
    @classmethod
    def valid_severity(cls, value: object) -> float:
        return _measurement(value)


class CheckinCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=1, max_length=100)
    kind: Literal['exception', 'post_run', 'delayed_followup']
    observed_at: datetime
    fatigue: float | None = None
    illness: Literal['none', 'possible', 'present'] | None = None
    gait_change: Literal['yes', 'no', 'unsure'] | None = None
    context_tags: list[str] = Field(default_factory=list)
    activity_id: uuid.UUID | None = None
    prompt_id: uuid.UUID | None = None
    note: str | None = None
    symptoms: list[SymptomInput] = Field(default_factory=list)

    @field_validator('observed_at')
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('observed_at must include offset')
        return value.astimezone(UTC)

    @field_validator('fatigue', mode='before')
    @classmethod
    def valid_fatigue(cls, value: object) -> float | None:
        return None if value is None else _measurement(value)

    @field_validator('context_tags')
    @classmethod
    def valid_tags(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(tag not in CONTEXT_TAGS for tag in value):
            raise ValueError('invalid context tags')
        return value


class CheckinPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)
    kind: Literal['exception', 'post_run', 'delayed_followup'] | None = None
    observed_at: datetime | None = None
    fatigue: float | None = None
    illness: Literal['none', 'possible', 'present'] | None = None
    gait_change: Literal['yes', 'no', 'unsure'] | None = None
    context_tags: list[str] | None = None
    activity_id: uuid.UUID | None = None
    prompt_id: uuid.UUID | None = None
    note: str | None = None
    symptoms: list[SymptomInput] | None = None

    @field_validator('observed_at')
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('observed_at must include offset')
        return value.astimezone(UTC)

    @field_validator('fatigue', mode='before')
    @classmethod
    def valid_fatigue(cls, value: object) -> float | None:
        return None if value is None else _measurement(value)

    @field_validator('context_tags')
    @classmethod
    def valid_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (len(value) != len(set(value)) or any(tag not in CONTEXT_TAGS for tag in value)):
            raise ValueError('invalid context tags')
        return value


def _symptoms(session: Session, checkin_id: uuid.UUID) -> list[SymptomReport]:
    return list(session.scalars(select(SymptomReport).where(SymptomReport.checkin_id == checkin_id)
        .order_by(SymptomReport.id)).all())


def _add_symptoms(session: Session, checkin_id: uuid.UUID, items: list[dict]) -> None:
    # The schema has no ordinal column. Encode insertion order in the UUID's
    # high bits so symptom order remains available for idempotency comparison.
    if len(items) >= 65535:
        fail('invalid_checkin', 'Too many symptom reports')
    suffix = checkin_id.int & ((1 << 112) - 1)
    for index, item in enumerate(items, 1):
        symptom_id = uuid.UUID(int=(index << 112) | suffix)
        session.add(SymptomReport(id=symptom_id, checkin_id=checkin_id, **item))


def _symptom_data(row: SymptomReport) -> dict:
    return {key: getattr(row, key) for key in ('id', 'site', 'side', 'severity', 'timing')}


def checkin_data(session: Session, row: Checkin) -> dict:
    guidance = session.scalar(select(DailyGuidance).where(DailyGuidance.checkin_id == row.id)
        .order_by(DailyGuidance.created_at.desc(), DailyGuidance.id.desc()).limit(1))
    return {'id': row.id, 'idempotency_key': row.idempotency_key, 'version': row.version,
        'kind': row.kind, 'observed_at': row.observed_at.astimezone(UTC),
        'recorded_at': row.recorded_at.astimezone(UTC),
        'fatigue': row.fatigue, 'illness': row.illness, 'gait_change': row.gait_change,
        'context_tags': row.context_tags, 'activity_id': row.activity_id,
        'prompt_id': row.prompt_id, 'note': row.note, 'schema_version': row.schema_version,
        'symptoms': [_symptom_data(item) for item in _symptoms(session, row.id)],
        'daily_guidance': guidance_data(guidance) if guidance else None}


def _creation_request(value: dict) -> dict:
    observed_at = value.get('observed_at')
    if isinstance(observed_at, str):
        observed_at = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
    if isinstance(observed_at, datetime):
        observed_at = observed_at.astimezone(UTC).isoformat(timespec='microseconds')
    return ({key: (observed_at if key == 'observed_at' else value.get(key)) for key in ('idempotency_key', 'kind', 'observed_at',
        'fatigue', 'illness', 'gait_change', 'context_tags', 'activity_id', 'prompt_id', 'note')}
        | {'symptoms': [{key: item[key] for key in ('site', 'side', 'severity', 'timing')}
                        for item in value.get('symptoms', [])]})


def _hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(jsonable_encoder(_creation_request(value)),
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _check_related(session: Session, body: dict, *, owner_prompt_id: uuid.UUID | None = None) -> Prompt | None:
    kind = body['kind']
    activity_id = body.get('activity_id')
    if kind in {'post_run', 'delayed_followup'} and activity_id is None:
        fail('activity_required', 'Follow-up check-in requires an activity')
    activity = session.get(Activity, activity_id) if activity_id is not None else None
    if activity_id is not None and activity is None:
        fail('activity_not_found', 'Activity not found', 404)
    if kind in {'post_run', 'delayed_followup'} and (activity is None or activity.sport not in RUN_SPORTS):
        fail('activity_not_run', 'Follow-up check-in requires a run')
    prompt_id = body.get('prompt_id')
    if prompt_id is None:
        return None
    prompt = session.get(Prompt, prompt_id)
    expected_kind = {'post_run': 'rpe', 'delayed_followup': 'delayed_symptom'}.get(kind)
    if (prompt is None or expected_kind is None or prompt.kind != expected_kind
        or prompt.activity_id != activity_id or
        (prompt.status not in {'open', 'expired'} and not
         (prompt.status == 'answered' and prompt.id == owner_prompt_id))):
        fail('prompt_subject_mismatch', 'Prompt does not match check-in subject')
    if (kind == 'post_run' and prompt.status != 'answered'
        and session.scalar(select(SessionRpe.id).where(
            SessionRpe.activity_id == activity_id).limit(1)) is None):
        fail('prompt_subject_mismatch', 'RPE prompt requires a recorded RPE')
    return prompt


def _today(session: Session, observed_at: datetime) -> date:
    profile = current_profile(session)
    return observed_at.astimezone(ZoneInfo(profile.timezone if profile else 'America/New_York')).date()


def create_checkin(session: Session, body: dict) -> tuple[dict, bool]:
    data = CheckinCreate.model_validate(body).model_dump()
    _lock(session)
    existing = session.scalar(select(Checkin).where(Checkin.idempotency_key == data['idempotency_key']))
    if existing:
        original = session.scalar(select(CheckinRevision).where(CheckinRevision.checkin_id == existing.id)
            .order_by(CheckinRevision.version).limit(1))
        original_data = original.payload if original else checkin_data(session, existing)
        if _hash(data) != _hash(original_data):
            fail('idempotency_conflict', 'Check-in key was used for a different body', 409)
        return original_data, False
    prompt = _check_related(session, data)
    symptoms = data.pop('symptoms')
    row = Checkin(**data, version=1, schema_version=2)
    session.add(row)
    session.flush()
    _add_symptoms(session, row.id, symptoms)
    if prompt:
        prompt.status = 'answered'
    session.flush()
    if row.kind == 'exception':
        persist_daily_guidance(session, today=_today(session, row.observed_at),
            checkin_id=row.id, now=datetime.now(UTC))
    return checkin_data(session, row), True


def patch_checkin(session: Session, id: uuid.UUID, body: dict) -> dict:
    patch = CheckinPatch.model_validate(body)
    _lock(session)
    row = session.get(Checkin, id)
    if row is None:
        fail('checkin_not_found', 'Check-in not found', 404)
    if row.version != patch.expected_version:
        fail('version_conflict', 'Check-in changed; reload before editing', 409)
    prior = checkin_data(session, row)
    changes = patch.model_dump(exclude={'expected_version'}, exclude_unset=True)
    candidate = {**_creation_request(prior), **changes}
    if (candidate.get('observed_at') is None or candidate.get('kind') is None
        or candidate.get('context_tags') is None or candidate.get('symptoms') is None):
        fail('invalid_checkin', 'Required check-in fields cannot be null')
    prompt = _check_related(session, candidate, owner_prompt_id=row.prompt_id)
    changed = _hash(candidate) != _hash(prior)
    session.add(CheckinRevision(checkin_id=row.id, version=row.version,
        payload=jsonable_encoder(prior)))
    symptoms = changes.pop('symptoms', None)
    for key, value in changes.items():
        setattr(row, key, value)
    if symptoms is not None:
        for old in _symptoms(session, row.id):
            session.delete(old)
        session.flush()
        _add_symptoms(session, row.id, symptoms)
    if prompt:
        prompt.status = 'answered'
    row.version += 1
    session.flush()
    if changed and row.kind == 'exception':
        persist_daily_guidance(session, today=_today(session, row.observed_at),
            checkin_id=row.id, now=datetime.now(UTC))
    return checkin_data(session, row)


def save_manual_rpe(session: Session, *, activity_id: uuid.UUID | None = None,
        strong_workout_id: uuid.UUID | None = None, manual_session_id: uuid.UUID | None = None,
        rpe: float, now: datetime) -> dict:
    value = _measurement(rpe)
    _lock(session)
    subjects = {'activity_id': activity_id, 'strong_workout_id': strong_workout_id,
                'manual_session_id': manual_session_id}
    if sum(item is not None for item in subjects.values()) != 1:
        fail('invalid_rpe_subject', 'Exactly one RPE subject is required')
    key = next(key for key, subject_id in subjects.items() if subject_id is not None)
    model = {'activity_id': Activity, 'strong_workout_id': StrongWorkoutRow,
             'manual_session_id': ManualSession}[key]
    subject = cast(Any, session.get(model, subjects[key]))
    if subject is None:
        fail('rpe_subject_not_found', 'RPE subject not found', 404)
    if key == 'activity_id' and subject.sport not in RUN_SPORTS:
        fail('rpe_subject_not_run', 'Activity is not a run')
    row = session.scalar(select(SessionRpe).where(getattr(SessionRpe, key) == subjects[key],
        SessionRpe.source == 'manual'))
    end = None
    if key == 'activity_id':
        end = subject.end_at
        if end is None and subject.elapsed_s is not None:
            end = subject.start_at + timedelta(seconds=subject.elapsed_s)
    elif key == 'strong_workout_id' and subject.duration_s is not None:
        profile = current_profile(session)
        zone = ZoneInfo(profile.timezone if profile else 'America/New_York')
        try:
            start = datetime.fromisoformat(subject.local_start).replace(tzinfo=zone)
        except ValueError:
            start = None
        if start is not None:
            end = start.astimezone(UTC) + timedelta(seconds=subject.duration_s)
    elif key == 'manual_session_id' and subject.time is not None and subject.duration_s is not None:
        profile = current_profile(session)
        zone = ZoneInfo(profile.timezone if profile else 'America/New_York')
        start = datetime.combine(subject.date, subject.time, tzinfo=zone)
        end = start.astimezone(UTC) + timedelta(seconds=subject.duration_s)
    delay = max(0, int((now - end).total_seconds())) if end is not None and now >= end else None
    if row is None:
        row = SessionRpe(**subjects, source='manual', rpe=value, collected_at=now,
                         collection_delay_s=delay)
        session.add(row)
    else:
        row.rpe, row.collected_at, row.collection_delay_s = value, now, delay
    session.flush()
    return {key: getattr(row, key) for key in ('activity_id', 'strong_workout_id',
        'manual_session_id', 'rpe', 'source', 'collected_at', 'collection_delay_s')}
