"""Strength templates are advisory; profile recurrence remains the date authority."""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.core import current_profile, fail, profile_data
from app.domain.cycle import recurring_sessions
from app.models import AppState
from app.planning_models import StrengthRoutineSlot
from app.strong_models import StrongWorkoutRow

LOCK_ID = 71382413
_LIFT = re.compile(r'squat|deadlift|lunge|rdl|leg press|hip thrust|step up|leg curl', re.I)
_SCHEDULE_FIELDS = ('strength_days_confirmed', 'strength_schedule_mode', 'scheduled_strength_days',
    'strength_week_a_start', 'strength_week_a_days', 'strength_week_b_days',
    'mobility_week_a_days', 'mobility_week_b_days', 'mobility_optional_days')


def confirmed_schedule(session: Session) -> dict:
    data = profile_data(current_profile(session))
    return {field: data[field] for field in _SCHEDULE_FIELDS}


def _slot_data(row: StrengthRoutineSlot) -> dict:
    return {'id': row.id, 'version': row.version, 'label': row.label,
        'default_weekday': row.default_weekday, 'lower_body_cost': row.lower_body_cost,
        'typical_duration_s': row.typical_duration_s,
        'main_lower_body_lifts': row.main_lower_body_lifts, 'active': row.active}


def _version(session: Session) -> int:
    return session.scalar(select(func.max(StrengthRoutineSlot.version))) or 0


def _current_slots(session: Session) -> list[StrengthRoutineSlot]:
    version = _version(session)
    return list(session.scalars(select(StrengthRoutineSlot).where(
        StrengthRoutineSlot.version == version, StrengthRoutineSlot.active.is_(True))
        .order_by(StrengthRoutineSlot.label, StrengthRoutineSlot.id)).all())


