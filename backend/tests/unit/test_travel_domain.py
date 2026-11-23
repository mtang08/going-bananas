import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.adapters.google_calendar import to_record
from app.domain.travel import Leg, categorize, detect_trips, make_leg, parse_flight, timezone_basis, zone_names

HOME = ZoneInfo("America/New_York")
NY, LA = "America/New_York", "America/Los_Angeles"


def _record(
    summary,
    *,
    event_type="fromGmail",
    start="2026-12-03T13:05:00+00:00",
    end="2026-12-03T19:30:00+00:00",
    start_tz=NY,
    end_tz=LA,
    all_day=False,
    transparency="transparent",
):
    record = {
        "transparency": transparency,
        "summary": summary,
        "event_type": event_type,
        "all_day": all_day,
        "start_at": start,
        "end_at": end,
        "start_date": None,
        "end_date": None,
        "start_tz": start_tz,
        "end_tz": end_tz,
    }
    if all_day:
        record.update(
            start_at=None, end_at=None, start_date="2026-12-03", end_date="2026-12-07", start_tz=None, end_tz=None
        )
    return record


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gcal"


def _fixture_legs(name):
    fixture = json.loads((FIXTURES / name).read_text())
    home = ZoneInfo(fixture["home_timezone"])
    legs = []
    for page in fixture["pages"]:
        for item in page["items"]:
            record = to_record(item)
            if record is None or record["all_day"] or record["response_status"] == "declined":
                continue
            category, confidence = categorize(record, home)
            if category == "flight":
                legs.append(
                    make_leg(
                        record["google_event_id"],
                        datetime.fromisoformat(record["start_at"]),
                        datetime.fromisoformat(record["end_at"]),
                        record["start_tz"],
                        record["end_tz"],
                        parse_flight(record["summary"])[1],
                        confidence,
                        home,
                    )
                )
    return fixture, home, legs


def _summary(trips):
    return [
        {
            "start_date": trip.start_date.isoformat(),
            "end_date": trip.end_date.isoformat() if trip.end_date else None,
            "destination_tz": trip.destination_tz,
            "destination_label": trip.destination_label,
            "confidence": trip.confidence,
            "leg_ids": [leg.event_id for leg in trip.legs],
        }
        for trip in trips
    ]


def _leg(event_id, dep, arr, dep_tz=NY, arr_tz=LA, label="Synthetic City", confidence="high"):
    return Leg(event_id, datetime.fromisoformat(dep), datetime.fromisoformat(arr), dep_tz, arr_tz, label, confidence)


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (_record("Out of office", event_type="outOfOffice"), ("out_of_office", None)),
        (_record("Flight to Synthetic City (ZZ 101)", end_tz=NY), ("flight", "high")),
        (_record("Flight to Synthetic City", start_tz=None, end_tz=None), ("flight", "high")),
        (_record("Synthetic Air ZZ 101 flight", end_tz=NY), ("flight", "high")),
        (_record("Synthetic reservation"), ("flight", "high")),
        (_record("Synthetic reservation", transparency="opaque"), ("reservation", None)),
        (_record("Stay at Synthetic Inn", all_day=True), ("lodging", None)),
        (
            _record("Synthetic Hotel", start="2026-12-03T20:00:00+00:00", end="2026-12-04T17:00:00+00:00", end_tz=NY),
            ("lodging", None),
        ),
        (
            _record(
                "Synthetic Hotel dinner", start="2026-12-03T23:00:00+00:00", end="2026-12-04T01:00:00+00:00", end_tz=NY
            ),
            ("reservation", None),
        ),
        (_record("Train to Synthetic Park", end_tz=NY), ("ground_travel", None)),
        (
            _record("Flight: ZZ 101 from XAA to XBB", event_type="default", start_tz=None, end_tz=None),
            ("flight", "medium"),
        ),
        (
            _record("flight: zz101 from xaa to xbb", event_type="default", start_tz=None, end_tz=None),
            ("flight", "medium"),
        ),
        (_record("Flight school open day", event_type="default", end_tz=NY), ("other", None)),
        (_record("Flight: ZZ 101 from XAA to XBB", event_type="default", all_day=True), ("other", None)),
        (_record("Synthetic voyage", start_tz=None, end_tz=None), ("reservation", None)),
        (_record("Synthetic voyage", end_tz=None), ("reservation", None)),
        (_record("Synthetic voyage", start_tz="America/Phoenix", end_tz="America/Denver"), ("reservation", None)),
        (
            _record(
                "Synthetic voyage",
                start="2026-07-03T15:00:00+00:00",
                end="2026-07-03T17:00:00+00:00",
                start_tz="America/Phoenix",
                end_tz="America/Denver",
            ),
            ("flight", "high"),
        ),
    ],
)
def test_categorize_rules(record, expected):
    assert categorize(record, HOME) == expected


def test_identical_zones_through_dst_change_do_not_classify_unknown_titles_as_flights():
    record = _record(
        "Synthetic reservation", start="2026-11-01T05:15:00+00:00", end="2026-11-01T06:15:00+00:00", end_tz=NY
    )
    assert categorize(record, HOME) == ("reservation", None)


