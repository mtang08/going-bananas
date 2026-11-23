"""Calendar events, trips, and legs bump data_revision without metric refresh scopes."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select

from app.models import AppState
from app.services import derived
from app.travel_models import GcalEvent, Trip, TripLeg

NOW = datetime(2026, 11, 22, 15, tzinfo=UTC)


def _revision(session):
    return session.scalar(select(AppState.data_revision).where(AppState.id == 1))


def test_travel_writes_bump_revision_without_date_scopes(session_factory, monkeypatch):
    calls = []
    monkeypatch.setattr(derived, "refresh_scopes", lambda session, scopes: calls.append(set(scopes)))
    with session_factory(expire_on_commit=False) as session:
        before = _revision(session)
        event = GcalEvent(
            google_event_id="evt-refresh-1",
            event_type="fromGmail",
            google_status="confirmed",
            all_day=False,
            start_at=NOW,
            end_at=NOW,
            transparency="opaque",
            busy=True,
            category="flight",
            auto_category="flight",
            category_source="auto",
            content_hash="a" * 64,
            first_seen_at=NOW,
            changed_at=NOW,
        )
        session.add(event)
        session.flush()
        assert session.info.get("metrics_scopes") == {"revision"}
        trip = Trip(
            status="pending",
            start_date=date(2026, 11, 22),
            destination_tz="America/Los_Angeles",
            confidence="high",
            detected={},
        )
        session.add(trip)
        session.flush()
        session.add(TripLeg(trip_id=trip.id, gcal_event_id=event.id, leg_hash="a" * 64, seq=0))
        session.flush()
        assert session.info.get("metrics_scopes") == {"revision"}
        session.commit()
        assert _revision(session) == before + 1

        event.removed_at = NOW
        event.version += 1
        trip.status, trip.review_reason = "needs_review", "source_removed"
        session.flush()
        assert session.info.get("metrics_scopes") == {"revision"}
        session.commit()
        assert _revision(session) == before + 2
    assert calls == []
