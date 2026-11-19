from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.domain.analytics import pace_s_per_km, utc_date_bounds
from app.domain.associations import preceding_sessions
from app.domain.cycle import opportunities


def test_pace_requires_positive_distance_and_time():
    assert pace_s_per_km(1609.344,600) == 372.82271534240033
    assert pace_s_per_km(0,600) is None


def test_dst_window_and_cycle():
    spring = utc_date_bounds(date(2026,3,8),date(2026,3,8),'America/New_York')
    fall = utc_date_bounds(date(2026,11,1),date(2026,11,1),'America/New_York')
    assert (spring[1]-spring[0]).total_seconds() == 23*3600
    assert (fall[1]-fall[0]).total_seconds() == 25*3600
    days = opportunities(date(2026,11,2),date(2026,11,16),date(2026,11,2))
    assert [d['date'] for d in days] == ['2026-11-02','2026-11-04','2026-11-06','2026-11-08',
                                        '2026-11-10','2026-11-12','2026-11-14','2026-11-16']


def test_association_uses_actual_elapsed_hours():
    zone = ZoneInfo('America/New_York')
    start = datetime(2026,11,2,8,0,tzinfo=zone)
    candidates = [{'id':'run','start_at':start,'elapsed_s':3600,'sport':'running'}]
    result = preceding_sessions(datetime(2026,11,3,9,0,tzinfo=zone),candidates,'America/New_York')
    assert result[0]['elapsed_hours'] == 24
    assert result[0]['day_label'] == 'next_day'
    assert preceding_sessions(datetime(2026,11,4,1,0,tzinfo=zone),candidates,'America/New_York')[0]['elapsed_hours'] == 40
