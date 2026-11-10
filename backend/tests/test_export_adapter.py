"""Synthetic archive and conversion checks; never contains athlete data."""

import json
from zipfile import ZipFile, ZipInfo

import pytest

from app.adapters.garmin.export import ExportError, normalize_export_activity, safe_inventory, scan_activities


def _activity(activity_id: int = 7) -> dict:
    return {
        "activityId": activity_id, "userProfileId": 17, "startTimeGmt": 1_756_000_000_000,
        "activityType": "track_running", "distance": 525_000,
        "elapsedDuration": 1_900_000, "movingDuration": 1_800_000, "avgHr": 145,
        "avgRunCadence": 82,
    }


def test_activity_conversion_preserves_only_verified_fields():
    converted = normalize_export_activity(_activity())
    assert converted["distance"] == 5250
    assert converted["elapsedDuration"] == 1900
    assert converted["movingDuration"] == 1800
    assert converted["averageHR"] == 145
    assert converted["activityType"] == {"typeKey": "track_running"}
    assert "averageRunningCadenceInStepsPerMinute" not in converted
    assert converted["startTimeGMT"].endswith("+00:00")


def test_scan_activity_member_and_owner(tmp_path):
    path = tmp_path / "sample.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("folder/summarizedActivities.json",
                         json.dumps([{"summarizedActivitiesExport": [_activity(), _activity(8)]}]))
    with ZipFile(path) as archive:
        scan = scan_activities(archive)
    assert len(scan.activities) == 2
    assert scan.activities[0].owner == "17"
    assert scan.activities[0].original["avgRunCadence"] == 82


@pytest.mark.parametrize("name", ["../escape.json", "/absolute.json", "x\\bad.json", "C:/drive.json"])
def test_unsafe_archive_path_rejected(tmp_path, name):
    path = tmp_path / "unsafe.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr(name, "{}")
    with ZipFile(path) as archive:
        with pytest.raises(ExportError, match="unsafe_archive_path"):
            safe_inventory(archive)


def test_symlink_archive_entry_rejected(tmp_path):
    path = tmp_path / "link.zip"
    info = ZipInfo("link.json")
    info.external_attr = (0o120777 << 16)
    with ZipFile(path, "w") as archive:
        archive.writestr(info, "target")
    with ZipFile(path) as archive:
        with pytest.raises(ExportError, match="unsafe_archive_entry"):
            safe_inventory(archive)


def test_mixed_owners_rejected(tmp_path):
    path = tmp_path / "mixed.zip"
    second = _activity(8)
    second["userProfileId"] = 18
    with ZipFile(path, "w") as archive:
        archive.writestr("summarizedActivities.json",
                         json.dumps([{"summarizedActivitiesExport": [_activity(), second]}]))
    with ZipFile(path) as archive:
        with pytest.raises(ExportError, match="mixed_activity_owner"):
            scan_activities(archive)
