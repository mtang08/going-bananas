from datetime import date

import pytest

from app.services.weekly_digest import planned_duration_s, session_outcome, week_bounds

TODAY = date(2030, 1, 9)


def _c(status, **subject):
    return {'status': status, 'activity_id': None, 'strong_workout_id': None, 'manual_session_id': None, **subject}


@pytest.mark.parametrize('day, completion, expected', [
    (8, _c('completed_as_planned', activity_id='a'), 'completed'),
    (8, _c('completed_modified', activity_id='a'), 'modified'),
    (8, _c('partial', activity_id='a'), 'partial'),
    (8, _c('moved', activity_id='a'), 'moved'),
    (8, _c('skipped'), 'missed'),
    (8, _c('unknown', activity_id='a'), 'recorded'),
    (8, _c('extra', strong_workout_id='w'), 'recorded'),
    (8, None, 'not_recorded'),
    (8, _c('unknown'), 'not_recorded'),
    (9, None, 'planned'),
    (12, None, 'planned'),
])
def test_session_outcome_table(day, completion, expected):
    assert session_outcome(date(2030, 1, day), completion, TODAY) == expected



def test_week_bounds_sunday_and_monday():
    monday = date(2030, 1, 7)
    sunday = date(2030, 1, 13)
    assert week_bounds(sunday) == (monday, sunday)
    assert week_bounds(monday) == (monday, sunday)


def test_planned_duration_prefers_direct_then_time_structure():
    time_step = {'type': 'work', 'duration_type': 'time', 'duration_value': 600, 'target': None}
    time_structure = [time_step, {**time_step, 'duration_value': 300}]
    distance_step = {**time_step, 'duration_type': 'distance'}

    assert planned_duration_s({'planned_duration_s': 1800, 'structure': time_structure}) == 1800.0
    assert planned_duration_s({'structure': time_structure}) == 900.0
    assert planned_duration_s({'structure': [distance_step]}) is None
    assert planned_duration_s({'structure': [{'type': 'bad'}]}) is None
    assert planned_duration_s({'planned_duration_s': 0}) is None
