from __future__ import annotations

from dataclasses import replace

import pytest

from app.metrics.intervals import (
    ExecStream,
    FitStep,
    LapIn,
    PlanStep,
    after_timer_seconds,
    clip,
    execution_outcome,
    expand_fit,
    expand_plan,
    weighted_median,
)


def example() -> tuple[list[PlanStep], list[FitStep], list[LapIn], ExecStream]:
    structure = [
        {'type': 'warmup', 'duration_type': 'time', 'duration_value': 600, 'target': None},
        {'type': 'repeat', 'count': 4, 'steps': [
            {'type': 'work', 'duration_type': 'time', 'duration_value': 300,
             'target': {'modality': 'speed', 'low': 3.8, 'high': 3.95, 'effort_cue': None}},
            {'type': 'recovery', 'duration_type': 'time', 'duration_value': 120, 'target': None},
        ]},
        {'type': 'cooldown', 'duration_type': 'time', 'duration_value': 600, 'target': None},
    ]
    plan = expand_plan(structure)
    fit = [
        FitStep(0, 'time', 'warmup', 600),
        FitStep(1, 'time', 'active', 300),
        FitStep(2, 'time', 'recovery', 120),
        FitStep(3, 'repeat_until_steps_cmplt', repeat_from=1, repeat_count=4),
        FitStep(4, 'time', 'cooldown', 600),
    ]
    starts = [0, 600, 900, 1020, 1320, 1440, 1740, 1860, 2160, 2280]
    durations = [600, 300, 120, 300, 120, 300, 120, 300, 120, 600]
    distances = [1800, 1152, 360, 1164, 360, 1158, 360, 1134, 360, 1800]
    indices = [0, 1, 2, 1, 2, 1, 2, 1, 2, 4]
    laps = [LapIn(i, start, duration, duration, distance, index)
            for i, (start, duration, distance, index) in enumerate(zip(starts, durations, distances, indices))]
    speed = [3.0] * 2881
    hr = [140.0] * 2881
    for start, value, bpm in [(600, 3.84, 160), (1020, 3.88, 161),
                              (1440, 3.86, 162), (1860, 3.78, 163)]:
        speed[start:start + 300] = [value] * 300
        hr[start:start + 300] = [float(bpm)] * 300
    stream = ExecStream(list(range(2881)), hr, speed, [(0, 2880)])
    return plan, fit, laps, stream


def test_ex1_numeric_and_mapping() -> None:
    plan, fit, laps, stream = example()
    outcome = execution_outcome(plan, fit, laps, stream)
    value = outcome['value']
    assert outcome['status'] == 'available'
    assert outcome['quality_status'] == 'good'
    assert (value['n_planned'], value['n_observed'], value['n_completed']) == (4, 4, 4)
    assert [rep['completion_ratio'] for rep in value['reps']] == [1.0] * 4
    assert [rep['mean_speed_mps'] for rep in value['reps']] == [3.84, 3.88, 3.86, 3.78]
    assert [rep['in_target'] for rep in value['reps']] == [True, True, True, False]
    assert [rep['hr_median_bpm'] for rep in value['reps']] == [160, 161, 162, 163]
    assert [rep['lap_index'] for rep in value['reps']] == [1, 3, 5, 7]
    assert [rep['planned_step'] for rep in value['reps']] == [2, 4, 6, 8]
    assert [rep['step_path'] for rep in value['reps']] == ['1.steps.0'] * 4
    assert [rep['repeat_index'] for rep in value['reps']] == [0, 1, 2, 3]
    assert value['cv_speed'] == 1.125
    assert value['last_first_change_pct'] == -1.563
    assert value['completed_work_s'] == 1200
    assert value['completed_work_m'] == 4608
    assert value['planned_work_s'] == 1200
    assert value['planned_work_m'] is None
    assert value['target_coverage'] == .75
    assert value['step_completion_ratio'] == 1


