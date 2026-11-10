from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.domain.analytics import ActivityFact, pace_s_per_km, summary, trailing_mean, utc_date_bounds
from app.domain.associations import preceding_sessions
from app.domain.cycle import opportunities, validate_acceptance


def activity(day, meters, sport='running', elapsed=700, moving=600, label=None):
    return ActivityFact(str(day), day, datetime.combine(day, datetime.min.time(), UTC), sport,
                        meters, elapsed, moving, label)


def test_volume_windows_pace_and_strength_is_separate():
    rows = [activity(date(2026,11,2),1609.344), activity(date(2026,11,8),3218.688),
            activity(date(2026,11,9),4828.032), activity(date(2026,11,15),6437.376),
            activity(date(2026,11,15),10000,'strength')]
    result = summary(rows, date(2026,11,15))
    assert result['rolling_14']['distance_m'] == 16093.44
    assert result['rolling_7']['distance_m'] == 11265.408
    assert result['current_week']['distance_m'] == 11265.408
    assert result['selected']['strength_count'] == 1
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
    assert validate_acceptance(date(2026,11,2),date(2026,11,15),[],date(2026,11,2),True,True)


def test_association_uses_actual_elapsed_hours():
    zone = ZoneInfo('America/New_York')
    start = datetime(2026,11,2,8,0,tzinfo=zone)
    candidates = [{'id':'run','start_at':start,'elapsed_s':3600,'sport':'running'}]
    result = preceding_sessions(datetime(2026,11,3,9,0,tzinfo=zone),candidates,'America/New_York')
    assert result[0]['elapsed_hours'] == 24
    assert result[0]['day_label'] == 'next_day'
    assert preceding_sessions(datetime(2026,11,4,1,0,tzinfo=zone),candidates,'America/New_York')[0]['elapsed_hours'] == 40


def test_sparse_recovery():
    assert trailing_mean([(date(2026,11,9),40),(date(2026,11,11),50),(date(2026,11,15),60)],
                         date(2026,11,15)) == {'mean':50,'n':3,'days':7}
    assert trailing_mean([],date(2026,11,15))['mean'] is None
