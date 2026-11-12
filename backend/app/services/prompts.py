"""Idempotent, source-derived prompt transitions. Caller owns the transaction."""
from __future__ import annotations

import math
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.checkin_models import Checkin, SessionRpe, SymptomReport
from app.metric_models import MetricResult, Prompt
from app.metrics.engine import load_runs
from app.models import Activity, AppState, ManualSession
from app.services.timezone import athlete_tz
from app.strong_models import StrongWorkoutRow

RUN_SPORTS = frozenset(('running', 'trail_running', 'treadmill_running'))
MATCH_KINDS = frozenset(('missing_activity', 'unmatched_session'))
TIMED_KINDS = frozenset(('rpe', 'delayed_symptom'))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('naive_prompt_clock')
    return value.astimezone(UTC)


def _id(kind: str, subject: str) -> str:
    return f'{kind}:{subject}'


def _answered(kind: str, subject: str, facts: dict[str, Any], existing: dict[str, Any] | None) -> bool:
    if kind == 'rpe':
        activity = next((a for a in facts.get('activities', []) if str(a['id']) == subject), None)
        value = activity.get('effective_rpe') if activity else None
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and 0 <= value <= 10)
    if kind == 'delayed_symptom':
        prompt_id = str(existing['id']) if existing and existing.get('id') is not None else None
        return any(checkin.get('kind') == 'delayed_followup' and (
            str(checkin.get('activity_id')) == subject
            or prompt_id is not None and str(checkin.get('prompt_id')) == prompt_id)
            for checkin in facts.get('checkins', []))
    completion = next((c for c in facts.get('completions', [])
                       if str(c['session_uid']) == subject), None)
    if completion is None:
        return False
    valid = facts.get('valid_subjects', {})
    linked = any(completion.get(field) is not None for field in
                 ('activity_id', 'strong_workout_id', 'manual_session_id'))
    if linked:
        return any(completion.get(field) is not None and str(completion[field]) in set(valid.get(kind, ()))
           for field, kind in (('activity_id', 'activity'), ('strong_workout_id', 'strong_workout'),
                               ('manual_session_id', 'manual_session')))
    return completion.get('match_method') == 'user_marked' and completion.get('status') in ('skipped', 'unknown')


def _desired(facts: dict[str, Any], now: datetime) -> dict[str, dict[str, Any]]:
    desired: dict[str, dict[str, Any]] = {}
    today = facts['local_today']
    if isinstance(today, str):
        today = date.fromisoformat(today)
    if not isinstance(today, date):
        raise ValueError('invalid_local_today')
    activities = facts.get('activities', [])
    checkins = facts.get('checkins', [])
    for activity in activities:
        subject = str(activity['id'])
        end = activity.get('end_at')
        if end is None:
            continue
        end = _aware(end)
        if end > now:
            continue
        close = end + timedelta(hours=48)
        desired[_id('rpe', subject)] = {
            'kind': 'rpe', 'activity_id': subject, 'session_uid': None,
            'opens_at': end, 'closes_at': close,
        }
        start = _aware(activity['start_at'])
        prior_symptom = any(
            start - timedelta(days=14) <= _aware(checkin['observed_at']) < start
            and any(isinstance(severity, (float, int)) and severity > 0
                    for severity in checkin.get('symptoms', []))
            for checkin in checkins)
        if activity.get('is_long') or prior_symptom:
            desired[_id('delayed_symptom', subject)] = {
                'kind': 'delayed_symptom', 'activity_id': subject, 'session_uid': None,
                'opens_at': end + timedelta(hours=16), 'closes_at': close,
            }
    first = today - timedelta(days=7)
    for result in facts.get('planned_actual', []):
        if result.get('kind') != 'run' or result.get('deleted'):
            continue
        day = result['local_date']
        if isinstance(day, str):
            day = date.fromisoformat(day)
        subject = str(result['session_uid'])
        reasons = set(result.get('reason_codes') or [])
        if first <= day < today and 'NO_ACTIVITY_FOUND' in reasons:
            desired[_id('missing_activity', subject)] = {
                'kind': 'missing_activity', 'activity_id': None, 'session_uid': subject,
                'opens_at': now, 'closes_at': None,
            }
        if first <= day <= today and reasons.intersection(('AMBIGUOUS_MATCH', 'MOVE_CANDIDATE')):
            desired[_id('unmatched_session', subject)] = {
                'kind': 'unmatched_session', 'activity_id': None, 'session_uid': subject,
                'opens_at': now, 'closes_at': None,
            }
    return desired


