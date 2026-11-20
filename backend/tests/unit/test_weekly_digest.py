import uuid
from datetime import date

import pytest

from app.services.weekly_digest import assemble_week, planned_duration_s, session_outcome, week_bounds

TODAY = date(2030, 1, 9)


def _c(status, **subject):
    return {"status": status, "activity_id": None, "strong_workout_id": None, "manual_session_id": None, **subject}


@pytest.mark.parametrize(
    "day, completion, expected",
    [
        (8, _c("completed_as_planned", activity_id="a"), "completed"),
        (8, _c("completed_modified", activity_id="a"), "modified"),
        (8, _c("partial", activity_id="a"), "partial"),
        (8, _c("moved", activity_id="a"), "moved"),
        (8, _c("skipped"), "missed"),
        (8, _c("unknown", activity_id="a"), "recorded"),
        (8, _c("extra", strong_workout_id="w"), "recorded"),
        (8, None, "not_recorded"),
        (8, _c("unknown"), "not_recorded"),
        (9, None, "planned"),
        (12, None, "planned"),
    ],
)
def test_session_outcome_table(day, completion, expected):
    assert session_outcome(date(2030, 1, day), completion, TODAY) == expected


def test_week_bounds_sunday_and_monday():
    monday = date(2030, 1, 7)
    sunday = date(2030, 1, 13)
    assert week_bounds(sunday) == (monday, sunday)
    assert week_bounds(monday) == (monday, sunday)


def test_planned_duration_prefers_direct_then_time_structure():
    time_step = {"type": "work", "duration_type": "time", "duration_value": 600, "target": None}
    time_structure = [time_step, {**time_step, "duration_value": 300}]
    distance_step = {**time_step, "duration_type": "distance"}

    assert planned_duration_s({"planned_duration_s": 1800, "structure": time_structure}) == 1800.0
    assert planned_duration_s({"structure": time_structure}) == 900.0
    assert planned_duration_s({"structure": [distance_step]}) is None
    assert planned_duration_s({"structure": [{"type": "bad"}]}) is None
    assert planned_duration_s({"planned_duration_s": 0}) is None


def _assemble(**over):
    base = dict(
        week_start=date(2030, 1, 7),
        today=date(2030, 1, 9),
        timezone="America/New_York",
        calendar_version=1,
        sessions=[],
        removed=[],
        completions={},
        runs=[],
        lifts=[],
        manuals=[],
        assessments={},
        intervals={},
        activity_facts={},
        pace_mps=None,
        activity_coverage_complete=True,
    )
    return assemble_week(**{**base, **over})


def _session(
    day,
    kind="run",
    *,
    uid=None,
    recipe=None,
    intent="Easy run",
    duration=None,
    distance=None,
    slot=0,
    revision=1,
    structure=None,
):
    return {
        "session_uid": uid or str(uuid.uuid4()),
        "revision": revision,
        "local_date": date(2030, 1, day),
        "slot": slot,
        "kind": kind,
        "recipe_id": recipe,
        "custom": False,
        "intent": intent,
        "planned_duration_s": duration,
        "planned_distance_m": distance,
        "structure": structure,
    }


def test_to_date_split_and_unknown_planned_time():
    monday = _session(7, uid="monday", duration=1800)
    totals_week = _assemble(
        sessions=[monday, _session(9), _session(12, duration=3600)],
        completions={"monday": _c("completed_as_planned", activity_id="a1")},
    )
    totals = totals_week["totals"]
    assert totals["sessions"]["planned"] == 3
    assert totals["sessions"]["planned_to_date"] == 2
    assert totals["time"]["planned_s"] == 5400.0
    assert totals["time"]["planned_to_date_s"] == 1800.0
    assert totals["time"]["planned_unknown"] == 1
    assert totals["sessions"]["by_outcome"] == dict(
        completed=1,
        modified=0,
        partial=0,
        moved=0,
        missed=0,
        recorded=0,
        not_recorded=0,
        planned=2,
    )
    assert totals_week["days_elapsed"] == 3
    assert _assemble(week_start=date(2030, 1, 14))["days_elapsed"] == 0


