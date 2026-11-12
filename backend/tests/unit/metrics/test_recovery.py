from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from app.metrics import recovery
from app.metrics.recovery import Observation, Subjective, night_outcome, signal_outcome, summary_outcome

DAY = date(2026, 11, 15)


def history(metric, values, *, partition="deviceA"):
    return [Observation(DAY - timedelta(days=i + 1), metric, value, partition, True, {"revision": i})
            for i, value in enumerate(values)]


def current(metric, value, *, partition="deviceA"):
    return Observation(DAY, metric, value, partition, True, {"revision": "current"})


def test_rhr_baseline():
    result = signal_outcome("resting_hr", current("resting_hr", 55), history("resting_hr", [48] * 14 + [52] * 14), DAY)
    assert [result[k] for k in ("baseline_median", "baseline_mad", "z", "valid_nights")] == [50, 2, 1.69, 28]
    assert result["baseline_state"] == "established" and result["adverse"] is True and result["status"] == "available"


def test_outlier():
    result = signal_outcome("resting_hr", current("resting_hr", 55), history("resting_hr", [48] * 14 + [52] * 14 + [150]), DAY)
    assert [result[k] for k in ("baseline_median", "baseline_mad", "z")] == [52, 4, .51]
    assert result["adverse"] is False


def test_hrv():
    result = signal_outcome("hrv", current("hrv", 50), history("hrv", [60] * 15 + [70] * 15), DAY)
    assert result["z"] == -2.27 and result["adverse"] is True and result["baseline_state"] == "established"


def test_provisional():
    result = signal_outcome("hrv", current("hrv", 60), history("hrv", [61.559] * 13 + [66.686] + [72.24] * 13), DAY)
    assert result["z"] == -.89 and result["adverse"] is False and result["baseline_state"] == "provisional"


def test_short_baseline():
    result = signal_outcome("hrv", current("hrv", 60), history("hrv", [50] * 13), DAY)
    assert result["baseline_state"] == "none" and result["z"] is result["adverse"] is None
    assert result["reason_codes"] == ["BASELINE_INSUFFICIENT"] and result["status"] == "partial"


def test_mad_zero():
    result = signal_outcome("resting_hr", current("resting_hr", 55), history("resting_hr", [50] * 28), DAY)
    assert result["baseline_mad"] == 0 and result["z"] is None and result["deviation"] == 5
    assert result["status"] == "partial" and result["reason_codes"] == ["MAD_ZERO"]


def test_partition_change():
    result = signal_outcome("hrv", current("hrv", 50, partition="deviceB"), history("hrv", [60] * 15 + [70] * 15), DAY)
    assert result["valid_nights"] == 0 and result["z"] is None
    unknown = signal_outcome("hrv", current("hrv", 50, partition='{"device_generation":"unknown"}'), [], DAY)
    assert "SOURCE_DEVICE_UNKNOWN" in unknown["quality_flags"]


@pytest.mark.parametrize("metric,value", [("hrv", 0), ("sleep", 0), ("sleep", 86401), ("resting_hr", 29),
                                         ("resting_hr", 231), ("hrv", float("nan")), ("sleep", float("inf"))])
def test_invalid_values(metric, value):
    result = signal_outcome(metric, current(metric, value), [], DAY)
    assert result["status"] == "invalid" and result["value"] is None and result["adverse"] is None


def test_unresolved_and_missing():
    unresolved = replace(current("hrv", None), resolved=False)
    assert signal_outcome("hrv", unresolved, [], DAY)["status"] == "invalid"
    assert signal_outcome("hrv", None, [], DAY)["status"] == "missing"
    assert signal_outcome("hrv", current("hrv", None), [], DAY)["status"] == "missing"


def test_missing_two():
    observations = history("resting_hr", [50] * 5)
    nights = [night_outcome(DAY - timedelta(days=i), observations, []) for i in range(7)]
    result = summary_outcome(nights)
    assert result["value"]["coverage"] == .714 and result["quality_status"] == "limited"
    assert result["value"]["nights_with_data"] == 5 and len(result["value"]["missing_dates"]) == 2
    assert result["status"] == "partial"


@pytest.mark.parametrize("fatigue,illness,expected", [(None, None, None), (7, None, True), (3, "none", False),
                                                     (3, None, None), (None, "possible", True)])
def test_subjective_unknown(fatigue, illness, expected):
    subject = Subjective(datetime(2026, 11, 15, tzinfo=UTC), "1", fatigue, illness)
    result = night_outcome(DAY, [], [subject])["value"]
    assert result["subjective_poor"] is expected and result["discordance"] is None


def test_discordance_and_independent_latest_subjectives():
    observations = history("resting_hr", [48] * 14 + [52] * 14) + [current("resting_hr", 55)]
    earlier = Subjective(datetime(2026, 11, 15, 10, tzinfo=UTC), "1", 7, "none")
    later = Subjective(datetime(2026, 11, 15, 11, tzinfo=UTC), "2", 3, None)
    result = night_outcome(DAY, observations, [later, earlier])["value"]
    assert result["subjective_poor"] is False and result["discordance"] is True
    assert result["fatigue"] == 3 and result["illness"] == "none"
    # One normal measured signal cannot imply the two unknown signals are normal.
    normal = night_outcome(DAY, observations[:-1] + [current("resting_hr", 50)], [earlier])["value"]
    assert normal["discordance"] is None


