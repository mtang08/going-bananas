import math

import pytest

from app.metrics.aerobic import AeroStream, Sample, aerobic_outcome, analysis_spans, run_class, speed_cv_pct


def stream(n, hr, speed, alt=None, timer_on=None, flags=()):
    t = list(range(n + 1))
    return AeroStream(t, [hr(i) for i in t], [speed(i) for i in t],
                      [alt(i) if alt else None for i in t], timer_on or [(0, n)], tuple(flags))


def test_steady_run_reports_ef_and_drift():
    result = aerobic_outcome(stream(3600, lambda i: 140 if i < 2100 else 147, lambda i: 2.8))

    assert result['status'] == 'available'
    assert result['quality_status'] == 'good'
    assert result['reason_codes'] == []
    assert result['quality_flags'] == ['ELEVATION_UNKNOWN']
    value = result['value']
    assert value['analysis_s'] == 3000.0
    assert value['coverage'] == 1.0
    assert value['mean_hr_bpm'] == 143.5
    assert value['ef_m_per_beat'] == 1.171
    assert value['speed_cv_pct'] == 0.0
    decoupling = value['decoupling']
    assert decoupling['status'] == 'available'
    assert decoupling['pct'] == 4.76
    assert decoupling['first_ef_m_per_beat'] == 1.2
    assert decoupling['second_ef_m_per_beat'] == 1.143
    assert decoupling['first_mean_hr_bpm'] == 140.0
    assert decoupling['second_mean_hr_bpm'] == 147.0
    assert decoupling['half_s'] == 1500.0


def test_duration_gates():
    too_short = aerobic_outcome(stream(1700, lambda i: 140, lambda i: 2.8))
    assert too_short['reason_codes'] == ['TOO_SHORT']
    assert too_short['value'] is None

    value = aerobic_outcome(stream(1800, lambda i: 140, lambda i: 2.8))['value']
    assert value['ef_m_per_beat'] == 1.2
    assert value['decoupling']['reason_codes'] == ['DECOUPLING_TOO_SHORT']
    assert value['decoupling']['pct'] is None
    assert value['decoupling']['half_s'] == 600.0

    value = aerobic_outcome(stream(2900, lambda i: 140, lambda i: 2.8))['value']
    assert value['decoupling']['reason_codes'] == ['DECOUPLING_TOO_SHORT']


def test_stops():
    result = aerobic_outcome(stream(3600, lambda i: 140, lambda i: 0.5 if 1000 <= i < 1200 else 2.8))
    assert result['quality_flags'] == ['ELEVATION_UNKNOWN', 'STOPS_EXCLUDED']
    value = result['value']
    assert value['stopped_s'] == 200.0
    assert value['moving_s'] == 2800.0
    assert value['ef_m_per_beat'] == 1.2
    assert value['decoupling']['pct'] == 0.0

    too_many = aerobic_outcome(stream(3600, lambda i: 140, lambda i: 0.5 if 1000 <= i < 1400 else 2.8))
    assert too_many['reason_codes'] == ['TOO_MANY_STOPS']


def test_pause_trims_first_minute_after_resume():
    timer_on = [(0, 1500), (1700, 3800)]
    assert analysis_spans(timer_on, 600, 60) == [(600, 1500), (1760, 3800)]

    result = aerobic_outcome(stream(3800, lambda i: 140, lambda i: 2.8, timer_on=timer_on))

    assert result['quality_flags'] == ['ELEVATION_UNKNOWN', 'PAUSES_TRIMMED']
    assert result['value']['analysis_s'] == 2940.0
    assert result['value']['pauses_trimmed'] == 1
    assert result['value']['decoupling']['half_s'] == 1470.0


def test_coverage_gates():
    too_low = aerobic_outcome(stream(3600, lambda i: None if 600 <= i < 1800 else 140, lambda i: 2.8))
    assert too_low['reason_codes'] == ['LOW_COVERAGE']
    assert too_low['status'] == 'not_assessable'

    limited = aerobic_outcome(stream(3600, lambda i: None if 600 <= i < 1200 else 140, lambda i: 2.8))
    assert limited['status'] == 'partial'
    assert limited['quality_status'] == 'limited'
    assert limited['reason_codes'] == ['LOW_COVERAGE']
    assert limited['value']['coverage'] == 0.8
    assert limited['value']['decoupling']['reason_codes'] == ['HALF_LOW_COVERAGE']
    assert limited['value']['decoupling']['pct'] is None


