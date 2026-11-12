from dataclasses import replace
from datetime import date
from unittest.mock import Mock

import pytest

from app.metrics.anchors import ActiveAnchor
from app.metrics.intensity import (
    StreamIn,
    activity_outcome,
    compute,
    distribution,
    modality_outcome,
    sample_valid,
    window_outcome,
    zone,
)

DAY = date(2026, 11, 15)
ANCHORS = {kind: ActiveAnchor(kind, kind, value, "moderate", date(2027, 1, 1), date(2026, 1, 1), kind)
           for kind, value in [("hr_aerobic_upper", 150), ("hr_threshold_lower", 170),
                               ("speed_aerobic_upper", 3.0), ("speed_threshold_lower", 3.6)]}


def spec_stream():
    times = list(range(3421)) + [3600]
    hr = [140 if t < 2700 or t >= 3420 else 160 if t < 3150 else 175 if t < 3300 else 0 for t in times]
    return StreamIn(times, hr, [None] * len(times), [(0, 3600)])


def small_stream():
    return StreamIn([0, 5, 10, 15, 20, 50, 55, 60, 62, 70],
                    [140, 150, 169, 170, 200, 145, 25, 150, 160, 150],
                    [2.5, 3.0, 3.59, 3.6, 3.0, None, 2.9, 3.0, 11.0, 3.0], [(0, 60), (62, 70)])


def test_spec_3600():
    stream = spec_stream()
    hr = modality_outcome("hr", stream, ANCHORS, DAY, 3600)
    for key, expected in {"easy_s": 2700.0, "moderate_s": 450.0, "high_s": 150.0, "valid_s": 3300.0,
                          "unknown_s": 300.0, "eligible_timer_s": 3600.0, "coverage": .917,
                          "unclassified_s": 0.0, "status": "available", "quality_status": "good",
                          "fraction_valid": {"easy": .818, "moderate": .136, "high": .045},
                          "fraction_timer": {"easy": .75, "moderate": .125, "high": .042}}.items():
        assert hr[key] == expected
    outcome = activity_outcome(stream, ANCHORS, DAY, 3600)
    assert outcome["status"] == "partial" and outcome["quality_status"] == "good"
    assert outcome["reason_codes"] == ["SPEED_NOT_RECORDED"]
    assert outcome["value"]["speed"]["status"] == "missing"


def test_small_trace_hr():
    hr = modality_outcome("hr", small_stream(), ANCHORS, DAY, 68)
    assert [hr[k] for k in ("easy_s", "moderate_s", "high_s", "valid_s", "unknown_s", "eligible_timer_s")] == [10, 18, 5, 33, 35, 68]
    assert hr["coverage"] == .485 and hr["status"] == "partial" and hr["quality_status"] == "insufficient"
    assert hr["fraction_valid"] == {"easy": .303, "moderate": .545, "high": .152}
    assert hr["fraction_timer"] == {"easy": .147, "moderate": .265, "high": .074}
    assert hr["reason_codes"] == ["LOW_COVERAGE"]


def test_small_trace_speed():
    speed = modality_outcome("speed", small_stream(), ANCHORS, DAY, 68)
    assert [speed[k] for k in ("easy_s", "moderate_s", "high_s", "valid_s", "unknown_s")] == [10, 10, 5, 25, 43]
    assert speed["coverage"] == .368
    assert speed["fraction_valid"] == {"easy": .4, "moderate": .4, "high": .2}


def test_boundaries():
    assert [zone(v, 150, 170) for v in (149.9, 150, 170)] == ["easy", "moderate", "high"]
    assert sample_valid("hr", 30) and sample_valid("hr", 230)
    assert sample_valid("speed", 0) and sample_valid("speed", 10)
    for v in (None, float("nan"), float("inf"), -1):
        assert not sample_valid("hr", v) and not sample_valid("speed", v)


def test_irregular_intervals():
    stream = StreamIn([0, 1, 4, 11, 12], [140, 160, 175, 140, 140], [], [(0, 12)])
    result = distribution("hr", stream, 150, 170)
    assert [result[k] for k in ("easy_s", "moderate_s", "high_s")] == [2, 3, 7]


def test_pause_excluded():
    stream = StreamIn([0, 5, 10, 15], [140] * 4, [], [(0, 5), (10, 15)])
    result = distribution("hr", stream, 150, 170)
    assert result["eligible_timer_s"] == result["easy_s"] == 10


def test_gap_unknown():
    result = distribution("hr", StreamIn([0, 30, 31], [140] * 3, [], [(0, 31)]), 150, 170)
    assert result["unknown_s"] == 30 and result["easy_s"] == 1


