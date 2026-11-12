from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from app.metrics import long_run
from app.metrics.contract import RunFact
from app.metrics.long_run import classify, delayed_status, exposure_outcome, window_outcome

DAY = date(2026, 11, 15)


def run(month: int, day: int, timer: float | None, distance: float | None,
        *, hour: int = 12, label: str | None = None, sport: str = "running") -> RunFact:
    return RunFact(UUID(int=month * 100 + day + hour * 1000), datetime(2026, month, day, hour, tzinfo=UTC),
                   None, date(2026, month, day), sport, timer, distance, label)


L = run(11, 15, 5040, 13500, hour=14)
PRIOR = [run(10, 20, 4500, 12200), run(10, 25, 2400, 6000), run(11, 1, 3000, 8000),
         run(11, 5, 2700, 7000), run(11, 10, 2400, 6500), run(11, 12, 2700, 6500),
         run(11, 13, 2460, 6500)]


def outcome(history: list[RunFact], *, linked: bool = False, recipe: str | None = None,
            target: RunFact = L, coverage: bool = True) -> dict:
    return exposure_outcome(target, history, linked, recipe, coverage, "unknown", [])


def test_rule_long_spec_numbers() -> None:
    result = outcome([*PRIOR, L])
    value = result["value"]
    assert (value["classification"], value["classification_source"], value["classification_confidence"]) == (
        "long", "long_rule", "low")
    assert value["prior_max_timer_s"] == 4500.0
    assert value["prior_max_distance_m"] == 12200.0
    assert value["duration_ratio_to_recent_max"] == 1.12
    assert value["distance_ratio_to_recent_max"] == 1.107
    assert value["week_timer_s"] == 12600.0
    assert value["week_distance_m"] == 33000.0
    assert value["weekly_share_duration"] == 0.4
    assert value["weekly_share_distance"] == 0.409
    assert result["status"] == "available"
    assert result["quality_flags"] == ["LOW_CONFIDENCE_CLASSIFICATION"]
    assert result["quality_status"] == "limited"


def test_plan_and_manual_precedence() -> None:
    planned = outcome([*PRIOR, L], linked=True, recipe="REC002")
    assert planned["value"]["classification_source"] == "plan_link"
    assert planned["quality_flags"] == []
    assert planned["quality_status"] == "good"
    not_long = outcome([*PRIOR, L], linked=True, recipe="REC001")
    assert not_long["status"] == "not_applicable"
    assert not_long["reason_codes"] == ["NOT_LONG_RUN"]
    manual = outcome([PRIOR[0], PRIOR[1], replace(L, workout_label="long")],
                     target=replace(L, workout_label="long"))
    assert manual["value"]["classification_source"] == "manual"
    assert "RETURN_FROM_BREAK" in manual["quality_flags"]
    assert manual["value"]["weekly_share_duration"] == 1.0
    assert manual["value"]["duration_ratio_to_recent_max"] == 1.12


def test_unknown_no_prior_boundary_and_same_day() -> None:
    unknown = outcome([PRIOR[0], PRIOR[1], L])
    assert unknown["status"] == "not_assessable"
    assert unknown["reason_codes"] == ["CLASSIFICATION_UNKNOWN", "INSUFFICIENT_HISTORY"]
    no_prior = outcome([replace(L, workout_label="long")], target=replace(L, workout_label="long"))
    assert no_prior["status"] == "partial"
    assert no_prior["reason_codes"] == ["INSUFFICIENT_HISTORY"]
    assert no_prior["value"]["weekly_share_duration"] == 1.0
    four = [run(11, d, 3000, 8000) for d in (1, 3, 5, 7)]
    assert classify(replace(L, timer_s=3990), four, False, None)[0] == "long"
    assert classify(replace(L, timer_s=3989), four, False, None)[0] == "not_long"
    earlier = run(11, 15, 2000, 5000, hour=10)
    later = run(11, 15, 2000, 5000, hour=20)
    same_day = outcome([*four, earlier, L, later])
    assert same_day["value"]["week_timer_s"] == 9040.0


