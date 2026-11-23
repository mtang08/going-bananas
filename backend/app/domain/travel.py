"""Pure travel rules: event categories from calendar records, and flight legs for trip detection."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.local_time import date_in_zone

FLIGHT_CODE = re.compile(r"\b([A-Z0-9]{2})\s?(\d{1,4})\b")
FLIGHT_TO = re.compile(r"(?i)^flight to (?P<dest>.+?)(?:\s*\(|$)")
FLIGHT_ROUTE = re.compile(
    r"^flight:\s*(?P<carrier>[A-Z0-9]{2})\s?(?P<number>\d{1,4})"
    r"\s+from\s+[A-Z]{3}\s+to\s+(?P<dest>[A-Z]{3})\b",
    re.IGNORECASE | re.ASCII,
)
FLIGHT_TITLE = re.compile(r"(?i)^flight\b")
LODGING_TITLE = re.compile(r"(?i)\b(stay at|hotel|inn|resort|suites?|airbnb|check-in)\b")
GROUND_TITLE = re.compile(r"(?i)\b(train|rail|amtrak|bus|ferry|car rental|rental car)\b")
LODGING_MIN = timedelta(hours=20)
LABEL_MAX = 120
CONNECT_MAX = timedelta(hours=24)
OPEN_TRIP_MAX = timedelta(days=30)
_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class Leg:
    event_id: str
    dep_at: datetime
    arr_at: datetime
    dep_tz: str
    arr_tz: str
    label: str | None
    confidence: str


def _known(name: str | None) -> str | None:
    if not name:
        return None
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return name


def zone_names(start_tz: str | None, end_tz: str | None, home: ZoneInfo) -> tuple[str, str]:
    """Departure and arrival zone names: a missing or unknown side uses the other side, then home."""
    start, end = _known(start_tz), _known(end_tz)
    return start or end or home.key, end or start or home.key


def timezone_basis(
    start_tz: str | None, end_tz: str | None
) -> Literal["calendar_endpoints", "calendar_display", "fallback"]:
    """Identify what Google supplied before applying any display fallback."""
    start, end = _known(start_tz), _known(end_tz)
    if start is None or end is None:
        return "fallback"
    return "calendar_display" if start == end else "calendar_endpoints"


def make_leg(
    event_id: str,
    dep_at: datetime,
    arr_at: datetime,
    start_tz: str | None,
    end_tz: str | None,
    label: str | None,
    flight_confidence: str | None,
    home: ZoneInfo,
) -> Leg:
    """A flight leg with low confidence when endpoint zones give no independent evidence."""
    dep_tz, arr_tz = zone_names(start_tz, end_tz, home)
    confidence = "low" if dep_tz == arr_tz else flight_confidence or "medium"
    return Leg(event_id, dep_at, arr_at, dep_tz, arr_tz, label, confidence)


def parse_flight(summary: str | None) -> tuple[str | None, str | None]:
    """(flight code such as "ZZ 101", destination label) from a flight title; None where nothing matches."""
    if not summary:
        return None, None
    title = summary.strip()
    route = FLIGHT_ROUTE.match(title)
    if route:
        return f"{route['carrier'].upper()} {route['number']}", route["dest"].upper()
    code = FLIGHT_CODE.search(title)
    destination = FLIGHT_TO.match(title)
    label = destination.group("dest").strip()[:LABEL_MAX] if destination else None
    return (f"{code.group(1)} {code.group(2)}" if code else None), (label or None)


def _instant(value: Any) -> datetime:
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _offsets_differ(record: dict[str, Any], home: ZoneInfo) -> bool:
    start_tz, end_tz = zone_names(record.get("start_tz"), record.get("end_tz"), home)
    if start_tz == end_tz:
        return False
    start, end = _instant(record["start_at"]), _instant(record["end_at"])
    return start.astimezone(ZoneInfo(start_tz)).utcoffset() != end.astimezone(ZoneInfo(end_tz)).utcoffset()


def categorize(record: dict[str, Any], home: ZoneInfo) -> tuple[str, str | None]:
    """(category, flight_confidence) by the first matching rule of design §6. `record` is a contracts §3 record."""
    title = (record.get("summary") or "").strip()
    gmail = record.get("event_type") == "fromGmail"
    timed = not record.get("all_day")
    mentions_flight = "flight" in title.lower()
    has_code = mentions_flight and (FLIGHT_CODE.search(title) is not None or FLIGHT_ROUTE.match(title) is not None)
    if record.get("event_type") == "outOfOffice":
        return "out_of_office", None
    if (
        gmail
        and timed
        and (
            FLIGHT_TITLE.match(title)
            or has_code
            or (record.get("transparency") == "transparent" and _offsets_differ(record, home))
        )
    ):
        return "flight", "high"
    if gmail and LODGING_TITLE.search(title):
        if not timed or _instant(record["end_at"]) - _instant(record["start_at"]) >= LODGING_MIN:
            return "lodging", None
    if gmail and GROUND_TITLE.search(title):
        return "ground_travel", None
    if gmail:
        return "reservation", None
    if timed and mentions_flight and (has_code or _offsets_differ(record, home)):
        return "flight", "medium"
    return "other", None


@dataclass(frozen=True)
class Stop:
    label: str | None
    tz: str
    arrive_date: date


@dataclass(frozen=True)
class TripCandidate:
    start_date: date
    end_date: date | None
    destination_label: str | None
    destination_tz: str
    confidence: str
    stops: tuple[Stop, ...]
    legs: tuple[Leg, ...]


def _away(instant: datetime, tz_name: str, home: ZoneInfo) -> bool:
    return instant.astimezone(ZoneInfo(tz_name)).utcoffset() != instant.astimezone(home).utcoffset()


def _arrives_away(leg: Leg, home: ZoneInfo) -> bool | None:
    if leg.dep_tz == leg.arr_tz:
        return None
    return _away(leg.arr_at, leg.arr_tz, home)


def _departs_away(leg: Leg, home: ZoneInfo) -> bool | None:
    if leg.dep_tz == leg.arr_tz:
        return None
    return _away(leg.dep_at, leg.dep_tz, home)


def _journeys(legs: Sequence[Leg]) -> list[list[Leg]]:
    journeys: list[list[Leg]] = []
    for leg in sorted(legs, key=lambda leg: (leg.dep_at, leg.event_id)):
        if journeys and timedelta(0) <= leg.dep_at - journeys[-1][-1].arr_at <= CONNECT_MAX:
            journeys[-1].append(leg)
        else:
            journeys.append([leg])
    return journeys


def _stop(leg: Leg) -> Stop:
    return Stop(leg.label, leg.arr_tz, date_in_zone(leg.arr_at, ZoneInfo(leg.arr_tz)))


def _candidate(legs: list[Leg], stops: list[Stop], home: ZoneInfo, *, closed: bool) -> TripCandidate:
    start = date_in_zone(legs[0].dep_at, ZoneInfo(legs[0].dep_tz))
    end = max(start, date_in_zone(legs[-1].arr_at, ZoneInfo(legs[-1].arr_tz))) if closed else None
    confidence = min((leg.confidence for leg in legs), key=_RANK.__getitem__)
    if not any(_arrives_away(leg, home) for leg in legs):
        confidence = min(confidence, "medium", key=_RANK.__getitem__)
    if not closed or any(leg.dep_tz == leg.arr_tz for leg in legs):
        confidence = "low"
    return TripCandidate(start, end, stops[0].label, stops[0].tz, confidence, tuple(stops), tuple(legs))


def detect_trips(legs: Sequence[Leg], home: ZoneInfo) -> list[TripCandidate]:
    """Single-pass trip detection over flight journeys (design §7), in start order."""
    trips: list[TripCandidate] = []
    open_legs: list[Leg] = []
    stops: list[Stop] = []
    for journey in _journeys(legs):
        departure = date_in_zone(journey[0].dep_at, home)
        if open_legs and departure - date_in_zone(open_legs[-1].arr_at, home) > OPEN_TRIP_MAX:
            trips.append(_candidate(open_legs, stops, home, closed=False))
            open_legs, stops = [], []
        arrival_away = _arrives_away(journey[-1], home)
        if open_legs:
            open_legs.extend(journey)
            if arrival_away:
                stops.append(_stop(journey[-1]))
            else:
                trips.append(_candidate(open_legs, stops, home, closed=True))
                open_legs, stops = [], []
            continue
        if arrival_away is False:
            if _departs_away(journey[0], home):
                continue
            away_stops = [_stop(leg) for leg in journey[:-1] if _arrives_away(leg, home)]
            if away_stops:
                trips.append(_candidate(journey, away_stops, home, closed=True))
                continue
        open_legs, stops = list(journey), [_stop(journey[-1])]
    if open_legs:
        trips.append(_candidate(open_legs, stops, home, closed=False))
    return trips
