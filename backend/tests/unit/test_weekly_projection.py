from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.calendar_models import SessionCompletion
from app.metrics.contract import RunFact
from app.services import weekly_projection as projection_service
from app.services.weekly_projection import planned_distance, recent_pace_mps


def _run(day: int, distance: float | None, timer: float | None) -> RunFact:
    return RunFact(
        activity_id=uuid4(),
        start_at=datetime(2030, 1, day, 12, tzinfo=UTC),
        end_at=None,
        local_date=date(2030, 1, day),
        sport="running",
        timer_s=timer,
        distance_m=distance,
        workout_label=None,
    )


def test_recent_pace_uses_only_the_window_and_positive_values():
    runs = [_run(1, 1000, 100), _run(5, 200, 100), _run(9, 400, 100), _run(10, 0, 100), _run(11, 500, None)]
    assert recent_pace_mps(runs, date(2030, 1, 30), 28) == (3.0, 2)


def test_recent_pace_ignores_runs_after_as_of():
    runs = [_run(5, 200, 100), _run(9, 1000, 100)]
    assert recent_pace_mps(runs, date(2030, 1, 7)) == (2.0, 1)


def test_recent_pace_empty_is_unknown():
    assert recent_pace_mps([], date(2030, 1, 7)) == (None, 0)


def test_explicit_distance_precedes_structure_and_duration():
    assert planned_distance(
        {"planned_distance_m": 5000, "planned_duration_s": 3600, "structure": [{"type": "bad"}]}, None
    ) == (5000, False)


def test_repeats_and_speed_targets_are_estimated():
    row = {
        "structure": [
            {
                "type": "repeat",
                "count": 3,
                "steps": [
                    {"type": "work", "duration_type": "distance", "duration_value": 400},
                    {
                        "type": "recovery",
                        "duration_type": "time",
                        "duration_value": 60,
                        "target": {"modality": "speed", "low": 2, "high": 4},
                    },
                ],
            }
        ]
    }
    assert planned_distance(row, None) == (1740, True)


def test_time_fallback_and_remainder_are_estimated():
    row = {
        "structure": [
            {
                "type": "work",
                "duration_type": "time",
                "duration_value": 600,
                "target": {"modality": "hr", "low": 120, "high": 150},
            }
        ],
        "planned_duration_s": 900,
    }
    assert planned_distance(row, 3) == (2700, True)
    assert planned_distance(row, None) == (None, False)
    assert planned_distance({"structure": [{"type": "bad"}], "planned_duration_s": 900}, 3) == (None, False)


def test_mixed_structure_does_not_add_duration_again():
    row = {
        "structure": [
            {"type": "work", "duration_type": "distance", "duration_value": 1000},
            {"type": "recovery", "duration_type": "time", "duration_value": 60},
        ],
        "planned_duration_s": 3600,
    }
    assert planned_distance(row, 2) == (1120, True)
    assert planned_distance(
        {
            "structure": [{"type": "work", "duration_type": "distance", "duration_value": 1000}],
            "planned_duration_s": 3600,
        },
        None,
    ) == (1000, False)


def test_zero_speed_target_is_preserved_over_history():
    def row(low, high):
        return {
            "structure": [
                {
                    "type": "recovery",
                    "duration_type": "time",
                    "duration_value": 60,
                    "target": {"modality": "speed", "low": low, "high": high},
                }
            ]
        }

    assert planned_distance(row(0, 0), 3) == (0, True)
    assert planned_distance(row(0, 2), 3) == (60, True)


@pytest.mark.parametrize(
    ("days_ago", "subject_field", "unrecorded_past"),
    [
        (1, "activity_id", 0),
        (0, "activity_id", 0),
        (0, "strong_workout_id", 0),
        (0, "manual_session_id", 0),
        (1, None, 1),
    ],
)
def test_unknown_completion_projection(monkeypatch, days_ago, subject_field, unrecorded_past):
    today = date(2026, 11, 18)
    session_uid = uuid4()
    completion = SessionCompletion(session_uid=session_uid, status="unknown")
    if subject_field is not None:
        setattr(completion, subject_field, uuid4())
    plan = [
        {
            "kind": "run",
            "session_uid": session_uid,
            "local_date": today - timedelta(days=days_ago),
            "planned_distance_m": 5000,
        },
        {"kind": "run", "session_uid": uuid4(), "local_date": today, "planned_distance_m": 3000},
    ]
    session = Mock(spec=Session)
    session.get.return_value = None
    session.scalars.side_effect = [Mock(all=Mock(return_value=[completion])), Mock(all=Mock(return_value=[]))]
    monkeypatch.setattr(projection_service.calendar, "calendar_today", lambda session: today)
    monkeypatch.setattr(projection_service.calendar, "state_at", lambda session, head: plan)
    monkeypatch.setattr(projection_service, "athlete_tz", lambda session: ZoneInfo("UTC"))
    monkeypatch.setattr(projection_service, "load_runs", lambda *args: [])
    monkeypatch.setattr(projection_service, "activities_coverage_complete", lambda *args: True)

    result = projection_service.weekly_projection(session)

    assert result["unrecorded_past_runs"] == unrecorded_past
    assert result["remaining_runs"] == 1
    assert result["remaining_distance_m"] == 3000
    assert result["missing_planned_runs"] == 0