def test_stopped_two_and_partial_final() -> None:
    plan, fit, laps, stream = example()
    stopped = execution_outcome(plan, fit, laps[:4], stream)
    value = stopped['value']
    assert stopped['status'] == 'partial'
    assert 'INCOMPLETE_WORK_STEPS' in stopped['reason_codes']
    assert (value['n_observed'], value['n_completed'], value['step_completion_ratio']) == (2, 2, .5)
    assert [rep['status'] for rep in value['reps'][2:]] == ['missing', 'missing']
    assert value['cv_speed'] == .733
    assert value['last_first_change_pct'] is None
    assert value['completed_work_s'] == 600
    assert value['completed_work_m'] == 2316
    assert value['target_coverage'] == 1
    partial_laps = laps.copy()
    partial_laps[7] = replace(laps[7], timer_s=150, elapsed_s=150, distance_m=567)
    partial = execution_outcome(plan, fit, partial_laps, stream)
    value = partial['value']
    assert (value['n_observed'], value['n_completed'], value['step_completion_ratio']) == (4, 3, .75)
    assert value['reps'][-1]['completion_ratio'] == .5
    assert value['last_first_change_pct'] is None
    assert value['completed_work_s'] == 1050
    assert value['completed_work_m'] == 4041


def test_unknown_lap_totals_and_absent_work() -> None:
    plan, fit, laps, stream = example()
    one_null = laps.copy()
    one_null[1] = replace(laps[1], timer_s=None)
    out = execution_outcome(plan, fit, one_null, stream)
    assert out['status'] == 'partial'
    assert out['value']['n_completed'] == 3
    assert out['value']['completed_work_s'] == 900
    assert 'PARTIAL_WORK_TIMER' in out['quality_flags']
    assert 'WORK_MEASUREMENT_MISSING' in out['reason_codes']
    assert out['value']['reps'][0]['hr_median_bpm'] is None
    assert 'HR_TIMER_UNKNOWN' in out['value']['reps'][0]['flags']
    all_null_timer = [replace(lap, timer_s=None) if lap.lap_index in (1, 3, 5, 7) else lap for lap in laps]
    out = execution_outcome(plan, fit, all_null_timer, stream)
    assert out['value']['completed_work_s'] is None
    assert out['value']['n_completed'] == 0
    all_null_distance = [replace(lap, distance_m=None) if lap.lap_index in (1, 3, 5, 7) else lap for lap in laps]
    out = execution_outcome(plan, fit, all_null_distance, stream)
    assert out['value']['completed_work_m'] is None
    assert out['value']['n_completed'] == 4
    assert out['status'] == 'partial'
    out = execution_outcome(plan, fit, [laps[0]], stream)
    assert out['value']['n_observed'] == 0
    assert out['value']['completed_work_s'] == 0
    assert out['value']['completed_work_m'] == 0


def test_required_and_optional_trace() -> None:
    plan, fit, laps, stream = example()
    required = execution_outcome(plan, fit, laps, None)
    assert required['status'] == 'partial'
    assert required['quality_status'] is None
    assert required['value']['n_completed'] == 4
    assert all(rep['speed_status'] == 'not_assessable' and
               rep['speed_reason_codes'] == ['NO_STREAM'] and rep['mean_speed_mps'] is None
               for rep in required['value']['reps'])
    assert 'COMPONENT_NOT_ASSESSABLE' in required['reason_codes']
    for modality in ('hr', 'effort'):
        optional = [replace(step, target_modality=modality, target_low=None,
                            target_high=None) if step.type == 'work' else step for step in plan]
        out = execution_outcome(optional, fit, laps, None)
        assert out['status'] == 'available'
        assert out['quality_status'] is None
        assert all(rep['completion_ratio'] == 1 for rep in out['value']['reps'])
        if modality == 'hr':
            assert all('HR_TARGET_NOT_SCORED' in rep['flags'] for rep in out['value']['reps'])
    absent = execution_outcome(plan, fit, laps, replace(stream, speed_mps=[None] * len(stream.t_s)))
    assert absent['status'] == 'partial'
    assert absent['value']['reps'][0]['speed_coverage'] == 0
    assert absent['value']['reps'][0]['speed_reason_codes'] == ['NO_SPEED_SAMPLES']
    speed = stream.speed_mps.copy()
    speed[700:705] = [25] * 5
    out = execution_outcome(plan, fit, laps, replace(stream, speed_mps=speed))
    assert out['value']['reps'][0]['speed_coverage'] == .983
    assert out['value']['reps'][0]['speed_status'] == 'available'


