import importlib
import importlib.metadata
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from app.services.timezone import athlete_today, athlete_tz, local_date

NY = ZoneInfo("America/New_York")


class FakeSession:
    def __init__(self, name):
        self.name = name

    def scalar(self, _stmt):
        return self.name


def test_a10_dst_fall_back_local_date():
    first = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    second = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    assert first != second
    assert local_date(first, NY) == date(2026, 11, 1)
    assert local_date(second, NY) == date(2026, 11, 1)
    assert local_date(datetime(2026, 11, 3, 4, 50, tzinfo=UTC), NY) == date(2026, 11, 2)


def test_local_date_rejects_naive_instant():
    with pytest.raises(ValueError, match="^naive_instant$"):
        local_date(datetime(2026, 11, 1, 5, 30), NY)


def test_athlete_tz_defaults_without_profile():
    assert athlete_tz(FakeSession(None)).key == "America/New_York"


def test_athlete_tz_uses_profile_timezone():
    assert athlete_tz(FakeSession("Europe/London")).key == "Europe/London"


def test_athlete_tz_invalid_name_raises():
    with pytest.raises(ZoneInfoNotFoundError):
        athlete_tz(FakeSession("Mars/Olympus"))


def test_athlete_today_uses_profile_zone():
    now = datetime(2026, 11, 3, 4, 50, tzinfo=UTC)
    assert athlete_today(FakeSession(None), now) == date(2026, 11, 2)
    assert athlete_today(FakeSession("Europe/London"), now) == date(2026, 11, 3)


def test_garmin_fit_sdk_pinned():
    assert importlib.metadata.version("garmin-fit-sdk") == "21.221.0"
    assert importlib.import_module("garmin_fit_sdk") is not None
