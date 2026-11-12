from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import strength_routine as routine


def _workout(name, day, duration, *lifts):
    return {'workout_name': name, 'local_date': day, 'duration_s': duration,
            'sets': [{'Exercise Name': lift, 'Weight': 'unknown'} for lift in lifts]}


def test_strong_suggestions_are_deterministic_and_advisory():
    workouts = [
        _workout('A', '2026-11-02', 3600, 'Squat', 'RDL'),
        _workout('A', '2026-11-09', 3600, 'Squat', 'RDL'),
        _workout('B', '2026-11-06', 3300, 'Deadlift', 'Lunge'),
        _workout('B', '2026-11-13', 3300, 'Deadlift', 'Lunge'),
    ]
    slots = routine.suggest_slots(workouts)
    assert [(slot['label'], slot['default_weekday'], slot['typical_duration_s'])
            for slot in slots] == [('A', 0, 3600), ('B', 4, 3300)]
    assert slots[0]['main_lower_body_lifts'] == ['RDL', 'Squat']
    assert slots[1]['main_lower_body_lifts'] == ['Deadlift', 'Lunge']
    assert all(slot['lower_body_cost'] == 'moderate' and slot['id'] is None for slot in slots)
    assert routine.suggest_slots([
        _workout('A', '2026-11-02', 3300), _workout('A', '2026-11-09', 3600),
    ])[0]['typical_duration_s'] == 3600
    assert routine.suggest_slots([_workout('A', '2026-11-02', 100)])[0]['typical_duration_s'] == 300
    assert [(slot['label'], slot['default_weekday']) for slot in routine.suggest_slots([])] == [
        ('Full body A', 0), ('Full body B', 4)]


def test_routine_slot_validation():
    valid = {'label': '  A  ', 'default_weekday': 0, 'lower_body_cost': 'moderate',
             'typical_duration_s': 1800, 'main_lower_body_lifts': [' Squat ']}
    assert routine._validate_slot(valid)['main_lower_body_lifts'] == ['Squat']
    for patch in ({'label': ' '}, {'default_weekday': 7}, {'typical_duration_s': 0},
                  {'main_lower_body_lifts': ['']}, {'lower_body_cost': 'unknown'}):
        with pytest.raises(HTTPException):
            routine._validate_slot({**valid, **patch})


def test_partial_week_assigns_same_template_as_full_week(monkeypatch):
    profile = SimpleNamespace(timezone='America/New_York', effective_at=datetime(2026, 10, 1, tzinfo=UTC),
        strength_days_confirmed=True, strength_schedule_mode='alternating',
        strength_week_a_start=date(2026, 11, 2), strength_week_a_days=[0, 4],
        strength_week_b_days=[1, 5], mobility_week_a_days=[2], mobility_week_b_days=[3],
        mobility_optional_days=[6])
    slots = [SimpleNamespace(id=uuid.uuid4(), label='A'), SimpleNamespace(id=uuid.uuid4(), label='B')]
    monkeypatch.setattr(routine, 'current_profile', lambda session: profile)
    monkeypatch.setattr(routine, '_current_slots', lambda session: slots)
    full = routine.routine_occurrences(None, date(2026, 11, 2), date(2026, 11, 15))
    partial = routine.routine_occurrences(None, date(2026, 11, 6), date(2026, 11, 6))
    assert [(row['date'], row['kind']) for row in full] == [
        ('2026-11-02', 'strength'), ('2026-11-04', 'mobility'), ('2026-11-06', 'strength'),
        ('2026-11-08', 'mobility'), ('2026-11-10', 'strength'), ('2026-11-12', 'mobility'),
        ('2026-11-14', 'strength'), ('2026-11-15', 'mobility')]
    assert partial[0]['label'] == 'B'
    assert partial[0]['strength_slot_id'] == full[2]['strength_slot_id']
    monkeypatch.setattr(routine, '_current_slots', lambda session: [])
    monkeypatch.setattr(routine, 'routine_view', lambda session: {'slots': [
        {'label': 'Full body A'}, {'label': 'Full body B'}]})
    suggested = routine.routine_occurrences(None, date(2026, 11, 6), date(2026, 11, 6))
    assert suggested[0]['label'] == 'Full body B'
    assert 'strength_slot_id' not in suggested[0]
