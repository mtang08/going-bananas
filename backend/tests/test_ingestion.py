import io
import json
import tarfile
from datetime import UTC, date, datetime

import pytest

from app.adapters.garmin.normalize import InvalidRecord, parse_activity
from app.adapters.garmin.personal import GarminConfigurationError, GarminPersonalSource, GarminRemoteError
from app.services.backup import BackupError, validate_backup
from app.services.sync import catchup_window, retry_delay, store_raw


def test_activity_time_and_sport_are_canonical():
    activity = parse_activity({"activityId": 18, "startTimeGMT": "2026-01-01T01:00:00Z",
        "activityType": {"typeKey": "running"}, "distance": 1609.344,
        "elapsedDuration": 700, "movingDuration": 600})
    assert activity.local_date == "2025-12-31"
    assert activity.source_time == "2026-01-01T01:00:00Z"
    assert activity.sport == "running"
    assert activity.elapsed_s == 700
    assert activity.moving_s == 600
    assert activity.start_at == datetime(2026, 1, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("patch,reason", [
    ({"distance": -1}, "invalid_distance"),
    ({"distance": float("nan")}, "invalid_distance"),
    ({"startTimeGMT": None, "startTimeLocal": "2026-11-01T01:30:00"}, "ambiguous_start_time"),
])
def test_invalid_values_are_rejected(patch, reason):
    record = {"activityId": 1, "startTimeGMT": "2026-03-08T07:00:00Z",
              "activityType": {"typeKey": "running"}, "distance": 0}
    record.update(patch)
    with pytest.raises(InvalidRecord, match=reason):
        parse_activity(record)


def test_same_raw_bytes_are_immutable(tmp_path):
    first = store_raw(tmp_path, b'{"activityId":1}')
    second = store_raw(tmp_path, b'{"activityId":1}')
    assert first == second
    assert (tmp_path / second[1]).read_bytes() == b'{"activityId":1}'


def test_retry_after_delta_and_http_date():
    class Response:
        headers = {"Retry-After": "15"}
    class RateLimited(Exception):
        status_code = 429
        response = Response()
    assert retry_delay(RateLimited(), 1) == 15
    Response.headers = {"Retry-After": "Tue, 10 Nov 2026 12:01:00 GMT"}
    assert retry_delay(RateLimited(), 1, datetime(2026, 11, 10, 12, tzinfo=UTC)) == 60


def test_repeated_page_stops_before_unbounded_fetch(tmp_path):
    source = GarminPersonalSource(tmp_path / "key", tmp_path / "token")
    calls = []

    def repeated(start, limit, first, last):
        calls.append(start)
        return [{"activityId": n} for n in range(limit)]

    source.search_page = repeated
    with pytest.raises(GarminConfigurationError, match="repeated_activity_page"):
        list(source.pages(date(2026, 11, 1), date(2026, 11, 2), page_size=2))
    assert calls == [0, 2]


def test_corrupt_backup_fails_before_restore(tmp_path):
    archive = tmp_path / "backup.tar.gz"
    manifest = {"version": 1, "contains_credentials": False,
                "files": {"database.pgdump": {"sha256": "0" * 64, "bytes": 4}}}
    with tarfile.open(archive, "w:gz") as tar:
        for name, payload in [("manifest.json", json.dumps(manifest).encode()),
                              ("database.pgdump", b"data")]:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    with pytest.raises(BackupError, match="backup_checksum_mismatch"):
        validate_backup(archive)


def test_backup_traversal_rejected(tmp_path):
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(BackupError, match="unsafe_backup_entry"):
        validate_backup(archive)


def test_catchup_covers_missed_days_and_chunks_long_gap():
    today = date(2026, 11, 10)
    assert catchup_window(today, date(2026, 10, 21), 14) == (date(2026, 10, 8), today)
    start, end = catchup_window(today, date(2024, 1, 1), 14)
    assert start == date(2023, 12, 19)
    assert (end - start).days == 365
    assert end < today


def test_official_client_retry_after_header_is_preserved_without_body(tmp_path):
    from garmin_personal_api import HttpError

    source = GarminPersonalSource(tmp_path / "key", tmp_path / "token")

    class Response:
        headers = {"Retry-After": "37"}

    def failed_request():
        source._capture_response(Response())
        raise HttpError(status_code=429, method="GET", url="https://example.invalid",
                        response_text="SECRET_RESPONSE_BODY")

    with pytest.raises(GarminRemoteError) as exc:
        source._call(failed_request)
    assert retry_delay(exc.value, 1) == 37
    assert "SECRET_RESPONSE_BODY" not in str(exc.value)