def test_delayed_and_window_latest() -> None:
    assert delayed_status([]) == "unknown"
    assert delayed_status([("post_run", [3.0])]) == "unknown"
    assert delayed_status([("delayed_followup", [0.0])]) == "none_reported"
    assert delayed_status([("delayed_followup", [4.0])]) == "reported"
    entries = [{"classification": "long", "local_date": "2026-11-08"},
               {"classification": "not_long", "local_date": "2026-11-10"},
               {"classification": "long", "local_date": "2026-11-15"}]
    result = window_outcome(entries)
    assert result["value"]["long_run_count"] == 2
    assert result["value"]["latest"] == entries[-1]
    assert window_outcome([], False)["status"] == "missing"
    assert window_outcome([], False)["value"] is None
    assert window_outcome(entries, False)["status"] == "partial"
    assert window_outcome(entries[:1], True, 2)["quality_flags"] == ["ACTIVITY_RESULT_MISSING"]
    assert window_outcome([{"classification": "unknown"}], True)["status"] == "partial"


def test_incomplete_comparator_week_and_nonfinite_inputs() -> None:
    result = exposure_outcome(replace(L, workout_label="long"), [*PRIOR, L], True, "REC002",
                              False, "unknown", [], False)
    assert "PARTIAL_COMPARATOR" in result["quality_flags"]
    assert "PARTIAL_WEEK" in result["quality_flags"]
    invalid = replace(L, timer_s=float("inf"), distance_m=float("nan"), workout_label="long")
    result = outcome([*PRIOR, invalid], target=invalid)
    assert result["status"] == "partial"
    assert result["value"]["timer_s"] is None
    assert result["value"]["distance_m"] is None
    assert result["value"]["duration_ratio_to_recent_max"] is None
    assert result["value"]["distance_ratio_to_recent_max"] is None


def test_classification_threshold_uses_unrounded_median() -> None:
    prior = [run(11, day, 3000.1, 8000) for day in (1, 3, 5, 7)]
    assert classify(replace(L, timer_s=3990.13), prior, False, None)[0] == "not_long"
    assert classify(replace(L, timer_s=3990.134), prior, False, None)[0] == "long"


def test_compute_hash_includes_later_same_day_run(monkeypatch: pytest.MonkeyPatch) -> None:
    later = replace(run(11, 15, 2000, 5000, hour=20), source_revision="later-v1")
    activity = SimpleNamespace(id=L.activity_id, sport="running", start_at=L.start_at, end_at=None)
    fake_session = SimpleNamespace(get=lambda *_args: activity, scalar=lambda *_args: None)
    monkeypatch.setattr(long_run, "athlete_tz", lambda _session: ZoneInfo("UTC"))
    monkeypatch.setattr(long_run, "_plan_link", lambda *_args: (False, None))
    monkeypatch.setattr(long_run, "_linked_checkins", lambda *_args: ([], [], []))
    monkeypatch.setattr(long_run, "metric_source_refs", lambda *_args: {"activity": {"id": str(L.activity_id)}})
    monkeypatch.setattr(long_run, "activities_coverage_complete",
                        lambda _session, first, _end: first == DAY - long_run.timedelta(days=6))
    monkeypatch.setattr(long_run, "load_runs", lambda *_args: [*PRIOR, L, later])
    first = long_run.compute(fake_session, str(L.activity_id))[0]
    assert first.source_refs["weekly_other_activity_ids"] == [str(later.activity_id)]
    assert first.source_refs["history"][-1]["source_revision"] == "later-v1"
    assert first.source_refs["coverage_complete_week"] is True
    assert first.source_refs["coverage_complete_comparator"] is False
    monkeypatch.setattr(long_run, "load_runs", lambda *_args: [*PRIOR, L, replace(later, source_revision="later-v2")])
    second = long_run.compute(fake_session, str(L.activity_id))[0]
    assert first.source_refs["input_hash"] != second.source_refs["input_hash"]