def test_mobility_and_rest_stay_out_of_headline():
    week = _assemble(
        sessions=[_session(7, "rest"), _session(8, "mobility", uid="mob", duration=600), _session(9, duration=1800)],
        completions={"mob": _c("completed_as_planned", manual_session_id="m1")},
        manuals=[dict(id="m1", date=date(2030, 1, 8), kind="mobility", duration_s=600, linked_activity_id=None)],
    )
    assert [row["kind"] for row in week["sessions"]] == ["mobility", "run"]
    assert week["totals"]["by_kind"]["mobility"]["planned"] == 1
    assert week["totals"]["sessions"]["planned"] == 1
    assert week["totals"]["time"]["planned_s"] == 1800.0
    assert week["totals"]["time"]["actual_s"] == 0.0
    assert week["unplanned"] == []


def test_unplanned_and_linked_manual_rules():
    week = _assemble(
        completions={"extra": _c("extra", strong_workout_id="w1")},
        runs=[dict(activity_id="a1", local_date=date(2030, 1, 7), timer_s=1800, distance_m=5000)],
        lifts=[dict(id="w1", local_date=date(2030, 1, 8), duration_s=1200)],
        manuals=[dict(id="m1", date=date(2030, 1, 7), kind="run", duration_s=1800, linked_activity_id="a1")],
    )
    assert [row["id"] for row in week["unplanned"]] == ["a1", "w1"]
    assert week["totals"]["sessions"]["unplanned"] == 2
    assert week["totals"]["time"]["actual_s"] == week["totals"]["time"]["unplanned_s"] == 3000.0


def test_moved_run_counts_in_week_it_was_run():
    week = _assemble(
        sessions=[_session(7, uid="run")],
        completions={"run": _c("moved", activity_id="a1")},
        runs=[dict(activity_id="a1", local_date=date(2030, 1, 6), timer_s=1800, distance_m=5000)],
    )
    (row,) = week["sessions"]
    assert row["actual"]["local_date"] == "2030-01-06"
    assert row["outcome"] == "moved"
    assert week["totals"]["run_distance"]["actual_m"] == 0.0
    assert week["unplanned"] == []


def test_unknown_amounts_are_counted_not_zeroed():
    week = _assemble(
        runs=[dict(activity_id="a1", local_date=date(2030, 1, 7), timer_s=None, distance_m=None)],
        manuals=[dict(id="m1", date=date(2030, 1, 7), kind="run", duration_s=600, linked_activity_id=None)],
    )
    assert week["totals"]["run_distance"]["actual_unknown"] == 2
    assert week["totals"]["run_distance"]["actual_m"] == 0.0
    assert week["totals"]["time"]["actual_unknown"] == 1
    assert week["totals"]["time"]["actual_s"] == 600.0


def test_planned_distance_uses_pace_and_flags_estimates():
    sessions = [_session(7, duration=3600), _session(8, distance=5000)]
    estimated = _assemble(sessions=sessions, pace_mps=2.0)
    first, second = estimated["sessions"]
    assert first["planned_distance_m"] == 7200.0
    assert first["planned_distance_estimated"] is True
    assert second["planned_distance_m"] == 5000.0
    assert second["planned_distance_estimated"] is False
    assert estimated["totals"]["run_distance"]["planned_estimated"] == 1
    unknown = _assemble(sessions=sessions, pace_mps=None)
    assert unknown["sessions"][0]["planned_distance_m"] is None
    assert unknown["totals"]["run_distance"]["planned_unknown"] == 1


def test_removed_sessions_counted_and_rest_ignored():
    week = _assemble(
        removed=[
            _session(8, "run", uid="run"),
            _session(7, "strength", uid="strength"),
            _session(9, "rest", uid="rest"),
        ]
    )
    assert [row["session_uid"] for row in week["removed"]] == ["strength", "run"]
    assert week["totals"]["sessions"]["removed"] == 2


