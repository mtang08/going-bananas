import json
from datetime import date
from zipfile import ZipFile

import pytest

from app.adapters.garmin.export_recovery import scan_recovery


def _archive(tmp_path, members):
    path = tmp_path / "export.zip"
    with ZipFile(path, "w") as archive:
        for name, rows in members.items():
            archive.writestr(name, json.dumps(rows))
    return path


def test_verified_recovery_shapes_and_original_rows(tmp_path):
    sleep = {"calendarDate": "2026-01-02", "sleepStartTimestampGMT": "2026-01-02T01:00:00Z",
             "sleepEndTimestampGMT": "2026-01-02T09:00:00Z", "awakeSleepSeconds": 900,
             "deepSleepSeconds": 100, "lightSleepSeconds": 200, "remSleepSeconds": 300,
             "napList": [{"durationSeconds": 3600}]}
    uds = {"userProfilePK": 42, "calendarDate": "2026-01-02", "restingHeartRate": 53,
           "currentDayRestingHeartRate": 54, "minHeartRate": 45}
    health = {"calendarDate": "2026-01-02", "metrics": [
        {"type": "HRV", "value": 41.5}, {"type": "HR", "value": 57.0}]}
    path = _archive(tmp_path, {
        "Wellness/2026-01-01_2026-01-03_42_sleepData.json": [sleep, {"retro": False}],
        "Wellness/UDSFile_2026-01-01_2026-01-03.json": [uds],
        "Wellness/2026-01-01_2026-01-03_42_healthStatusData.json": [health],
    })
    with ZipFile(path) as archive:
        result = scan_recovery(archive)

    by_metric = {item.metric: item for item in result.observations}
    assert set(by_metric) == {"sleep", "resting_hr", "hrv"}
    assert by_metric["sleep"].value == 8 * 3600 - 900
    assert by_metric["sleep"].source_date == date(2026, 1, 2)
    assert by_metric["sleep"].statistic == "main_sleep_duration"
    assert by_metric["sleep"].unit == "s"
    assert by_metric["sleep"].payload == sleep
    assert by_metric["resting_hr"].value == 53
    assert by_metric["resting_hr"].source_field == "restingHeartRate"
    assert by_metric["hrv"].value == 41.5
    assert by_metric["hrv"].statistic == "last_night_average"
    assert by_metric["hrv"].unit == "ms"
    assert {item.account_owner for item in result.observations} == {"42"}
    assert result.skipped == {"sleep_incomplete_or_invalid": 1,
                              "health_status_other_metrics_unsupported": 1}


def test_missing_and_invalid_values_are_omitted_not_zero(tmp_path):
    path = _archive(tmp_path, {
        "UDSFile_2026-01-01_2026-01-03.json": [
            {"userProfilePK": 42, "calendarDate": "2026-01-02", "minHeartRate": 40},
            {"userProfilePK": 42, "calendarDate": "2026-01-03", "restingHeartRate": True},
            {"userProfilePK": 42, "calendarDate": "2026-01-04", "restingHeartRate": 0}],
        "2026-01-01_2026-01-03_42_healthStatusData.json": [
            {"calendarDate": "2026-01-02", "metrics": [{"type": "HRV", "value": 35},
                                                     {"type": "HRV", "value": 36}]},
            {"calendarDate": "2026-01-03", "metrics": [{"type": "HRV", "value": 0}]}],
        "2026-01-01_2026-01-03_42_sleepData.json": [
            {"calendarDate": "2026-01-02", "sleepStartTimestampGMT": "2026-01-02T09:00:00Z",
             "sleepEndTimestampGMT": "2026-01-02T01:00:00Z", "awakeSleepSeconds": 0},
            {"calendarDate": "2026-01-03", "sleepStartTimestampGMT": "2026-01-03T01:00:00Z",
             "sleepEndTimestampGMT": "2026-01-03T02:00:00Z", "awakeSleepSeconds": 3600}],
    })
    with ZipFile(path) as archive:
        result = scan_recovery(archive)
    assert not result.observations
    assert result.skipped == {"uds_missing_or_invalid_resting_hr": 3,
                              "health_status_missing_or_invalid_hrv": 2,
                              "sleep_incomplete_or_invalid": 2}


def test_supported_member_requires_json_array(tmp_path):
    path = _archive(tmp_path, {"UDSFile_2026-01-01_2026-01-03.json": {"calendarDate": "2026-01-02"}})
    with ZipFile(path) as archive, pytest.raises(ValueError, match="invalid_recovery_array"):
        scan_recovery(archive)