def prompt_changes(facts: dict, existing: list[dict], now: datetime) -> dict:
    """Return create/update intents and transition counts without mutating inputs."""
    now = _aware(now)
    desired = _desired(facts, now)
    old = {_id(row['kind'], str(row.get('activity_id') or row.get('session_uid'))): row
           for row in existing}
    create: list[dict[str, Any]] = []
    update: list[dict[str, Any]] = []
    counts = {'created': 0, 'expired': 0, 'answered': 0}
    for key, payload in sorted(desired.items()):
        previous = old.get(key)
        answered = _answered(payload['kind'], str(payload['activity_id'] or payload['session_uid']), facts, previous)
        status = 'answered' if answered else 'expired' if payload['closes_at'] is not None and payload['closes_at'] <= now else 'open'
        if previous is None:
            create.append({**payload, 'key': key, 'status': status})
            counts['created'] += 1
            if status in ('answered', 'expired'):
                counts[status] += 1
        elif previous['status'] not in ('dismissed', 'answered'):
            if answered:
                next_status = 'answered'
            elif previous['status'] == 'expired':
                next_status = 'expired'
            elif key not in desired or (previous.get('closes_at') is not None
                                         and _aware(previous['closes_at']) <= now):
                next_status = 'expired'
            else:
                next_status = 'open'
            if next_status != previous['status']:
                update.append({'key': key, 'status': next_status})
                if next_status in ('answered', 'expired'):
                    counts[next_status] += 1
    for key, previous in sorted(old.items()):
        if key not in desired and previous['status'] not in ('dismissed', 'answered'):
            subject = str(previous.get('activity_id') or previous.get('session_uid'))
            if _answered(previous['kind'], subject, facts, previous):
                update.append({'key': key, 'status': 'answered'})
                counts['answered'] += 1
            elif previous['status'] == 'open':
                update.append({'key': key, 'status': 'expired'})
                counts['expired'] += 1
    return {'create': create, 'update': update, 'counts': counts}


def _eligible_run_rows(session: Session, run_rows: list[Activity], zone: ZoneInfo) -> list[Activity]:
    if not run_rows:
        return []
    dates = [row.start_at.astimezone(zone).date() for row in run_rows]
    eligible_ids = {fact.activity_id for fact in load_runs(session, min(dates), max(dates) + timedelta(days=1))}
    return [row for row in run_rows if row.id in eligible_ids]


