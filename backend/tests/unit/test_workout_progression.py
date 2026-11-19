from datetime import date

from app.services.workout_progression import assemble_groups, plan_facts, session_point


def step(kind, dtype, value, target=None):
    return {"type": kind, "duration_type": dtype, "duration_value": value, "target": target}


def structure(count=4, duration=300):
    return [
        step("warmup", "time", 600),
        {
            "type": "repeat",
            "count": count,
            "steps": [
                step("work", "time", duration, {"modality": "speed", "low": 3.4, "high": 3.8}),
                step("recovery", "time", 120),
            ],
        },
        step("cooldown", "time", 600),
    ]


FOUR_BY_FIVE = structure()
PLANNED = {
    "session_uid": "s1",
    "local_date": date(2026, 11, 9),
    "recipe_id": "REC003",
    "intent": "Threshold",
    "structure": FOUR_BY_FIVE,
}
RUN = {"id": "a1", "local_date": date(2026, 11, 9), "sport": "running"}


def rep(speed, hr, timer=300.0, done=True, speed_status="available"):
    return {
        "fully_completed": done,
        "speed_status": speed_status,
        "mean_speed_mps": speed,
        "actual_timer_s": timer,
        "hr_median_bpm": hr,
    }


def interval(status, reasons, reps, n_completed, **extra):
    return {
        "id": "r1",
        "status": status,
        "reason_codes": reasons,
        "value": {
            "reps": reps,
            "n_planned": len(reps),
            "n_completed": n_completed,
            "step_completion_ratio": n_completed / len(reps),
            "cv_speed": None,
            "last_first_change_pct": None,
            "target_coverage": None,
            **extra,
        },
    }


def full_reps():
    return [rep(3.6, 158), rep(3.6, 160), rep(3.4, 162), rep(3.6, 164)]


def test_plan_facts():
    assert plan_facts(FOUR_BY_FIVE) == {
        "signature": "ws1:4xt300",
        "n_work": 4,
        "recovery_s": 360,
        "target_modalities": ["speed"],
    }
    assert plan_facts(None) is None


def test_full_session():
    point = session_point(
        PLANNED, None, RUN, interval("available", [], full_reps(), 4, cv_speed=2.817, last_first_change_pct=0.0)
    )
    assert point["status"] == "available" and point["reason_codes"] == []
    assert (point["work_speed_mps"], point["work_hr_bpm"], point["work_m_per_beat"]) == (3.55, 161.0, 1.323)
    assert (point["reps_used"], point["cv_speed"], point["local_date"]) == (4, 2.817, "2026-11-09")


def test_partial_session_uses_completed_reps():
    reasons = ["INCOMPLETE_WORK_STEP", "INCOMPLETE_WORK_STEPS"]
    reps = [rep(3.45, 160) for _ in range(3)] + [rep(3.45, 165, timer=250, done=False)]
    point = session_point(PLANNED, None, RUN, interval("partial", reasons, reps, 3))
    assert point["status"] == "partial" and point["reason_codes"] == reasons
    assert (point["work_speed_mps"], point["work_hr_bpm"], point["work_m_per_beat"]) == (3.45, 160, 1.294)


def test_short_reps_keep_hr_unknown():
    planned = {
        **PLANNED,
        "structure": [step("work", "distance", 400), step("recovery", "time", 60), step("work", "distance", 400)],
    }
    point = session_point(planned, None, RUN, interval("available", [], [rep(4.2, None, 95.2), rep(4, None, 100)], 2))
    assert point["work_speed_mps"] == 4.098 and point["work_hr_bpm"] is None
    assert point["work_m_per_beat"] is None and point["reps_used_hr"] == 0 and point["status"] == "available"


def test_reps_without_pace_are_excluded():
    reps = full_reps()
    reps[2] = rep(3.5, 162, speed_status="partial")
    point = session_point(PLANNED, None, RUN, interval("available", [], reps, 4))
    assert point["status"] == "partial" and point["reason_codes"] == ["REPS_EXCLUDED"]
    assert point["reps_used"] == 3
    assert (point["work_speed_mps"], point["work_hr_bpm"], point["work_m_per_beat"]) == (3.6, 160.7, 1.344)


def test_unassessable_and_missing_points():
    point = session_point(
        PLANNED,
        None,
        RUN,
        {"id": "r5", "status": "not_assessable", "reason_codes": ["WATCH_WORKOUT_MISMATCH"], "value": None},
    )
    assert point["status"] == "not_assessable" and point["reason_codes"] == ["WATCH_WORKOUT_MISMATCH"]
    assert point["n_completed"] is None
    point = session_point(PLANNED, {"status": "skipped"}, None, None)
    assert point["status"] == "missing" and point["reason_codes"] == ["NO_LINKED_ACTIVITY"]
    assert point["completion_status"] == "skipped" and point["local_date"] == point["planned_date"]
    point = session_point(PLANNED, None, {**RUN, "sport": "treadmill_running"}, None)
    assert point["reason_codes"] == ["INTERVAL_RESULT_MISSING"] and point["quality_flags"] == ["TREADMILL"]


def test_assemble_groups():
    points = [
        session_point(
            {**PLANNED, "session_uid": uid, "local_date": day, "recipe_id": recipe, "structure": workout},
            None,
            None,
            None,
        )
        for uid, day, recipe, workout in [
            ("a", date(2026, 10, 1), "REC003", FOUR_BY_FIVE),
            ("b", date(2026, 10, 8), "REC003", structure(5, 240)),
            ("c", date(2026, 10, 15), None, FOUR_BY_FIVE),
        ]
    ]
    groups = assemble_groups(points, "signature")
    assert [g["group_key"] for g in groups] == ["sig:ws1:4xt300", "sig:ws1:5xt240"]
    assert groups[0]["sessions_total"] == 2 and groups[0]["latest_date"] == "2026-10-15"
    assert all(g["sessions_assessable"] == 0 for g in groups)
    groups = assemble_groups(points, "recipe")
    assert [g["group_key"] for g in groups] == ["sig:ws1:4xt300", "recipe:REC003"]
    assert groups[0]["group_by"] == "signature"
    assert groups[1]["signature"] is None and groups[1]["signatures"] == ["ws1:4xt300", "ws1:5xt240"]
    assert groups[1]["sessions_total"] == 2 and all(g["sessions_assessable"] == 0 for g in groups)
