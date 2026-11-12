from datetime import date
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.metrics import srpe
from app.metrics.srpe import RpeFact, effective_rpe, session_outcome, window_outcome

DAY = date(2026, 11, 15)


def fact(duration: float | None, manual: float | None = None, garmin: float | None = None) -> RpeFact:
    return RpeFact("run", "run", DAY, duration, manual, garmin, None, None)


def test_run_load_and_manual_precedence() -> None:
    result = session_outcome(fact(2880, garmin=6))
    assert result["value"]["load_au"] == 288.0
    assert result["value"]["duration_min"] == 48.0
    assert result["value"]["rpe_source"] == "garmin_fit"
    assert result["quality_status"] == "good"
    conflict = session_outcome(fact(2880, manual=5, garmin=6))
    assert effective_rpe(fact(2880, manual=5, garmin=6)) == (5, "manual", 6, None, True)
    assert conflict["value"]["load_au"] == 240.0
    assert conflict["quality_flags"] == ["RPE_SOURCE_CONFLICT"]
    assert conflict["quality_status"] == "limited"


@pytest.mark.parametrize(("given", "status", "reason", "load"), [
    (fact(3000, manual=0), "available", [], 0.0),
    (fact(3000), "missing", ["RPE_MISSING"], None),
    (fact(None, manual=5), "missing", ["DURATION_MISSING"], None),
    (fact(3000, manual=11), "invalid", ["RPE_OUT_OF_RANGE"], None),
])
def test_missing_zero_and_invalid(given: RpeFact, status: str, reason: list[str], load: float | None) -> None:
    result = session_outcome(given)
    assert (result["status"], result["reason_codes"], result["value"]["load_au"]) == (status, reason, load)


def test_window_523_and_unknowns() -> None:
    result = window_outcome([fact(2880, garmin=6), fact(2820, manual=5), fact(2400)], [], True)
    assert result["value"] == {"load_au": 523.0, "sessions_total": 3, "sessions_with_rpe": 2,
                               "sessions_without_load": 1, "sessions_missing_duration": 0,
                               "duration_total_s": 8100.0, "duration_with_rpe_s": 5700.0,
                               "coverage_duration": 0.704, "coverage_sessions": 0.667}
    assert (result["status"], result["quality_status"], result["reason_codes"]) == (
        "partial", "limited", ["SESSIONS_WITHOUT_LOAD"])
    missing = window_outcome([fact(3000), fact(3000)], [], True)
    assert missing["value"]["load_au"] is None
    assert missing["value"]["coverage_duration"] == 0.0
    assert missing["value"]["coverage_sessions"] == 0.0
    unknown = window_outcome([fact(None, manual=5)], [], True)
    assert unknown["value"]["coverage_duration"] is None


def test_empty_and_overlap() -> None:
    empty = window_outcome([], [], True)
    assert empty["status"] == "available"
    assert empty["value"]["load_au"] == 0.0
    assert empty["value"]["duration_total_s"] == 0.0
    assert empty["value"]["duration_with_rpe_s"] == 0.0
    assert empty["value"]["coverage_duration"] is None
    assert empty["quality_status"] is None
    overlap = window_outcome([fact(3000, manual=5)], [DAY], True)
    assert overlap["quality_flags"] == ["STRENGTH_SOURCE_OVERLAP"]


def test_unknown_duration_and_incomplete_empty() -> None:
    mixed = window_outcome([fact(3000, manual=5), fact(None, manual=5)], [], True)
    assert mixed["value"]["coverage_duration"] is None
    assert mixed["quality_status"] == "limited"
    all_unknown = window_outcome([fact(None, manual=5)], [], True)
    assert all_unknown["value"]["duration_total_s"] is None
    incomplete = window_outcome([], [], False)
    assert incomplete["status"] == "missing"
    assert incomplete["value"]["load_au"] is None
    assert incomplete["value"]["duration_total_s"] is None


def test_sum_raw_load_before_rounding_and_nonfinite() -> None:
    result = window_outcome([fact(1, manual=3), fact(1, manual=3)], [], True)
    assert result["value"]["load_au"] == 0.1
    assert session_outcome(fact(float("nan"), manual=5))["value"]["duration_s"] is None
    invalid = session_outcome(fact(3000, manual=float("inf")))
    assert invalid["status"] == "invalid"
    assert invalid["value"]["rpe"] is None
    tiny = window_outcome([fact(0.04, manual=5), fact(0.04)], [], True)
    assert tiny["value"]["duration_total_s"] == 0.1
    assert tiny["value"]["coverage_duration"] == 0.5


def test_strength_ignores_garmin_rpe_and_invalid_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    row = SimpleNamespace(source="garmin_fit", rpe=6, collection_delay_s=60)
    strength = srpe._fact("strong:example", "strength", DAY, 3000, [row])
    assert session_outcome(strength)["value"]["load_au"] is None
    monkeypatch.setattr(srpe, "athlete_tz", lambda _session: ZoneInfo("UTC"))
    for key in ("w9:2026-11-15", "strong:x", "manual:x"):
        with pytest.raises(ValueError, match="invalid_subject_key"):
            srpe.compute(None, key)
    fake_session = SimpleNamespace(get=lambda *_args: None)
    assert srpe.compute(fake_session, f"strong:{uuid4()}") == []
    assert srpe.compute(fake_session, f"manual:{uuid4()}") == []