def test_key_session_execution():
    sessions = [
        _session(7, uid="long", recipe="REC002"),
        _session(8, uid="quality", recipe="REC003"),
        _session(9, uid="easy"),
        _session(10, uid="unlinked", recipe="REC003"),
    ]
    component = {"name": "duration_ratio", "value": 0.8, "status": "partially_met"}
    week = _assemble(
        sessions=sessions,
        completions={
            uid: _c("completed_as_planned", activity_id=f"a{index}")
            for index, uid in enumerate(("long", "quality", "easy"), 1)
        },
        runs=[
            dict(activity_id=f"a{index}", local_date=date(2030, 1, 6 + index), timer_s=1800, distance_m=5000)
            for index in range(1, 4)
        ],
        assessments={
            "quality": {
                "status": "available",
                "reason_codes": [],
                "quality_flags": ["EXCEEDED"],
                "value": {"components": [component]},
            }
        },
        intervals={"a2": {"n_planned": 6, "n_completed": 4}},
        activity_facts={
            "a1": {
                "sport": "treadmill_running",
                "avg_hr_bpm": 150.0,
                "moving_pace_s_per_km": 330.0,
                "rpe": 4.0,
                "rpe_source": "manual",
            }
        },
    )
    long_run, quality, easy, unlinked = week["sessions"]
    assert quality["execution"] == {
        "assessment_status": "available",
        "reason_codes": [],
        "components": [component],
        "quality_flags": ["EXCEEDED"],
        "reps_planned": 6,
        "reps_completed": 4,
    }
    assert long_run["execution"]["assessment_status"] is None
    assert long_run["execution"]["reason_codes"] == ["ASSESSMENT_MISSING"]
    assert long_run["execution"]["reps_planned"] is None
    assert long_run["execution"]["reps_completed"] is None
    assert long_run["actual"]["sport"] == "treadmill_running"
    assert long_run["actual"]["rpe_source"] == "manual"
    assert quality["actual"]["avg_hr_bpm"] is None and quality["actual"]["sport"] is None
    assert easy["key"] is False and easy["execution"]["assessment_status"] is None
    assert unlinked["key"] is True and unlinked["execution"] is None
    assert week["totals"]["key_sessions"]["planned"] == 3


def test_non_activity_actual_has_null_activity_facts():
    week = _assemble(
        sessions=[_session(7, kind="strength", uid="strength")],
        completions={"strength": _c("completed_as_planned", strong_workout_id="w1")},
        lifts=[dict(id="w1", local_date=date(2030, 1, 7), duration_s=1200)],
        activity_facts={"w1": {"sport": "treadmill_running"}},
    )
    actual = week["sessions"][0]["actual"]
    assert all(actual[field] is None for field in ("sport", "avg_hr_bpm", "moving_pace_s_per_km", "rpe", "rpe_source"))


def test_revision_over_one_is_changed():
    week = _assemble(sessions=[_session(7, revision=2), _session(8, revision=1)])
    assert [row["changed"] for row in week["sessions"]] == [True, False]


def test_missing_subject_row_keeps_outcome():
    week = _assemble(
        sessions=[_session(7, uid="run")], completions={"run": _c("completed_as_planned", activity_id="gone")}
    )
    (row,) = week["sessions"]
    assert row["actual"] is None
    assert row["outcome"] == "completed"


def test_self_reported_strength_counts_as_done_with_unknown_time():
    week = _assemble(
        sessions=[_session(8, "strength", uid="lift", duration=3600)],
        completions={"lift": _c("completed_as_planned", match_method="user_marked")},
    )
    assert week["totals"]["by_kind"]["strength"]["done"] == 1
    assert week["totals"]["time"]["actual_unknown"] == 1
    assert week["sessions"][0]["actual"] is None
