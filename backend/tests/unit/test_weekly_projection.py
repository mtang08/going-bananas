from datetime import date, timedelta
from unittest.mock import Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.calendar_models import SessionCompletion
from app.services import weekly_projection as projection_service
from app.services.weekly_projection import planned_distance


def test_explicit_distance_precedes_structure_and_duration():
    assert planned_distance({'planned_distance_m': 5000, 'planned_duration_s': 3600,
                             'structure': [{'type': 'bad'}]}, None) == (5000, False)


def test_repeats_and_speed_targets_are_estimated():
    row = {'structure': [{'type': 'repeat', 'count': 3, 'steps': [
        {'type': 'work', 'duration_type': 'distance', 'duration_value': 400},
        {'type': 'recovery', 'duration_type': 'time', 'duration_value': 60,
         'target': {'modality': 'speed', 'low': 2, 'high': 4}}]}]}
    assert planned_distance(row, None) == (1740, True)


def test_time_fallback_and_remainder_are_estimated():
    row = {'structure': [{'type': 'work', 'duration_type': 'time', 'duration_value': 600,
                         'target': {'modality': 'hr', 'low': 120, 'high': 150}}],
           'planned_duration_s': 900}
    assert planned_distance(row, 3) == (2700, True)
    assert planned_distance(row, None) == (None, False)
    assert planned_distance({'structure': [{'type': 'bad'}], 'planned_duration_s': 900}, 3) == (None, False)


def test_mixed_structure_does_not_add_duration_again():
    row = {'structure': [
        {'type': 'work', 'duration_type': 'distance', 'duration_value': 1000},
        {'type': 'recovery', 'duration_type': 'time', 'duration_value': 60}],
        'planned_duration_s': 3600}
    assert planned_distance(row, 2) == (1120, True)
    assert planned_distance({'structure': [
        {'type': 'work', 'duration_type': 'distance', 'duration_value': 1000}],
        'planned_duration_s': 3600}, None) == (1000, False)


def test_zero_speed_target_is_preserved_over_history():
    def row(low, high):
        return {'structure': [{'type': 'recovery', 'duration_type': 'time',
                               'duration_value': 60, 'target': {'modality': 'speed',
                               'low': low, 'high': high}}]}
    assert planned_distance(row(0, 0), 3) == (0, True)
    assert planned_distance(row(0, 2), 3) == (60, True)


@pytest.mark.parametrize(
    ('days_ago', 'subject_field', 'unrecorded_past'),
    [
        (1, 'activity_id', 0),
        (0, 'activity_id', 0),
        (0, 'strong_workout_id', 0),
        (0, 'manual_session_id', 0),
        (1, None, 1),
    ],
)
def test_unknown_completion_projection(monkeypatch, days_ago, subject_field, unrecorded_past):
    today = date(2026, 11, 18)
    session_uid = uuid4()
    completion = SessionCompletion(session_uid=session_uid, status='unknown')
    if subject_field is not None:
        setattr(completion, subject_field, uuid4())
    plan = [
        {'kind': 'run', 'session_uid': session_uid, 'local_date': today - timedelta(days=days_ago),
         'planned_distance_m': 5000},
        {'kind': 'run', 'session_uid': uuid4(), 'local_date': today, 'planned_distance_m': 3000},
    ]
    session = Mock(spec=Session)
    session.get.return_value = None
    session.scalars.side_effect = [Mock(all=Mock(return_value=[completion])), Mock(all=Mock(return_value=[]))]
    monkeypatch.setattr(projection_service.calendar, '_today', lambda session: today)
    monkeypatch.setattr(projection_service.calendar, 'state_at', lambda session, head: plan)
    monkeypatch.setattr(projection_service, 'athlete_tz', lambda session: ZoneInfo('UTC'))
    monkeypatch.setattr(projection_service, 'load_runs', lambda *args: [])
    monkeypatch.setattr(projection_service, 'activities_coverage_complete', lambda *args: True)

    result = projection_service.weekly_projection(session)

    assert result['unrecorded_past_runs'] == unrecorded_past
    assert result['remaining_runs'] == 1
    assert result['remaining_distance_m'] == 3000
    assert result['missing_planned_runs'] == 0
