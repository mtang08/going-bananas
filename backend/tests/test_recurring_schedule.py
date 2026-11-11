from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from app.domain.cycle import recurring_sessions
from app.services.coaching import daily, weekly


def profile(**changes):
    values = dict(strength_days_confirmed=True, strength_schedule_mode='alternating',
                  strength_week_a_start=date(2026, 11, 9), strength_week_a_days=[0, 4],
                  strength_week_b_days=[1, 5], mobility_week_a_days=[2],
                  mobility_week_b_days=[3], mobility_optional_days=[6],
                  scheduled_strength_days=[])
    values.update(changes)
    return SimpleNamespace(**values)


def test_two_week_rotation_crosses_year_and_dst_without_drifting():
    november = recurring_sessions(date(2026, 11, 9), date(2026, 11, 22), profile())
    assert [(s['date'], s['kind'], s['optional']) for s in november] == [
        ('2026-11-09', 'strength', False), ('2026-11-11', 'mobility', False),
        ('2026-11-13', 'strength', False), ('2026-11-15', 'mobility', True),
        ('2026-11-17', 'strength', False), ('2026-11-19', 'mobility', False),
        ('2026-11-21', 'strength', False), ('2026-11-22', 'mobility', True),
    ]
    year = recurring_sessions(date(2026, 12, 28), date(2027, 1, 10), profile())
    assert sum(s['kind'] == 'strength' for s in year) == 4
    assert year[0]['date'] == '2026-12-29'  # Week B relative to Nov 9.
    spring = recurring_sessions(date(2027, 3, 8), date(2027, 3, 21), profile())
    assert sum(s['kind'] == 'strength' for s in spring) == 4
    assert sum(s['kind'] == 'mobility' and not s['optional'] for s in spring) == 2


def test_weekly_legacy_and_accepted_range_override():
    weekly_profile = profile(strength_schedule_mode='weekly', scheduled_strength_days=[0, 4])
    slots = recurring_sessions(date(2026, 11, 9), date(2026, 11, 22), weekly_profile)
    assert [s['date'] for s in slots] == ['2026-11-09', '2026-11-13', '2026-11-16', '2026-11-20']
    covered = recurring_sessions(date(2026, 11, 9), date(2026, 11, 22), profile(),
                                 [(date(2026, 11, 12), date(2026, 11, 19))])
    assert all(not (date(2026, 11, 12) <= date.fromisoformat(s['date']) <= date(2026, 11, 19)) for s in covered)
    configured = profile(effective_at=datetime.fromisoformat('2026-11-11T09:00:00-05:00'),
                         timezone='America/New_York')
    future_only = recurring_sessions(date(2026, 11, 9), date(2026, 11, 22), configured)
    assert all(s['date'] >= '2026-11-11' for s in future_only)


def test_daily_and_weekly_use_confirmed_slots_without_accepted_plan():
    day = date(2026, 11, 11)
    slots = recurring_sessions(day, day + timedelta(days=13), profile())
    context = {
        'generated_at': None, 'timezone': 'America/New_York',
        'profile': {'anchor_confirmed': False, 'cycle_anchor': None},
        'recurring_sessions': slots, 'next_14_days_plan': [], 'recent_14_days_plan': [],
        'recent_checkins': [], 'recent_activities': [], 'recovery': {'series': {'hrv': []}},
        'last_14_days': {'rolling_7': {}, 'rolling_14': {}},
    }
    result = daily(context, day, {}, today=day)
    assert result['planned_session']['kind'] == 'mobility'
    assert result['planned_sessions'][0]['source'] == 'recurring_schedule'
    assert not any('No confirmed recurring' in reason for reason in result['missing_or_stale_inputs'])
    review = weekly(context, day)
    next_slots = review['next_cycle_proposal']['dated_sessions']
    assert sum(s['kind'] == 'strength' for s in next_slots) == 4
    assert sum(s['kind'] == 'mobility' and s['optional'] for s in next_slots) == 2
    assert all(s['source'] == 'recurring_schedule' for s in next_slots)


def test_same_day_run_and_strength_remain_distinct_commitments():
    day = date(2026, 11, 9)
    context = {
        'generated_at': None, 'profile': {'anchor_confirmed': True, 'cycle_anchor': day},
        'recurring_sessions': recurring_sessions(day, day, profile()),
        'next_14_days_plan': [], 'recent_checkins': [], 'recent_activities': [],
        'recovery': {'series': {'hrv': []}},
    }
    result = daily(context, day, {}, today=day)
    assert [s['kind'] for s in result['planned_sessions']] == ['run', 'strength']
    assert result['additional_session_guidance'][0]['kind'] == 'strength'


def test_conditional_run_intents_respect_weekend_and_strength_placement():
    start = date(2026, 11, 9)
    context = {
        'generated_at': None, 'profile': {
            'anchor_confirmed': True, 'cycle_anchor': start, 'strength_schedule_mode': 'alternating',
            'strength_week_a_start': start, 'strength_week_a_days': [0, 4],
            'strength_week_b_days': [1, 5], 'preferences': {'long_run_weekdays': [5, 6]},
        },
        'recurring_sessions': recurring_sessions(start, start+timedelta(days=13), profile()),
        'next_14_days_plan': [], 'recent_14_days_plan': [], 'recent_checkins': [],
        'recent_activities': [], 'recovery': {'series': {'hrv': []}},
        'last_14_days': {'rolling_7': {}, 'rolling_14': {}},
    }
    dated = weekly(context, start)['next_cycle_proposal']['dated_sessions']
    run_slots = [s for s in dated if s['kind'] == 'run']
    assert [(s['date'], s['intent']) for s in run_slots if s['intent'] == 'long'] == [
        ('2026-11-15', 'long'), ('2026-11-21', 'long')]
    assert [(s['date'], s['intent']) for s in run_slots if s['intent'] == 'quality'] == [
        ('2026-11-11', 'quality'), ('2026-11-19', 'quality')]
    assert all(s['conditional'] for s in run_slots if s['intent'] in {'quality', 'long'})
    today = daily(context, date(2026, 11, 11), {}, today=date(2026, 11, 11))
    assert today['planned_session']['intent'] == 'quality'
    assert today['proposed_session']['mode'] == 'easy_run'
    for run_day, expected in [(date(2026, 11, 11), 'quality'), (date(2026, 11, 15), 'long')]:
        current = dict(context)
        current['recent_checkins'] = [{
            'observed_at': datetime.combine(run_day, datetime.min.time(), UTC).replace(hour=12),
            'symptoms': 'none', 'change': 'same', 'gait': 'normal', 'feeling': 'usual',
        }]
        current['recovery'] = {'series': {'hrv': [{'date': run_day, 'value': 70}]}}
        ready = daily(current, run_day,
                      {'illness': 'none', 'lower_body_soreness': 'none', 'clinician_restriction': 'none'},
                      today=run_day)
        assert ready['decision'] == 'proceed'
        assert ready['planned_session']['intent'] == expected
        assert expected in ready['proposed_session']['purpose']
