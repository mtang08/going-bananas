import pytest

from app.metrics.aerobic import AeroStream, Sample, aerobic_outcome, analysis_spans, speed_cv_pct


def stream(n, hr, speed, alt=None, timer_on=None, flags=()):
    t = list(range(n + 1))
    return AeroStream(t, [hr(i) for i in t], [speed(i) for i in t],
                      [alt(i) if alt else None for i in t], timer_on or [(0, n)], tuple(flags))


def test_steady_run_reports_ef_and_drift():
    result = aerobic_outcome(stream(3600, lambda i: 140 if i < 2100 else 147, lambda i: 2.8))

    assert result['status'] == 'available'
    assert result['quality_status'] == 'good'
    assert result['reason_codes'] == []
    assert result['quality_flags'] == []
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
    assert result['quality_flags'] == ['STOPS_EXCLUDED']
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

    assert result['quality_flags'] == ['PAUSES_TRIMMED']
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

    assert result['quality_flags'] == ['PAUSES_TRIMMED']
    assert result['value']['analysis_s'] == 1240.0
    assert result['value']['pauses_trimmed'] == 1