def suggest_slots(workouts: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for workout in workouts:
        name = str(workout.get('workout_name') or '').strip()
        if name:
            grouped[name].append(workout)
    chosen = sorted(grouped, key=lambda name: (-len(grouped[name]), name))[:2]
    suggestions = []
    for name in chosen:
        rows = grouped[name]
        weekdays = Counter(date.fromisoformat(str(row['local_date'])).weekday() for row in rows)
        weekday = min(weekdays, key=lambda day: (-weekdays[day], day))
        durations = [value for row in rows if (value := row.get('duration_s')) is not None
                     and isinstance(value, (int, float)) and math.isfinite(value) and value > 0]
        median = statistics.median(durations) if durations else None
        rounded_duration = max(300, int(math.floor(median / 300 + .5) * 300)) if median is not None else None
        lifts: Counter[str] = Counter()
        canonical: dict[str, str] = {}
        for row in rows:
            seen = set()
            for item in row.get('sets') or []:
                lift = str(item.get('Exercise Name') or '').strip()
                key = lift.casefold()
                if lift and _LIFT.search(lift) and key not in seen:
                    seen.add(key)
                    lifts[key] += 1
                    canonical[key] = min(lift, canonical.get(key, lift), key=str.casefold)
        top_lifts = [canonical[key] for key in sorted(lifts, key=lambda key: (-lifts[key], key))[:3]]
        suggestions.append({'id': None, 'version': 0, 'label': name[:40],
            'default_weekday': weekday, 'lower_body_cost': 'moderate',
            'typical_duration_s': rounded_duration,
            'main_lower_body_lifts': top_lifts, 'active': True})
    pads = [('Full body A', 0), ('Full body B', 4)]
    while len(suggestions) < 2:
        label, day = pads[len(suggestions)]
        suggestions.append({'id': None, 'version': 0, 'label': label,
            'default_weekday': day, 'lower_body_cost': 'moderate',
            'typical_duration_s': None, 'main_lower_body_lifts': [], 'active': True})
    return suggestions


def routine_view(session: Session) -> dict:
    version = _version(session)
    if version:
        return {'version': version, 'slots': [_slot_data(row) for row in _current_slots(session)],
                'suggested': False, 'schedule': confirmed_schedule(session)}
    profile = current_profile(session)
    today = datetime.now(UTC).astimezone(ZoneInfo(profile.timezone if profile else 'America/New_York')).date()
    rows = session.scalars(select(StrongWorkoutRow).where(
        StrongWorkoutRow.resolution_state == 'resolved',
        StrongWorkoutRow.local_date.between(today - timedelta(days=55), today))
        .order_by(StrongWorkoutRow.local_date, StrongWorkoutRow.id)).all()
    data = [{'workout_name': row.workout_name, 'local_date': row.local_date,
             'duration_s': row.duration_s, 'sets': row.sets} for row in rows]
    return {'version': 0, 'slots': suggest_slots(data), 'suggested': True,
            'schedule': confirmed_schedule(session)}


def _validate_slot(item: dict) -> dict:
    allowed = {'label', 'default_weekday', 'lower_body_cost', 'typical_duration_s',
               'main_lower_body_lifts', 'active'}
    if set(item) - allowed:
        fail('invalid_routine_slot', 'Unexpected routine slot field')
    label = item.get('label')
    weekday = item.get('default_weekday')
    cost = item.get('lower_body_cost')
    duration = item.get('typical_duration_s')
    lifts = item.get('main_lower_body_lifts', [])
    if not isinstance(label, str) or not label.strip() or len(label.strip()) > 40:
        fail('invalid_routine_slot', 'Routine label must be 1–40 characters')
    if type(weekday) is not int or weekday not in range(7):
        fail('invalid_routine_slot', 'Weekday must be 0–6')
    if cost not in {'low', 'moderate', 'high'}:
        fail('invalid_routine_slot', 'Invalid lower body cost')
    if duration is not None and (type(duration) is not int or duration <= 0):
        fail('invalid_routine_slot', 'Duration must be positive seconds')
    if not isinstance(lifts, list) or any(not isinstance(lift, str) or not lift.strip() for lift in lifts):
        fail('invalid_routine_slot', 'Lift names must be nonblank')
    if type(item.get('active', True)) is not bool:
        fail('invalid_routine_slot', 'Active must be boolean')
    return {'label': label.strip(), 'default_weekday': weekday, 'lower_body_cost': cost,
        'typical_duration_s': duration, 'main_lower_body_lifts': [lift.strip() for lift in lifts],
        'active': item.get('active', True)}


def replace_routine(session: Session, expected_version: int, slots: list[dict]) -> dict:
    session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': LOCK_ID})
    state = session.get(AppState, 1, with_for_update=True)
    if state is None or state.planning_authority != 'calendar':
        fail('planning_not_active', 'Calendar planning is not active', 409)
    version = _version(session)
    if version != expected_version:
        fail('version_conflict', 'Routine changed; reload before editing', 409)
    if not slots:
        fail('routine_empty', 'At least one routine slot is required')
    validated = [_validate_slot(item) for item in slots]
    for item in validated:
        session.add(StrengthRoutineSlot(version=version + 1, **item))
    session.flush()
    return routine_view(session)


def routine_occurrences(session: Session, start: date, end: date) -> list[dict]:
    if end < start:
        return []
    profile = current_profile(session)
    monday = start - timedelta(days=start.weekday())
    sunday = end + timedelta(days=6-end.weekday())
    all_rows = recurring_sessions(monday, sunday, profile)
    slots = sorted(_current_slots(session), key=lambda row: (row.label, str(row.id)))
    suggested = routine_view(session)['slots'] if not slots else []
    positions: dict[date, int] = defaultdict(int)
    result = []
    for row in all_rows:
        day = date.fromisoformat(row['date'])
        if row['kind'] == 'strength':
            week = day - timedelta(days=day.weekday())
            position = positions[week]
            positions[week] += 1
            if slots:
                slot = slots[position % len(slots)]
                row = {**row, 'strength_slot_id': slot.id, 'label': slot.label}
            elif suggested:
                row = {**row, 'label': suggested[position % len(suggested)]['label']}
        if start <= day <= end:
            result.append(row)
    return result