def _facts(session: Session, now: datetime) -> dict[str, Any]:
    zone: ZoneInfo = athlete_tz(session)
    today = now.astimezone(zone).date()
    run_rows = _eligible_run_rows(session, list(session.scalars(select(Activity).where(
        Activity.sport.in_(RUN_SPORTS))).all()), zone)
    ids = [str(row.id) for row in run_rows]
    long_rows = list(session.scalars(select(MetricResult).where(
        MetricResult.metric_id == 'long_run_exposure', MetricResult.subject_type == 'activity',
        MetricResult.is_current.is_(True), MetricResult.subject_key.in_(ids))).all()) if ids else []
    long_by_id = {row.subject_key: row for row in long_rows}
    rpe_rows = list(session.scalars(select(SessionRpe).where(
        SessionRpe.activity_id.in_([row.id for row in run_rows]))).all()) if run_rows else []
    rpe_by_activity: dict[uuid.UUID, dict[str, float]] = {}
    for rpe_row in rpe_rows:
        if rpe_row.activity_id is not None:
            rpe_by_activity.setdefault(rpe_row.activity_id, {})[rpe_row.source] = rpe_row.rpe
    activities = []
    for activity_row in run_rows:
        source = rpe_by_activity.get(activity_row.id, {})
        long_result = long_by_id.get(str(activity_row.id))
        long_value = long_result.value if long_result and isinstance(long_result.value, dict) else {}
        activities.append({
            'id': str(activity_row.id), 'start_at': activity_row.start_at, 'end_at': activity_row.end_at,
            'effective_rpe': source.get('manual', source.get('garmin_fit', activity_row.workout_rpe)),
            'is_long': long_value.get('classification') == 'long',
        })
    checkin_rows = list(session.scalars(select(Checkin)).all())
    report_rows = list(session.scalars(select(SymptomReport)).all())
    reports_by_checkin: dict[uuid.UUID, list[float]] = {}
    for report_row in report_rows:
        reports_by_checkin.setdefault(report_row.checkin_id, []).append(report_row.severity)
    checkins = [{
        'id': str(row.id), 'kind': row.kind, 'observed_at': row.observed_at,
        'activity_id': str(row.activity_id) if row.activity_id else None,
        'prompt_id': str(row.prompt_id) if row.prompt_id else None,
        'symptoms': reports_by_checkin.get(row.id, []),
    } for row in checkin_rows]
    state = session.get(AppState, 1)
    head = state.calendar_head_version if state else 0
    revisions: dict[uuid.UUID, CalendarSessionRevision] = {}
    if head > 0:
        rows = session.scalars(select(CalendarSessionRevision).where(
            CalendarSessionRevision.calendar_version_number <= head)
            .order_by(CalendarSessionRevision.session_uid,
                      CalendarSessionRevision.calendar_version_number.desc(),
                      CalendarSessionRevision.revision.desc())).all()
        for revision_row in rows:
            revisions.setdefault(revision_row.session_uid, revision_row)
    revisions = {uid: revision for uid, revision in revisions.items()
                 if today - timedelta(days=7) <= revision.local_date <= today}
    metric_keys = [str(uid) for uid in revisions]
    metric_rows = list(session.scalars(select(MetricResult).where(
        MetricResult.metric_id == 'planned_actual_session', MetricResult.is_current.is_(True),
        MetricResult.subject_key.in_(metric_keys))).all()) if metric_keys else []
    metric_by_uid = {row.subject_key: row for row in metric_rows}
    planned_actual = [{
        'session_uid': str(uid), 'local_date': revision.local_date,
        'kind': revision.kind, 'deleted': revision.deleted,
        'reason_codes': metric_by_uid[str(uid)].reason_codes,
    } for uid, revision in revisions.items() if str(uid) in metric_by_uid]
    completions = [{
        'session_uid': str(row.session_uid), 'activity_id': row.activity_id,
        'strong_workout_id': row.strong_workout_id, 'manual_session_id': row.manual_session_id,
        'match_method': row.match_method, 'status': row.status,
    } for row in session.scalars(select(SessionCompletion)).all()]
    valid_subjects = {
        'activity': [str(row.id) for row in run_rows],
        'strong_workout': [str(id_) for id_ in session.scalars(select(StrongWorkoutRow.id).where(
            StrongWorkoutRow.resolution_state == 'resolved')).all()],
        'manual_session': [str(id_) for id_ in session.scalars(select(ManualSession.id)).all()],
    }
    return {'activities': activities, 'checkins': checkins, 'completions': completions,
            'planned_actual': planned_actual, 'local_today': today, 'timezone': zone.key,
            'valid_subjects': valid_subjects}


def generate_prompts(session: Session, now: datetime) -> dict[str, int]:
    """Apply derived state in the caller transaction without committing or bumping revisions."""
    now = _aware(now)
    existing = list(session.scalars(select(Prompt)).all())
    rows = [{
        'id': str(row.id), 'kind': row.kind,
        'activity_id': str(row.activity_id) if row.activity_id else None,
        'session_uid': str(row.session_uid) if row.session_uid else None,
        'opens_at': row.opens_at, 'closes_at': row.closes_at, 'status': row.status,
    } for row in existing]
    changes = prompt_changes(_facts(session, now), rows, now)
    by_key = {_id(row.kind, str(row.activity_id or row.session_uid)): row for row in existing}
    counts = {'created': 0, 'expired': 0, 'answered': 0}
    for item in changes['create']:
        result = session.execute(insert(Prompt).values(
            kind=item['kind'], activity_id=uuid.UUID(item['activity_id']) if item['activity_id'] else None,
            session_uid=uuid.UUID(item['session_uid']) if item['session_uid'] else None,
            opens_at=item['opens_at'], closes_at=item['closes_at'], status=item['status'],
        ).on_conflict_do_nothing().returning(Prompt.id))
        if result.scalar_one_or_none() is not None:
            counts['created'] += 1
            if item['status'] in ('expired', 'answered'):
                counts[item['status']] += 1
    for item in changes['update']:
        row = by_key[item['key']]
        if row.status != item['status']:
            row.status = item['status']
            if row.status in ('expired', 'answered'):
                counts[row.status] += 1
    return counts
