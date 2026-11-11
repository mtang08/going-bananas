from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from app.services.run_classification import RunObservation, classify_history


def run(day: date, *, id: str | None = None, distance: float | None = 5000,
        elapsed: float | None = 1850, moving: float | None = 1800,
        hr: float | None = 140, manual: str | None = None,
        source: str | None = None) -> RunObservation:
    return RunObservation(
        id=id or day.isoformat(), local_date=day,
        start_at=datetime.combine(day, datetime.min.time(), UTC), sport='running',
        distance_m=distance, elapsed_s=elapsed, moving_s=moving,
        avg_hr_bpm=hr, manual_label=manual, source_label=source,
    )


def baseline(target: date) -> list[RunObservation]:
    return [run(target - timedelta(days=7 * weeks)) for weeks in range(1, 9)]


def test_unknown_with_insufficient_history_and_missing_heart_rate():
    target = run(date(2026, 11, 14), distance=9000, elapsed=3200, hr=None)
    result = classify_history(baseline(target.local_date)[:3] + [target])[target.id]
    assert result['effective_label'] == 'unknown'
    assert result['confidence'] == 'insufficient'
    assert result['metrics']['prior_runs'] == 3
    assert any('Fewer than six' in reason for reason in result['reasons'])


def test_weekend_long_uses_relative_time_distance_and_keeps_effort_separate():
    target = run(date(2026, 11, 14), distance=9000, elapsed=3200, moving=3000, hr=160)
    result = classify_history(baseline(target.local_date) + [target])[target.id]
    assert result['effective_label'] == 'long'
    assert result['suggested_label'] == 'long'
    assert result['label_source'] == 'heuristic'
    assert result['metrics']['effort_signal'] == 'higher_average_hr'
    assert result['metrics']['relative_duration'] > 1.25


def test_weekday_cannot_receive_heuristic_long_label():
    target = run(date(2026, 11, 17), distance=9000, elapsed=3200, moving=3000, hr=None)
    result = classify_history(baseline(target.local_date) + [target])[target.id]
    assert result['effective_label'] == 'unknown'
    assert result['suggested_label'] is None


def test_quality_needs_high_average_hr_and_faster_moving_pace_together():
    target = run(date(2026, 11, 17), moving=1600, elapsed=1650, hr=155)
    history = baseline(target.local_date)
    result = classify_history(history + [target])[target.id]
    assert result['effective_label'] == 'quality'
    assert result['confidence'] == 'low'
    high_hr_only = replace(target, id='high-hr-only', moving_s=1900)
    assert classify_history(history + [high_hr_only])[high_hr_only.id]['effective_label'] == 'unknown'
    no_hr = replace(target, id='no-hr', avg_hr_bpm=None)
    assert classify_history(history + [no_hr])[no_hr.id]['effective_label'] == 'unknown'


def test_easy_requires_lower_average_hr_without_fast_pace():
    target = run(date(2026, 11, 17), moving=1870, elapsed=1920, hr=130)
    result = classify_history(baseline(target.local_date) + [target])[target.id]
    assert result['effective_label'] == 'easy'
    assert result['confidence'] == 'low'


def test_manual_then_source_precedence_preserves_explicit_weekday_long():
    target = run(date(2026, 11, 17), moving=1600, elapsed=1650, hr=155,
                 source='quality', manual='long')
    history = baseline(target.local_date)
    result = classify_history(history + [target])[target.id]
    assert (result['effective_label'], result['label_source'], result['suggested_label']) == ('long', 'manual', None)
    assert any('weekend restriction applies to suggestions' in reason for reason in result['reasons'])
    result = classify_history(history + [replace(target, manual_label=None)])[target.id]
    assert (result['effective_label'], result['label_source']) == ('quality', 'source')


def test_future_runs_and_unresolved_rows_never_change_prior_suggestion():
    target = run(date(2026, 11, 17), moving=1600, elapsed=1650, hr=155)
    history = baseline(target.local_date)
    before = classify_history(history + [target])[target.id]
    future = run(date(2026, 11, 24), id='future', hr=200, moving=1200)
    excluded = replace(run(date(2026, 11, 16), id='excluded'), excluded=True)
    unresolved = replace(run(date(2026, 11, 15), id='unresolved'), resolution_state='revision_conflict')
    after = classify_history(history + [target, future, excluded, unresolved])[target.id]
    assert before == after


def test_invalid_input_is_bounded_and_identified():
    target = run(date(2026, 11, 17))
    with pytest.raises(ValueError, match='duplicate_run_id'):
        classify_history([target, target])
    with pytest.raises(ValueError, match='invalid_long_run_weekdays'):
        classify_history([target], long_run_weekdays=(7,))
