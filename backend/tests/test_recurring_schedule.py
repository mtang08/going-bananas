from datetime import date, datetime
from types import SimpleNamespace

from app.domain.cycle import recurring_sessions


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
