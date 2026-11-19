"""Weekly planned-versus-done digest. Read-only; one loader serves the API and the coach."""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Literal, get_args

from app.domain.session_class import HARD_CLASSES
from app.services.calendar_structure import StructureError, expand_structure

DIGEST_SCHEMA = 'weekly_digest.v1'
Outcome = Literal['completed', 'modified', 'partial', 'moved', 'missed', 'recorded', 'not_recorded', 'planned']
OUTCOMES: tuple[Outcome, ...] = get_args(Outcome)
DONE_OUTCOMES = frozenset({'completed', 'modified', 'partial', 'moved', 'recorded'})
NOT_DONE_OUTCOMES = frozenset({'missed', 'not_recorded'})
HEADLINE_KINDS = ('run', 'strength', 'cross')
REPORTED_KINDS = ('run', 'strength', 'cross', 'mobility')
KEY_CLASSES = HARD_CLASSES
PACE_WINDOW_DAYS = 28
_STATUS_OUTCOME: dict[str, Outcome] = {'completed_as_planned': 'completed', 'completed_modified': 'modified',
    'partial': 'partial', 'moved': 'moved', 'skipped': 'missed'}
_SUBJECT_FIELDS = (('activity_id', 'activity'), ('strong_workout_id', 'strong_workout'),
                   ('manual_session_id', 'manual_session'))


def week_bounds(day: date) -> tuple[date, date]:
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def session_outcome(local_date: date, completion: dict | None, today: date) -> Outcome:
    status = completion.get('status') if completion else None
    if status in _STATUS_OUTCOME:
        return _STATUS_OUTCOME[status]
    if completion and any(completion.get(field) for field, _ in _SUBJECT_FIELDS):
        return 'recorded'
    return 'not_recorded' if local_date < today else 'planned'


def _amount(value: object, *, positive: bool = False) -> float | None:
    ok = (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
          and (value > 0 if positive else value >= 0))
    return float(value) if ok else None  # type: ignore[arg-type]


def planned_duration_s(row: dict) -> float | None:
    direct = _amount(row.get('planned_duration_s'), positive=True)
    if direct is not None:
        return direct
    if not row.get('structure'):
        return None
    try:
        steps = expand_structure(row['structure'])
    except StructureError:
        return None
    if any(step['duration_type'] != 'time' for step in steps):
        return None
    return float(sum(step['duration_value'] for step in steps))
