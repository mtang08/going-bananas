from __future__ import annotations

from datetime import date

import pytest

from app.adapters.strong import StrongCSVError, scan_strong_csv
from app.services.strength_history import subtract_calendar_months

HEADER = "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"


def test_strong_csv_groups_sets_and_keeps_source_weight_text(tmp_path):
    path = tmp_path / "strong.csv"
    path.write_text(HEADER +
                    "2026-11-09 21:13:58,Workout A,1h 5m,Dumbbell Press,1,45.0,8,0,0,\n"
                    "2026-11-09 21:13:58,Workout A,1h 5m,Dumbbell Press,2,45.0,8,0,0,\n")
    workouts, digest, size = scan_strong_csv(path)
    assert len(workouts) == 1
    assert workouts[0].duration_s == 3900
    assert workouts[0].row_count == 2
    assert workouts[0].sets[0]["Weight"] == "45.0"
    assert workouts[0].local_start == "2026-11-09 21:13:58"
    assert len(digest) == 64 and size == path.stat().st_size


def test_strong_csv_rejects_inconsistent_duration(tmp_path):
    path = tmp_path / "strong.csv"
    path.write_text(HEADER +
                    "2026-11-09 21:13:58,Workout A,1h 5m,Press,1,45,8,0,0,\n"
                    "2026-11-09 21:13:58,Workout A,1h 6m,Press,2,45,8,0,0,\n")
    with pytest.raises(StrongCSVError, match="inconsistent_duration"):
        scan_strong_csv(path)


def test_calendar_month_window_clips_month_end():
    assert subtract_calendar_months(date(2026, 11, 10), 18) == date(2025, 5, 10)
    assert subtract_calendar_months(date(2026, 8, 31), 18) == date(2025, 2, 28)


def test_implausible_timer_is_preserved_but_not_counted(tmp_path):
    path = tmp_path / "strong.csv"
    path.write_text(HEADER + "2026-11-09 21:13:58,Workout A,120h 41m,Press,1,45,8,0,0,\n")
    workouts, _, _ = scan_strong_csv(path)
    assert workouts[0].duration_s is None
    assert workouts[0].sets[0]["Duration"] == "120h 41m"