def test_hr_and_timer_helpers() -> None:
    assert weighted_median([(150, 1), (170, 9)]) == 170
    assert weighted_median([(150, 5), (170, 5)]) == 160
    assert weighted_median([(150, 4.999), (170, 5.001)]) == 170
    assert weighted_median([(150, 5.001), (170, 4.999)]) == 150
    assert after_timer_seconds([(0, 30), (90, 270)], 60) == [(120, 270)]
    assert clip([(0, 10), (20, 30)], 5, 25) == [(5, 10), (20, 25)]
    plan, fit, laps, stream = example()
    short_plan = [replace(step, duration_value=60, target_modality='effort',
                          target_low=None, target_high=None) if step.type == 'work' else step for step in plan]
    short_laps = [replace(lap, timer_s=60) if lap.lap_index in (1, 3, 5, 7) else lap for lap in laps]
    out = execution_outcome(short_plan, fit, short_laps, None)
    assert out['status'] == 'available'
    assert all(rep['hr_median_bpm'] is None and 'HR_NOT_REPORTED_SHORT_STEP' in rep['flags']
               for rep in out['value']['reps'])


def test_paused_timer_hr_lag_and_lap_bounds() -> None:
    plan = [PlanStep(1, 'work', 'time', 210, '0', target_modality='speed',
                     target_low=3.8, target_high=4.2)]
    fit = [FitStep(0, 'time', 'active')]
    laps = [LapIn(0, 0, 210, 270, 840, 0)]
    hr = [100.0] * 271
    hr[120:] = [170.0] * 151
    stream = ExecStream(list(range(271)), hr, [4.0] * 271, [(0, 30), (90, 270)])
    out = execution_outcome(plan, fit, laps, stream)
    rep = out['value']['reps'][0]
    assert out['status'] == 'available'
    assert rep['speed_coverage'] == 1
    assert rep['target_valid_s'] == 210
    assert rep['hr_median_bpm'] == 170
    assert rep['completion_ratio'] == 1
    # An unknown elapsed duration may end at the next chronological lap only.
    next_lap = LapIn(1, 270, 10, 10, 40, 1)
    next_fit = [*fit, FitStep(1, 'time', 'recovery')]
    inferred = execution_outcome(plan, next_fit, [replace(laps[0], elapsed_s=None), next_lap], stream)
    assert inferred['value']['reps'][0]['speed_status'] == 'available'
    unknown_end = execution_outcome(plan, fit, [replace(laps[0], elapsed_s=None)], stream)
    assert unknown_end['value']['reps'][0]['speed_reason_codes'] == ['LAP_END_UNKNOWN']
    assert unknown_end['status'] == 'partial'
    with pytest.raises(ValueError, match='invalid_timer'):
        execution_outcome(plan, fit, laps, replace(stream, timer_on=[(30, 20), (90, 270)]))


def test_mapping_mismatch_and_repeats() -> None:
    plan, fit, laps, stream = example()
    for altered in (
        [replace(step, repeat_count=5) if step.message_index == 3 else step for step in fit],
        [replace(step, duration_type='distance') if step.message_index == 1 else step for step in fit],
    ):
        out = execution_outcome(plan, altered, laps, stream)
        assert out['value'] is None
        assert out['reason_codes'] == ['WATCH_WORKOUT_MISMATCH']
    out = execution_outcome(plan, fit, [laps[0], laps[2], laps[1], *laps[3:]], stream)
    # Sorting by lap_index restores row order, so index identity remains deterministic.
    assert out['status'] == 'available'
    mismatched = laps.copy()
    mismatched[3] = replace(laps[3], wkt_step_index=2)
    assert execution_outcome(plan, fit, mismatched, stream)['reason_codes'] == ['LAP_STEP_ORDER_MISMATCH']
    unindexed_interior = laps.copy()
    unindexed_interior[3] = replace(laps[3], wkt_step_index=None)
    assert execution_outcome(plan, fit, unindexed_interior, stream)['reason_codes'] == ['LAP_STEP_ORDER_MISMATCH']
    unsupported = [FitStep(0, 'repeat_until_time', repeat_from=0, repeat_count=2)]
    assert execution_outcome(plan, unsupported, laps, stream)['reason_codes'] == ['UNSUPPORTED_REPEAT']
    forward = [FitStep(0, 'repeat_until_steps_cmplt', repeat_from=1, repeat_count=2),
               FitStep(1, 'time', 'active', 300)]
    assert execution_outcome(plan, forward, laps, stream)['reason_codes'] == ['MALFORMED_REPEAT']
    assert execution_outcome([], fit, laps, stream)['reason_codes'] == ['NO_WORK_STEPS']
    nested = [
        FitStep(0, 'time', 'active'), FitStep(1, 'time', 'recovery'),
        FitStep(2, 'repeat_until_steps_cmplt', repeat_from=0, repeat_count=2),
        FitStep(3, 'time', 'rest'),
        FitStep(4, 'repeat_until_steps_cmplt', repeat_from=0, repeat_count=2),
    ]
    assert [step.message_index for step in expand_fit(nested)] == [0, 1, 0, 1, 3, 0, 1, 0, 1, 3]


