"""Trip reconciliation, edits, and views on guarded synthetic state."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from app.services.trips import reconcile_trips
from app.travel_models import GcalEvent, Trip, TripLeg

HOME = ZoneInfo("America/New_York")
NY, LA = "America/New_York", "America/Los_Angeles"
NOW = datetime(2026, 11, 22, 15, tzinfo=UTC)
LATER = datetime(2026, 11, 23, 15, tzinfo=UTC)
NONE = {"created": 0, "updated": 0, "flagged": 0, "deleted": 0}


def _flight(session, google_id, dep, arr, dep_tz=NY, arr_tz=LA, label="Synthetic City", **overrides):
    fields = dict(
        google_event_id=google_id,
        event_type="fromGmail",
        google_status="confirmed",
        summary=f"Flight to {label} (ZZ 1)",
        all_day=False,
        start_at=datetime.fromisoformat(dep),
        end_at=datetime.fromisoformat(arr),
        start_tz=dep_tz,
        end_tz=arr_tz,
        transparency="opaque",
        busy=True,
        category="flight",
        auto_category="flight",
        category_source="auto",
        flight_confidence="high",
        flight_code="ZZ 1",
        destination_label=label,
        content_hash=hashlib.sha256(google_id.encode()).hexdigest(),
        first_seen_at=NOW,
        changed_at=NOW,
    )
    fields.update(overrides)
    row = GcalEvent(**fields)
    session.add(row)
    session.flush()
    return row


def _round_trip(session):
    out = _flight(session, "evt-out", "2026-12-03T13:05:00+00:00", "2026-12-03T19:30:00+00:00")
    ret = _flight(
        session, "evt-ret", "2026-12-08T06:30:00+00:00", "2026-12-08T12:05:00+00:00", LA, NY, "Synthetic Home"
    )
    return out, ret


def _move(session, row, dep, arr):
    row.start_at, row.end_at = datetime.fromisoformat(dep), datetime.fromisoformat(arr)
    row.content_hash = hashlib.sha256(f"{row.google_event_id}:{dep}".encode()).hexdigest()
    row.version += 1
    session.flush()


def _legs(session, trip):
    rows = session.scalars(select(TripLeg).where(TripLeg.trip_id == trip.id).order_by(TripLeg.seq))
    return [(row.gcal_event_id, row.leg_hash, row.seq) for row in rows]


def _trips(session):
    return list(session.scalars(select(Trip).order_by(Trip.start_date, Trip.id)))


@pytest.fixture
def tsession(session_factory):
    with session_factory(expire_on_commit=False) as session:
        for model in (TripLeg, Trip, GcalEvent):
            session.execute(delete(model))
        yield session


def test_pending_trip_follows_return_and_ignores_declined(tsession):
    out, ret = _round_trip(tsession)
    _flight(tsession, "skip", "2026-12-12T12:00:00Z", "2026-12-12T16:00:00Z", response_status="declined")
    assert reconcile_trips(tsession, HOME) == NONE | {"created": 1}
    (trip,) = _trips(tsession)
    assert trip.status == "pending" and trip.destination_tz == LA
    assert _legs(tsession, trip) == [(out.id, out.content_hash, 0), (ret.id, ret.content_hash, 1)]
    assert reconcile_trips(tsession, HOME) == NONE
    _move(tsession, ret, "2026-12-09T06:30:00Z", "2026-12-09T12:05:00Z")
    assert reconcile_trips(tsession, HOME) == NONE | {"updated": 1}
    assert trip.end_date == date(2026, 12, 9) and trip.version == 2


@pytest.mark.parametrize("accept", [True, False])
def test_review_preserves_athlete_edits(tsession, accept):
    from app.services.trips import patch_trip

    _, ret = _round_trip(tsession)
    reconcile_trips(tsession, HOME)
    (trip,) = _trips(tsession)
    patch_trip(
        tsession,
        trip.id,
        {"expected_version": 1, "destination_label": "My stay", "status": "confirmed", "gym_access": "none"},
        NOW,
    )
    _move(tsession, ret, "2026-12-09T06:30:00Z", "2026-12-09T12:05:00Z")
    assert reconcile_trips(tsession, HOME) == NONE | {"flagged": 1}
    assert trip.destination_label == "My stay" and trip.end_date == date(2026, 12, 8)
    assert trip.review_reason == "source_changed" and trip.detected["end_date"] == "2026-12-09"
    assert reconcile_trips(tsession, HOME) == NONE
    patch_trip(
        tsession, trip.id, {"expected_version": trip.version, "accept_detected": accept, "status": "confirmed"}, LATER
    )
    assert trip.destination_label == ("Synthetic City" if accept else "My stay")
    assert trip.gym_access == "none" and reconcile_trips(tsession, HOME) == NONE


@pytest.mark.parametrize("status", ["pending", "confirmed", "dismissed"])
def test_source_removal_and_manual_trip(tsession, status):
    from app.services.trips import create_manual_trip, patch_trip

    manual = create_manual_trip(
        tsession, dict(start_date=date(2026, 12, 2), end_date=date(2026, 12, 9), destination_tz=LA), NOW
    )
    out, ret = _round_trip(tsession)
    reconcile_trips(tsession, HOME)
    trip = next(t for t in _trips(tsession) if t.id != manual.id)
    trip.status = status
    out.removed_at = ret.removed_at = NOW
    tsession.flush()
    counts = reconcile_trips(tsession, HOME)
    if status == "pending":
        assert counts == NONE | {"deleted": 1} and _trips(tsession) == [manual]
    elif status == "confirmed":
        assert counts == NONE | {"flagged": 1}
        assert trip.review_reason == "source_removed" and trip.detected == {}
        patch_trip(tsession, trip.id, {"expected_version": trip.version, "status": "confirmed"}, LATER)
    else:
        assert counts == NONE and trip.status == "dismissed"
    assert reconcile_trips(tsession, HOME) == NONE and manual.version == 1


def test_matching_default_and_gmail_legs_retain_trip_after_a_copy_disappears(tsession):
    from app.services.trips import trip_view

    out, ret = _round_trip(tsession)
    out.start_tz = out.end_tz = NY
    duplicate = _flight(
        tsession, "copy", out.start_at.isoformat(), out.end_at.isoformat(), None, None, event_type="default"
    )
    assert reconcile_trips(tsession, HOME) == NONE | {"created": 1}
    (trip,) = _trips(tsession)
    assert [row[0] for row in _legs(tsession, trip)] == [out.id, ret.id]
    assert trip_view(tsession, trip, HOME)["legs"][0]["timezone_basis"] == "calendar_display"
    out.removed_at = NOW
    tsession.flush()
    assert reconcile_trips(tsession, HOME) == NONE | {"updated": 1}
    assert [row[0] for row in _legs(tsession, trip)] == [duplicate.id, ret.id]
    assert trip_view(tsession, trip, HOME)["legs"][0]["timezone_basis"] == "fallback"
    trip.status = "dismissed"
    out.removed_at = None
    tsession.flush()
    assert reconcile_trips(tsession, HOME) == NONE
    assert _trips(tsession) == [trip] and trip.status == "dismissed"


def test_newly_connected_itineraries_reuse_earliest_trip(tsession):
    out, ret = _round_trip(tsession)
    out2 = _flight(tsession, "out-b", "2026-12-14T13:00:00Z", "2026-12-14T16:00:00Z", NY, "America/Chicago")
    ret2 = _flight(tsession, "ret-b", "2026-12-18T20:00:00Z", "2026-12-18T23:00:00Z", "America/Chicago", NY)
    assert reconcile_trips(tsession, HOME) == NONE | {"created": 2}
    first = _trips(tsession)[0]
    ret.removed_at = NOW
    tsession.flush()
    assert reconcile_trips(tsession, HOME) == NONE | {"updated": 1, "deleted": 1}
    assert _trips(tsession) == [first]
    assert [row[0] for row in _legs(tsession, first)] == [out.id, out2.id, ret2.id]
