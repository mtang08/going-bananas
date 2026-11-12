from datetime import date, timedelta

from app.metrics.planned_actual import _interval_components, component, planned_actual_outcome

DAY = date(2026, 11, 19)
WORK = [{"type": "work", "duration_type": "time", "duration_value": 60,
         "target": {"modality": "speed", "low": 3.0, "high": 4.0}}]


def plan(**changes: object) -> dict:
    return {"kind": "run", "local_date": DAY, "certainty": "committed",
            "calendar_version_number": 3, "planned_duration_s": 3000,
            "planned_distance_m": None, "structure": WORK, **changes}


def linked(**changes: object) -> dict:
    return {"activity_id": "a1", "match_method": "explicit", "status": "unknown",
            "modification_reason": None, **changes}


def assess(plan_row: dict | None, completion: dict | None, actual: dict | None,
           intervals: dict | None = None, candidates: list[dict] | None = None,
           coverage: bool = True) -> dict:
    return planned_actual_outcome(plan_row, completion, actual, intervals, candidates or [], coverage, DAY)


def test_modified_partial_and_sensible() -> None:
    r = assess(plan(), linked(modification_reason="symptom_onset"), {"kind": "run", "timer_s": 2820},
               {"step_completion_ratio": .5, "target_coverage": .8})
    assert r["value"]["overall_status"] == "completed_modified"
    assert r["derived_completion_status"] == "completed_modified"
    assert r["quality_flags"] == ["SENSIBLE_MODIFICATION"]
    assert [(c["name"], c["status"]) for c in r["value"]["components"]] == [
        ("duration_ratio", "met"), ("step_completion_ratio", "partially_met"), ("target_coverage", "met")]
    p = assess(plan(), linked(), {"kind": "run", "timer_s": 1500},
               {"step_completion_ratio": .5, "target_coverage": .8})
    assert p["value"]["overall_status"] == "partial"
    assert assess(plan(planned_duration_s=4200, structure=None), linked(modification_reason="symptom_onset"),
                  {"kind": "run", "timer_s": 2880})["value"]["overall_status"] == "completed_modified"


def test_unknown_and_missing_plan_and_skipped() -> None:
    unknown = assess(plan(), linked(), {"kind": "run", "timer_s": None}, None)
    assert unknown["value"]["overall_status"] == "unknown"
    assert "COMPONENT_NOT_ASSESSABLE" in unknown["reason_codes"]
    with_reason = assess(plan(), linked(modification_reason="symptom_onset"),
                         {"kind": "run", "timer_s": None}, None)
    assert with_reason["value"]["overall_status"] == "unknown"
    empty = assess(plan(planned_duration_s=None, structure=None), linked(), {"kind": "run", "timer_s": 3000})
    assert empty["reason_codes"] == ["INSUFFICIENT_PLAN"]
    skipped = assess(plan(), linked(status="skipped", match_method="user_marked"), None)
    assert skipped["derived_completion_status"] == "skipped"
    ambiguous = assess(plan(), None, None, candidates=[{"subject_key": "a1", "reason": "AMBIGUOUS_MATCH"}])
    assert ambiguous["value"]["overall_status"] == "unknown"
    assert ambiguous["reason_codes"] == ["AMBIGUOUS_MATCH"]


def test_boundaries_exceeded_target_and_future_priority() -> None:
    assert component("duration_ratio", 899.9, 1000)["status"] == "partially_met"
    assert component("duration_ratio", 900, 1000)["status"] == "met"
    assert component("target_coverage", .75, 1)["status"] == "met"
    assert component("target_coverage", .4, 1)["status"] == "partially_met"
    exceeded = assess(plan(structure=None), linked(), {"kind": "run", "timer_s": 3481})
    assert exceeded["quality_flags"] == ["EXCEEDED"]
    assert exceeded["value"]["components"][0]["status"] == "met"
    near_boundary = assess(plan(), linked(), {"kind": "run", "timer_s": 2699.7},
                           {"step_completion_ratio": .99, "target_coverage": .8})
    assert near_boundary["value"]["components"][0]["value"] == .9
    assert near_boundary["value"]["overall_status"] == "partial"
    both_exceed = assess(plan(planned_distance_m=5000, structure=None), linked(),
                         {"kind": "run", "timer_s": 3600, "distance_m": 6000})
    assert both_exceed["quality_flags"] == ["EXCEEDED"]
    future = assess({**plan(), "local_date": DAY + timedelta(days=1)}, None, None,
                    candidates=[{"reason": "AMBIGUOUS_MATCH"}])
    assert future["reason_codes"] == ["NOT_YET_DUE"]
    assert future["value"]["match_method"] == "none"


def test_excluded_link_stays_linked_unknown() -> None:
    result = assess(plan(), linked(), None)
    assert result["value"]["overall_status"] == "unknown"
    assert result["derived_completion_status"] == "unknown"
    assert result["reason_codes"][0] == "ACTIVITY_EXCLUDED"


def test_target_coverage_rebuilt_before_threshold() -> None:
    intervals = _interval_components({"target_coverage": .75, "step_completion_ratio": 1.0,
                                      "n_planned": 1, "n_completed": 1,
                                      "reps": [{"target_valid_s": 1000.0, "target_in_range_s": 749.6}]})
    assert intervals is not None and intervals["target_coverage"] == .7496
    result = assess(plan(), linked(), {"kind": "run", "timer_s": 3000}, intervals)
    target = next(c for c in result["value"]["components"] if c["name"] == "target_coverage")
    assert target["value"] == .75
    assert target["status"] == "partially_met"
