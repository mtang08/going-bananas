from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.services.calendar import bootstrap_plan


def _runs(plan):
    return [row for row in plan if row['kind'] == 'run']


def test_empty_history_bootstrap_clipped_weeks_and_recurring_strength():
    start = date(2026, 11, 16)
    occurrences = [{'date': day.isoformat(), 'kind': 'strength', 'optional': False}
                   for day in (date(2026, 11, 16), date(2026, 11, 20),
                               date(2026, 11, 23), date(2026, 11, 27))]
    plan = bootstrap_plan(date(2026, 11, 2), start, start, [], occurrences)
    runs = _runs(plan)
    assert [row['local_date'].day for row in runs] == [16, 18, 20, 22, 24, 26, 28]
    assert [row['recipe_id'] for row in runs] == [None, 'REC001', 'REC001', 'REC002',
                                                  None, 'REC001', 'REC002']
    assert [row['planned_duration_s'] for row in runs] == [1800, 1800, 1800, 2400,
                                                           1800, 1800, 2400]
    assert all(row['slot'] == 0 for row in runs)
    assert [row['local_date'].day for row in plan if row['kind'] == 'strength'] == [16, 20, 23, 27]
    assert all(row['slot'] == 1 for row in plan if row['kind'] == 'strength')


def test_history_classifies_long_and_rounds_easy():
    today = date(2026, 11, 16)
    timers = [1800, 1900, 2000, 2100, 3600]
    history = [{'local_date': today - timedelta(days=5-index), 'timer_s': timer,
                'resolution_state': 'resolved'} for index, timer in enumerate(timers)]
    plan = _runs(bootstrap_plan(date(2026, 11, 2), today, today, history, []))
    assert [row['planned_duration_s'] for row in plan] == [2100, 2100, 2100, 3600,
                                                           2100, 2100, 3600]
    unknown = history + [{'local_date': today - timedelta(days=1), 'timer_s': float('nan')},
                         {'local_date': today - timedelta(days=1), 'timer_s': 9000,
                          'resolution_state': 'pending'}]
    assert _runs(bootstrap_plan(date(2026, 11, 2), today, today, unknown, [])) == plan


def test_mobility_optional_flag_is_preserved():
    start = date(2026, 11, 16)
    plan = bootstrap_plan(start, start, start, [], [
        {'date': '2026-11-18', 'kind': 'mobility', 'optional': False},
        {'date': '2026-11-22', 'kind': 'mobility', 'optional': True}])
    mobility = [item for item in plan if item['kind'] == 'mobility']
    assert [item['slot'] for item in mobility] == [2, 2]
    assert [item['legacy_payload'] for item in mobility] == [None, {'optional': True}]


def test_prior_28_calendar_days_can_classify_run_inside_recent_window():
    today = date(2026, 11, 16)
    history = [{'local_date': today - timedelta(days=35-index), 'timer_s': 1800}
               for index in range(4)]
    history.append({'local_date': today - timedelta(days=27), 'timer_s': 3600})
    plan = _runs(bootstrap_plan(date(2026, 11, 2), today, today, history, []))
    assert plan[3]['planned_duration_s'] == 3600
    assert plan[1]['planned_duration_s'] == 1800


def test_same_day_earlier_runs_are_prior_observations():
    today = date(2026, 11, 16)
    history = [{'local_date': today - timedelta(days=1), 'timer_s': timer,
                'start_at': datetime(2026, 11, 15, hour, tzinfo=UTC)}
               for hour, timer in enumerate([1800, 1800, 1800, 1800, 3600], start=7)]
    plan = _runs(bootstrap_plan(date(2026, 11, 2), today, today, history, []))
    assert plan[3]['planned_duration_s'] == 3600