def test_categorize_accepts_datetime_instants():
    record = _record("Synthetic transparent reservation")
    record.update(start_at=datetime.fromisoformat(record["start_at"]), end_at=datetime.fromisoformat(record["end_at"]))
    assert categorize(record, HOME) == ("flight", "high")


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Flight to Synthetic City (ZZ 101)", ("ZZ 101", "Synthetic City")),
        ("Flight to Synthetic City", (None, "Synthetic City")),
        ("flight to synthetic city (ZZ101)", ("ZZ 101", "synthetic city")),
        ("Synthetic Air ZZ 7 flight", ("ZZ 7", None)),
        ("Flight: ZZ 101 from XAA to XBB", ("ZZ 101", "XBB")),
        ("flight: zz101 from xaa to xbb", ("ZZ 101", "XBB")),
        ("Flight to " + "A" * 200, (None, "A" * 120)),
        (None, (None, None)),
    ],
)
def test_parse_flight(title, expected):
    assert parse_flight(title) == expected


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (NY, LA, (NY, LA)),
        (LA, LA, (LA, LA)),
        (None, LA, (LA, LA)),
        (NY, None, (NY, NY)),
        (None, None, (NY, NY)),
        ("Mars/Olympus", LA, (LA, LA)),
    ],
)
def test_zone_names_fall_back(start, end, expected):
    assert zone_names(start, end, HOME) == expected


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (NY, LA, "calendar_endpoints"),
        (LA, LA, "calendar_display"),
        (None, LA, "fallback"),
        ("Mars/Olympus", "Mars/Olympus", "fallback"),
    ],
)
def test_timezone_basis_preserves_the_original_zone_quality(start, end, expected):
    assert timezone_basis(start, end) == expected


@pytest.mark.parametrize(
    ("start", "end", "classification", "expected"),
    [
        (NY, LA, "high", "high"),
        (NY, LA, None, "medium"),
        (NY, None, "high", "low"),
        (LA, LA, "high", "low"),
        (None, None, "medium", "low"),
    ],
)
def test_make_leg_confidence(start, end, classification, expected):
    dep, arr = (datetime.fromisoformat(value) for value in ("2026-12-01T13:00:00+00:00", "2026-12-01T20:00:00+00:00"))
    leg = make_leg("evt", dep, arr, start, end, "Synthetic City", classification, HOME)
    assert leg.confidence == expected
    assert (leg.dep_tz, leg.arr_tz) == zone_names(start, end, HOME)


@pytest.mark.parametrize("name", ["trips_cross_zone.json", "trips_same_zone.json"])
def test_detect_trips_fixtures(name):
    fixture, home, legs = _fixture_legs(name)
    expected = fixture["expect"]["trips"]
    assert _summary(detect_trips(legs, home)) == expected
    assert _summary(detect_trips(list(reversed(legs)), home)) == expected


def test_multi_city_trip_keeps_stops():
    _, home, legs = _fixture_legs("trips_cross_zone.json")
    connected, multi_city, *_ = detect_trips(legs, home)
    assert [(s.label, s.tz, s.arrive_date.isoformat()) for s in connected.stops] == [
        ("Synthetic City", LA, "2026-12-03")
    ]
    assert [(s.label, s.tz, s.arrive_date.isoformat()) for s in multi_city.stops] == [
        ("Synthetic Coast", LA, "2027-01-10"),
        ("Synthetic Isle", "Pacific/Honolulu", "2027-01-14"),
    ]


@pytest.mark.parametrize(
    ("dep", "expected_stops"),
    [
        ("2026-12-02T20:00:00+00:00", ["Synthetic Isle"]),
        ("2026-12-02T20:01:00+00:00", ["Synthetic City", "Synthetic Isle"]),
    ],
)
def test_connection_window_is_24_hours(dep, expected_stops):
    first = _leg("evt-a", "2026-12-01T13:00:00+00:00", "2026-12-01T20:00:00+00:00")
    second = _leg("evt-b", dep, "2026-12-03T02:15:00+00:00", LA, "Pacific/Honolulu", "Synthetic Isle")
    (trip,) = detect_trips([first, second], HOME)
    assert [stop.label for stop in trip.stops] == expected_stops
    assert trip.legs == (first, second)
    assert trip.end_date is None and trip.confidence == "low"


def test_distinct_zone_connecting_return_without_outbound_is_ignored():
    depart = _leg("evt-a", "2026-12-01T13:00:00+00:00", "2026-12-01T15:00:00+00:00", LA, "America/Denver")
    arrive = _leg("evt-b", "2026-12-01T16:00:00+00:00", "2026-12-01T19:00:00+00:00", "America/Denver", NY)
    assert detect_trips([depart, arrive], HOME) == []


def test_uncertain_outbound_can_pair_with_credible_return():
    outbound = _leg("evt-a", "2026-12-01T13:00:00+00:00", "2026-12-01T20:00:00+00:00", LA, LA)
    back = _leg("evt-b", "2026-12-05T13:00:00+00:00", "2026-12-05T20:00:00+00:00", LA, NY)
    (trip,) = detect_trips([outbound, back], HOME)
    assert trip.end_date.isoformat() == "2026-12-05"
    assert trip.confidence == "low"


@pytest.mark.parametrize(
    ("dep_date", "end_dates"),
    [
        ("2027-01-31", ["2027-01-31"]),
        ("2027-02-01", [None, None]),
    ],
)
def test_uncertain_journeys_pair_within_thirty_home_dates(dep_date, end_dates):
    outbound = _leg("evt-a", "2027-01-01T15:00:00+00:00", "2027-01-01T16:00:00+00:00", LA, LA)
    back = _leg("evt-b", dep_date + "T20:00:00+00:00", dep_date + "T22:00:00+00:00", LA, LA)
    trips = detect_trips([outbound, back], HOME)
    assert [trip["end_date"] for trip in _summary(trips)] == end_dates
    assert all(trip.confidence == "low" for trip in trips)


def test_detect_trips_empty():
    assert detect_trips([], HOME) == []