def test_uncovered_edges():
    result = modality_outcome("hr", StreamIn([10, 20], [140, 140], [], [(0, 30)]), ANCHORS, DAY, 30)
    assert result["easy_s"] == 10 and result["unknown_s"] == 20 and result["eligible_timer_s"] == 30
    assert result["coverage"] == .333 and result["status"] == "partial" and result["quality_status"] == "insufficient"


def test_empty_records():
    result = distribution("hr", StreamIn([], [], [], [(0, 30)]), 150, 170)
    assert result["unknown_s"] == 30 and result["valid_s"] == 0 and result["fraction_valid"] is None


def test_union():
    result = distribution("hr", StreamIn(list(range(16)), [140] * 16, [], [(0, 10), (5, 15)]), 150, 170)
    assert result["eligible_timer_s"] == 15


@pytest.mark.parametrize("times", [[0, 0, 1], [1, 0]])
def test_invalid_stream_order(times):
    with pytest.raises(ValueError, match="invalid_stream_order"):
        distribution("hr", StreamIn(times, [140] * len(times), [], [(0, 10)]), 150, 170)


@pytest.mark.parametrize("anchors", [{}, {**ANCHORS, "hr_threshold_lower": replace(ANCHORS["hr_threshold_lower"], confidence="insufficient")}])
def test_anchor_missing_and_insufficient(anchors):
    result = modality_outcome("hr", small_stream(), anchors, DAY, 68)
    assert result["status"] == "not_assessable" and result["reason_codes"] == ["ANCHOR_MISSING"]
    assert result["easy_s"] is None and result["confidence"] is None and result["anchors_used"] == []


def test_config_error():
    anchors = {**ANCHORS, "hr_aerobic_upper": replace(ANCHORS["hr_aerobic_upper"], value_low=170),
               "hr_threshold_lower": replace(ANCHORS["hr_threshold_lower"], value_low=150)}
    result = modality_outcome("hr", small_stream(), anchors, DAY, 68)
    assert result["status"] == "invalid" and result["reason_codes"] == ["ANCHOR_CONFIG_ERROR"]
    assert result["easy_s"] is None and len(result["anchors_used"]) == 2


def test_no_stream():
    result = activity_outcome(None, ANCHORS, DAY, 68)
    assert result["status"] == "missing" and result["reason_codes"] == ["NO_STREAM"]
    assert result["anchor_keys"] == []


def test_flags():
    anchors = {**ANCHORS, "hr_aerobic_upper": replace(ANCHORS["hr_aerobic_upper"], confidence="low", review_after=date(2026, 11, 14))}
    result = modality_outcome("hr", small_stream(), anchors, DAY, 68)
    assert result["flags"] == ["LOW_CONFIDENCE_ANCHOR", "ANCHOR_REVIEW_DUE"]
    result = modality_outcome("hr", small_stream(), anchors, DAY, 100)
    assert result["status"] == "not_assessable" and result["easy_s"] is None
    assert result["flags"][-1] == "TIMER_MISMATCH"
    assert result["timer_diagnostics"] == {"eligible_timer_s": 68, "session_timer_s": 100}


@pytest.mark.parametrize("flag", ["TIMER_EVENTS_MISSING", "TIMER_EVENTS_AMBIGUOUS", "TIMER_MISMATCH"])
def test_bad_timer_gate(flag):
    result = activity_outcome(replace(small_stream(), quality_flags=(flag,)), ANCHORS, DAY, 68)
    assert result["status"] == "not_assessable" and result["reason_codes"] == [flag]
    for modality in ("hr", "speed"):
        assert result["value"][modality]["easy_s"] is None


def test_timer_tolerance_and_review_date_boundaries():
    result = modality_outcome("hr", small_stream(), ANCHORS, date(2027, 1, 1), 69)
    assert "TIMER_MISMATCH" not in result["flags"] and "ANCHOR_REVIEW_DUE" not in result["flags"]
    assert modality_outcome("hr", small_stream(), ANCHORS, DAY, 69.001)["status"] == "not_assessable"


def test_no_timer():
    result = modality_outcome("hr", replace(small_stream(), timer_on=[]), ANCHORS, DAY, None)
    assert result["reason_codes"] == ["NO_TIMER_ON_DATA"] and result["easy_s"] is None