def test_distance_targets_zero_speed_and_missing_original_endpoint() -> None:
    plan, fit, laps, stream = example()
    distance_plan = [PlanStep(i + 1, 'work', 'distance', 1000, str(i)) for i in range(3)]
    distance_fit = [FitStep(i, 'distance', 'active') for i in range(3)]
    distance_laps = [LapIn(i, i * 300, 300, 300, distance, i)
                     for i, distance in enumerate((1000, 990, 1010))]
    out = execution_outcome(distance_plan, distance_fit, distance_laps, None)
    assert out['value']['n_completed'] == 2
    assert out['value']['step_completion_ratio'] == .667
    assert out['value']['planned_work_m'] == 3000
    assert out['value']['planned_work_s'] is None
    zero_stream = replace(stream, speed_mps=[0.0] * len(stream.t_s))
    out = execution_outcome(plan, fit, laps, zero_stream)
    assert out['value']['cv_speed'] is None
    assert out['value']['last_first_change_pct'] is None
    assert 'ZERO_SPEED_DENOMINATOR' in out['quality_flags']
    missing_first = laps.copy()
    missing_first[1] = replace(laps[1], timer_s=100)
    out = execution_outcome(plan, fit, missing_first, stream)
    assert out['value']['last_first_change_pct'] is None
    assert out['value']['cv_speed'] is not None


def test_nonfinite_lap_values_are_unknown_and_subtotals_round_once() -> None:
    plan = [PlanStep(i + 1, 'work', 'time', 0.01, str(i)) for i in range(3)]
    fit = [FitStep(i, 'time', 'active') for i in range(3)]
    laps = [LapIn(i, i, 0.04, 1, 0.04, i) for i in range(3)]
    outcome = execution_outcome(plan, fit, laps, None)
    assert outcome['value']['completed_work_s'] == 0.1
    assert outcome['value']['completed_work_m'] == 0.1
    bad = laps.copy()
    bad[0] = replace(laps[0], timer_s=float('nan'), distance_m=float('inf'))
    outcome = execution_outcome(plan, fit, bad, None)
    assert outcome['status'] == 'partial'
    assert outcome['value']['reps'][0]['actual_timer_s'] is None
    assert outcome['value']['reps'][0]['actual_distance_m'] is None
    assert outcome['value']['completed_work_s'] == 0.1
    assert 'PARTIAL_WORK_TIMER' in outcome['quality_flags']
    with pytest.raises(ValueError, match='invalid_structure'):
        execution_outcome([replace(plan[0], duration_value=0)], fit, laps, None)


@pytest.mark.parametrize('flag', ['TIMER_EVENTS_MISSING', 'TIMER_EVENTS_AMBIGUOUS', 'TIMER_MISMATCH'])
def test_timer_flags_suppress_trace_but_preserve_lap_completion(flag: str) -> None:
    plan, fit, laps, stream = example()
    out = execution_outcome(plan, fit, laps, replace(stream, quality_flags=(flag,)))
    assert out['status'] == 'partial'
    assert out['value']['n_completed'] == 4
    assert all(rep['speed_reason_codes'] == [flag] for rep in out['value']['reps'])
    optional = [replace(step, target_modality='effort', target_low=None, target_high=None)
                if step.type == 'work' else step for step in plan]
    assert execution_outcome(optional, fit, laps, replace(stream, quality_flags=(flag,)))['status'] == 'available'