def test_baseline_window():
    observations = history("hrv", [60] * 6) + [Observation(DAY - timedelta(days=i), "hrv", 70, "deviceA", True, {})
                                               for i in range(15, 23)]
    observations += [Observation(DAY - timedelta(days=60), "hrv", 70, "deviceA", True, {}),
                     Observation(DAY - timedelta(days=61), "hrv", 1, "deviceA", True, {}), current("hrv", 999)]
    result = signal_outcome("hrv", current("hrv", 60), observations, DAY)
    assert result["valid_nights"] == 15 and "BASELINE_STALE" in result["quality_flags"]


def test_latest_revision_and_invalid_history():
    observations = history("hrv", [60] * 15 + [70] * 15)
    observations += [replace(observations[0], value=0), replace(observations[1], resolved=False)]
    result = signal_outcome("hrv", current("hrv", 50), observations, DAY)
    assert result["valid_nights"] == 29 and result["invalid_history_nights"] == 2


def test_threshold_before_rounding():
    baseline = history("resting_hr", [48] * 14 + [52] * 14)
    result = signal_outcome("resting_hr", current("resting_hr", 50 + 1.49999 * 2 / .6745), baseline, DAY)
    assert result["z"] == 1.5 and result["adverse"] is False


def test_compute_seven_dates_and_local_subjective(monkeypatch):
    session = Mock()
    session.scalar.return_value = "America/New_York"
    # This UTC instant is the previous local day, across the fall DST weekend.
    checkin = SimpleNamespace(id=UUID(int=1), version=2, observed_at=datetime(2026, 11, 2, 2, tzinfo=UTC), fatigue=8, illness=None)
    session.scalars.return_value.all.return_value = [checkin]
    seen = []
    def load(_session, start, end):
        seen.append((start, end))
        return []
    monkeypatch.setattr(recovery, "_load_observations", load)
    original = recovery.night_outcome
    captured = []
    def capture(day, observations, subjects):
        captured.append((day, subjects))
        return original(day, observations, subjects)
    monkeypatch.setattr(recovery, "night_outcome", capture)
    result = recovery.compute(session, "w7:2026-11-03")[0]
    assert len(captured) == 7 and seen == [(date(2026, 8, 29), date(2026, 11, 3))]
    assert [(d, len(s)) for d, s in captured if s] == [(date(2026, 11, 1), 1)]
    assert result.value["nights_with_data"] == 0 and len(result.value["missing_dates"]) == 7
    assert result.source_refs["checkins"][0]["version"] == 2
    assert result.window_start.isoformat() == "2026-10-28T04:00:00+00:00"
    assert result.window_end.isoformat() == "2026-11-04T05:00:00+00:00"


@pytest.mark.parametrize("key", ["w14:2026-11-15", "w7:2026-99-01", "night:20261115", "foo"])
def test_invalid_keys(key):
    with pytest.raises(ValueError, match="invalid_subject_key"):
        recovery.compute(Mock(), key)


def test_observation_partition_and_immutable_refs():
    import json

    session = Mock()
    observation = SimpleNamespace(id=UUID(int=1), source_account_id=UUID(int=2), source_revision="revision",
                                  statistic="last_night_average", time_semantics="garmin_hrv_calendar_date",
                                  value=50, source_date=DAY, metric="hrv")
    source = SimpleNamespace(id=UUID(int=3), fields={"device_generation": "documented-v2"},
                             source_kind="garmin_personal", payload_hash="payload", rejected_reason=None)
    unknown = SimpleNamespace(**{**vars(source), "fields": {}, "rejected_reason": "unresolved"})
    raw = SimpleNamespace(sha256="raw-hash")
    session.execute.return_value.all.return_value = [(observation, source, raw), (observation, unknown, raw),
                                                     (observation, None, None)]
    mapped = recovery._load_observations(session, DAY - timedelta(days=60), DAY)
    partition = json.loads(mapped[0].partition)
    assert partition == {"source_account_id": str(UUID(int=2)), "source_kind": "garmin_personal",
                         "statistic": "last_night_average", "definition": "garmin_hrv_calendar_date",
                         "device_generation": "documented-v2"}
    assert mapped[0].resolved and not mapped[1].resolved and not mapped[2].resolved
    assert json.loads(mapped[1].partition)["device_generation"] == "unknown"
    assert json.loads(mapped[2].partition)["source_kind"] == "unknown"
    assert mapped[0].source_refs["source_revision"] == "revision"
    assert mapped[0].source_refs["payload_hash"] == "payload" and mapped[0].source_refs["raw_sha256"] == "raw-hash"
    assert mapped[1].source_refs["source_rejected_reason"] == "unresolved"
    assert mapped[2].source_refs["raw_sha256"] is None