def test_unsteady_pace_rejected():
    result = aerobic_outcome(stream(3600, lambda i: 150, lambda i: 2.5 if (i // 120) % 2 == 0 else 4.0))

    assert result['reason_codes'] == ['PACE_NOT_STEADY']


def test_signal_gates():
    assert aerobic_outcome(None)['reason_codes'] == ['NO_STREAM']
    mismatched = stream(3600, lambda i: 140, lambda i: 2.8, flags=('TIMER_MISMATCH',))
    assert aerobic_outcome(mismatched)['reason_codes'] == ['TIMER_MISMATCH']
    assert aerobic_outcome(stream(3600, lambda i: None, lambda i: 2.8))['reason_codes'] == ['HR_NOT_RECORDED']
    assert aerobic_outcome(stream(3600, lambda i: 140, lambda i: None))['reason_codes'] == ['SPEED_NOT_RECORDED']


def test_sample_crossing_midpoint_contributes_to_both_halves():
    result = aerobic_outcome(stream(3601, lambda i: 140 if i < 2100 else 220, lambda i: 2.8))
    decoupling = result['value']['decoupling']

    assert decoupling['status'] == 'available'
    assert decoupling['half_s'] == 1500.5
    assert decoupling['first_mean_hr_bpm'] == 140.0
    assert decoupling['second_mean_hr_bpm'] == 220.0


def test_paired_time_crossing_bin_boundary_fills_next_bin():
    paired = [
        Sample(0, 55, True, 2.0, 140),
        Sample(1, 10, True, 4.0, 140),
        Sample(2, 55, True, 6.0, 140),
    ]

    assert speed_cv_pct(paired, 60) == pytest.approx(64.81812160876685)


def test_pause_is_trimmed_when_warmup_ends_at_pause():
    timer_on = [(0, 600), (1000, 2300)]
    assert analysis_spans(timer_on, 600, 60) == [(1060, 2300)]

    result = aerobic_outcome(stream(2300, lambda i: 140, lambda i: 2.8, timer_on=timer_on))

    assert result['quality_flags'] == ['ELEVATION_UNKNOWN', 'PAUSES_TRIMMED']
    assert result['value']['analysis_s'] == 1240.0
    assert result['value']['pauses_trimmed'] == 1


def elevation_stream(alt):
    return stream(3600, lambda i: 140 if i < 2100 else 147, lambda i: 2.8, alt=alt)


def hilly_altitude(i):
    return 50 + 20 * math.sin(2 * math.pi * i / 600)


def test_out_and_back_blocks_only_decoupling_pct():
    result = aerobic_outcome(elevation_stream(lambda i: 30 * max(0, 1 - abs(i - 2100) / 1500)))

    assert 'HILLY_ROUTE' not in result['quality_flags']
    value = result['value']
    assert value['ef_m_per_beat'] == 1.171
    assert value['elevation']['status'] == 'available'
    assert value['elevation']['gain_m'] == pytest.approx(29.8, abs=0.2)
    assert value['elevation']['half_grade_diff_pct'] == pytest.approx(-1.39, abs=0.02)
    decoupling = value['decoupling']
    assert decoupling['status'] == 'not_assessable'
    assert decoupling['reason_codes'] == ['HALF_GRADE_DIFFERS']
    assert decoupling['pct'] is None
    assert decoupling['first_ef_m_per_beat'] == 1.2
    assert decoupling['second_ef_m_per_beat'] == 1.143


def test_hilly_route_flagged():
    result = aerobic_outcome(elevation_stream(hilly_altitude))

    assert 'HILLY_ROUTE' in result['quality_flags']
    value = result['value']
    assert value['elevation']['gain_m_per_km'] == pytest.approx(22.97, abs=0.1)
    assert value['elevation']['half_grade_diff_pct'] == pytest.approx(-0.29, abs=0.02)
    assert value['decoupling']['pct'] == 4.76


def test_uniform_climb_does_not_block():
    result = aerobic_outcome(elevation_stream(lambda i: 12 * max(0, i - 600) / 3000))
    value = result['value']

    assert value['elevation']['half_grade_diff_pct'] == 0.0
    assert value['elevation']['gain_m_per_km'] < 15
    assert value['decoupling']['status'] == 'available'


def test_flat_altitude():
    result = aerobic_outcome(elevation_stream(lambda i: 50.0))

    assert result['quality_flags'] == []
    assert result['value']['elevation']['gain_m'] == 0.0
    assert result['value']['elevation']['gain_m_per_km'] == 0.0


def test_treadmill_flags_and_skips_elevation():
    result = aerobic_outcome(elevation_stream(hilly_altitude), treadmill=True)

    assert result['quality_flags'] == ['TREADMILL']
    assert result['value']['elevation']['status'] == 'not_applicable'
    assert result['value']['ef_m_per_beat'] == 1.171


def test_elevation_cadence_does_not_shift_with_stops_or_record_spacing():
    times = [*range(0, 3600, 7), 3600]
    sparse = AeroStream(
        times, [140] * len(times), [0.5 if 994 <= i < 1190 else 2.8 for i in times],
        [0.02 * i for i in times], [(0, 3600)],
    )
    result = aerobic_outcome(sparse)

    assert result['value']['stopped_s'] == 196.0
    assert result['value']['elevation']['gain_m'] == 59.5
    assert result['value']['elevation']['gain_m_per_km'] == 7.58


def test_hilly_gate_compares_before_rounding():
    slope = 15.004 * 8.4 / 2970
    result = aerobic_outcome(elevation_stream(lambda i: i * slope))

    assert result['value']['elevation']['gain_m_per_km'] == 15.0
    assert result['quality_flags'] == ['HILLY_ROUTE']


def test_half_grade_gate_compares_before_rounding():
    slope = 1.004 * 42 / (1470 - 120 / 31)
    result = aerobic_outcome(elevation_stream(lambda i: max(0, i - 2100) * slope))

    assert result['value']['elevation']['half_grade_diff_pct'] == 1.0
    assert result['value']['decoupling']['reason_codes'] == ['HALF_GRADE_DIFFERS']
    assert result['value']['decoupling']['pct'] is None


def test_run_class():
    easy = {'recipe_id': 'REC001', 'intent': 'Easy run', 'structure': None}
    long = {'recipe_id': 'REC002', 'intent': 'Long run', 'structure': None}
    warmup = {'type': 'warmup', 'duration_type': 'time', 'duration_value': 600}
    cooldown = {'type': 'cooldown', 'duration_type': 'time', 'duration_value': 600}
    four_by_five = [warmup, {'type': 'repeat', 'count': 4, 'steps': [
        {'type': 'work', 'duration_type': 'time', 'duration_value': 300,
         'target': {'modality': 'speed', 'low': 3.4, 'high': 3.8}},
        {'type': 'recovery', 'duration_type': 'time', 'duration_value': 120},
    ]}, cooldown]
    steady = {'recipe_id': None, 'intent': 'Steady 40', 'structure': None}
    quality = {'recipe_id': 'REC004', 'intent': 'Tempo', 'structure': [
        warmup, {'type': 'work', 'duration_type': 'time', 'duration_value': 1200}, cooldown,
    ]}

    assert run_class(easy, 0, None) == ('easy', None)
    assert run_class(long, 0, None) == ('long', None)
    assert run_class({'recipe_id': 'REC003', 'structure': four_by_five}, 0, None) == (
        'structured', 'STRUCTURED_SESSION',
    )
    assert run_class(quality, 0, None) == ('quality', 'NOT_EASY_OR_LONG')
    assert run_class(steady, 0, None) == ('unplanned', None)
    assert run_class(steady, 0, 'long') == ('long', None)
    assert run_class(None, 0, 'quality') == ('quality', 'NOT_EASY_OR_LONG')
    assert run_class(None, 4, None) == ('structured', 'STRUCTURED_SESSION')
    assert run_class(None, 1, None) == ('unplanned', None)
