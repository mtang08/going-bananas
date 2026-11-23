from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.fit_models import ActivityLap
from app.models import Activity
from app.read.treadmill_intervals import confirmed_lap_paces, lap_identity


def test_confirmed_pace_survives_lap_replay_but_not_index_reuse() -> None:
    start = datetime(2026, 11, 22, 15, tzinfo=UTC)
    original = ActivityLap(id=uuid4(), lap_index=2, start_at=start, timer_s=300, distance_m=1000)
    activity = Activity(
        sport="treadmill_running",
        treadmill_interval_paces={"2": {"lap_identity": lap_identity(original), "pace_s_per_mile": 420}},
    )
    replay = ActivityLap(id=uuid4(), lap_index=2, start_at=start, timer_s=300, distance_m=1050)
    assert confirmed_lap_paces(activity, [replay]) == {2: 420}
    replay.start_at += timedelta(minutes=1)
    assert confirmed_lap_paces(activity, [replay]) == {}
