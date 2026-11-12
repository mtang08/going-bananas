from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from app.domain.analytics import utc_date_bounds
from app.metrics.contract import RunFact
from app.metrics.volume import parse_window_key, totals, volume_outcome

AS_OF = date(2026, 11, 15)


def run(day: int, timer: float | None, distance: float | None, *, sport: str = "running") -> RunFact:
    return RunFact(UUID(int=day), datetime(2026, 11, day, 12, tzinfo=UTC), None,
                   date(2026, 11, day), sport, timer, distance, None)


def test_synthetic_three_runs_and_previous() -> None:
    current = [run(10, 2100, 5800), run(12, 2700, 7400), run(14, 4200, 11200)]
    result = volume_outcome(current, AS_OF, 7, True, True)
    assert result["status"] == "available"
    assert result["quality_status"] == "good"
    assert result["value"]["timer_duration_s"] == 9000.0
    assert result["value"]["distance_m"] == 24400.0
    assert result["value"]["run_count"] == 3
    assert result["value"]["runs_missing_timer"] == 0
    assert result["reason_codes"] == result["quality_flags"] == []
    with_previous = volume_outcome([run(5, 1800, 5000), *current], AS_OF, 7, True, True)
    assert with_previous["value"]["previous"]["timer_duration_s"] == 1800.0
    assert with_previous["value"]["previous"]["distance_m"] == 5000.0
    assert with_previous["value"]["previous"]["start_date"] == "2026-11-02"
    assert with_previous["value"]["previous"]["end_date"] == "2026-11-08"


def test_missing_and_empty_coverage() -> None:
    missing_distance = volume_outcome([run(10, 2100, None, sport="treadmill_running")], AS_OF, 7, True, True)
    assert missing_distance["status"] == "partial"
    assert missing_distance["reason_codes"] == ["DISTANCE_MISSING"]
    assert missing_distance["value"]["distance_m"] is None
    missing_timer = volume_outcome([run(10, None, 5000)], AS_OF, 7, True, True)
    assert missing_timer["reason_codes"] == ["TIMER_MISSING"]
    assert missing_timer["value"]["timer_duration_s"] is None
    empty = volume_outcome([], AS_OF, 7, True, True)
    assert empty["status"] == "available"
    assert empty["value"]["timer_duration_s"] == empty["value"]["distance_m"] == 0.0
    incomplete = volume_outcome([], AS_OF, 7, False, False)
    assert incomplete["status"] == "missing"
    assert incomplete["value"]["timer_duration_s"] is None
    assert incomplete["value"]["previous"]["distance_m"] is None
    assert incomplete["quality_flags"] == ["SYNC_COVERAGE_INCOMPLETE"]


def test_window_bounds_and_keys() -> None:
    start, end = utc_date_bounds(date(2026, 10, 28), date(2026, 11, 3), "America/New_York")
    assert start.isoformat() == "2026-10-28T04:00:00+00:00"
    assert end.isoformat() == "2026-11-04T05:00:00+00:00"
    assert (end - start).total_seconds() == 169 * 3600
    assert parse_window_key("w7:2026-11-15") == (7, AS_OF)
    for key in ("w9:2026-11-15", "x", "w7:2026-13-15"):
        with pytest.raises(ValueError, match="invalid_subject_key"):
            parse_window_key(key)
    selected = totals([run(10, 2100, 5800), run(5, 1800, 5000)], date(2026, 11, 9), date(2026, 11, 16))
    assert selected["run_count"] == 1


def test_raw_sum_then_round_and_nonfinite_missing() -> None:
    small = volume_outcome([run(10, 0.04, 0.04), run(12, 0.04, 0.04)], AS_OF, 7, True, True)
    assert small["value"]["timer_duration_s"] == 0.1
    assert small["value"]["distance_m"] == 0.1
    nonfinite = volume_outcome([run(10, float("nan"), float("inf"))], AS_OF, 7, True, True)
    assert nonfinite["status"] == "partial"
    assert nonfinite["value"]["timer_duration_s"] is None
    assert nonfinite["value"]["distance_m"] is None