def test_window_sum():
    large = {**activity_outcome(spec_stream(), ANCHORS, DAY, 3600), "anchor_set_hash": "large"}
    small = {**activity_outcome(small_stream(), ANCHORS, DAY, 68), "anchor_set_hash": "small"}
    result = window_outcome([large, small, None])
    hr = result["value"]["hr"]
    assert [hr[k] for k in ("easy_s", "moderate_s", "high_s", "valid_s", "unknown_s", "eligible_timer_s")] == [2710, 468, 155, 3333, 335, 3668]
    assert hr["coverage"] == .909 and hr["status"] == "partial"
    assert hr["reason_codes"] == ["ACTIVITIES_NOT_COUNTED", "PARTIAL_ACTIVITY_COVERAGE"]
    assert [hr[k] for k in ("activities_total", "activities_counted", "activities_without_result")] == [3, 2, 1]
    assert result["value"]["anchor_set_hashes"] == ["large", "small"]


def test_window_empty():
    result = window_outcome([])
    assert result["status"] == "available" and result["quality_status"] is None
    assert result["value"]["hr"]["valid_s"] == 0 and result["value"]["hr"]["coverage"] is None
    unknown = window_outcome([], coverage_complete=False)
    assert unknown["status"] == "missing" and unknown["value"]["hr"]["valid_s"] is None
    assert unknown["reason_codes"] == ["SYNC_COVERAGE_INCOMPLETE"]


def test_window_incomplete_and_uncounted():
    row = activity_outcome(small_stream(), ANCHORS, DAY, 68)
    result = window_outcome([row], coverage_complete=False)
    assert result["status"] == "partial" and "SYNC_COVERAGE_INCOMPLETE" in result["reason_codes"]
    result = window_outcome([activity_outcome(small_stream(), {}, DAY, 68)])
    assert result["status"] == "not_assessable" and result["value"]["hr"]["valid_s"] is None


@pytest.mark.parametrize("key", ["w9:2026-11-15", "w7:2026-99-15", "not-a-uuid", "night:2026-11-15"])
def test_parse_keys(key):
    session = Mock()
    session.scalar.return_value = "America/New_York"
    with pytest.raises(ValueError, match="invalid_subject_key"):
        compute(session, key)


def test_a7_artifacts_excluded():
    stream = StreamIn([0, 5, 10, 15], [140, 235, 140, 140], [2.5, 12, 2.5, 2.5], [(0, 15)])
    result = activity_outcome(stream, ANCHORS, DAY, 15)
    for modality in ("hr", "speed"):
        signal = result["value"][modality]
        assert signal["valid_s"] == 10 and signal["unknown_s"] == 5
        assert signal["coverage"] == .667 and signal["status"] == "partial"
    assert result["quality_status"] == "insufficient"


def test_compute_window_provenance_is_stable(monkeypatch):
    from types import SimpleNamespace
    from uuid import UUID

    from app.metrics import intensity
    from app.metrics.contract import sha256_json

    first, second = UUID(int=1), UUID(int=2)
    session = Mock()
    session.scalar.return_value = "America/New_York"
    runs = [SimpleNamespace(activity_id=uid, source_refs={"raw_hash": str(uid)}) for uid in (first, second)]
    monkeypatch.setattr(intensity, "load_runs", lambda *_args: runs)
    monkeypatch.setattr(intensity, "activities_coverage_complete", lambda *_args: False)
    outcome = activity_outcome(small_stream(), ANCHORS, DAY, 68)
    rows = {str(uid): SimpleNamespace(id=uid, dependency_hash=f"hash-{uid}", status=outcome["status"],
                                      value=outcome["value"], anchor_set_hash="anchors", anchor_keys=outcome["anchor_keys"])
            for uid in (first, second)}
    monkeypatch.setattr(intensity, "latest_results", lambda *_args: rows)
    result = compute(session, "w7:2026-11-15")[0]
    rows = dict(reversed(list(rows.items())))
    reordered = compute(session, "w7:2026-11-15")[0]
    assert sha256_json(result.source_refs) == sha256_json(reordered.source_refs)
    assert result.source_refs["activity_ids"] == [str(first), str(second)]
    assert result.source_refs["sources"] == [run.source_refs for run in runs]
    assert [d["id"] for d in result.source_refs["dependencies"]] == [str(first), str(second)]
    assert result.source_refs["input_hash"]
    assert "SYNC_COVERAGE_INCOMPLETE" in result.reason_codes
    assert result.timezone == "America/New_York" and result.window_start.isoformat() == "2026-11-09T05:00:00+00:00"
    assert result.window_end.isoformat() == "2026-11-16T05:00:00+00:00"
