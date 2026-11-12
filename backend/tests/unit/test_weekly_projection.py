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
