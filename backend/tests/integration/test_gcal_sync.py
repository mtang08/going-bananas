"""Google Calendar sync on guarded synthetic state."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Event, Lock, Thread
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from app.adapters.google_calendar import TOKEN_FILE, GcalRemoteError, content_hash, to_record
from app.errors import AppError
from app.models import ImportBatch
from app.services import gcal_sync
from app.services.gcal_sync import sync_window, upsert_events
from app.travel_models import GcalEvent, Trip, TripLeg

HOME = ZoneInfo("America/New_York")
TODAY = date(2026, 11, 22)
NOW = datetime(2026, 11, 22, 15, tzinfo=UTC)
LATER = datetime(2026, 11, 23, 15, tzinfo=UTC)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gcal"
WINDOW = sync_window(HOME, TODAY)


def _fixture(name="basic_pages.json"):
    return json.loads((FIXTURES / name).read_text())


def _records(name="basic_pages.json"):
    pages = _fixture(name)["pages"]
    return [record for page in pages for item in page["items"] if (record := to_record(item)) is not None]


def _edited(record, **changes):
    changed = {**record, **changes}
    changed["content_hash"] = content_hash(changed)
    return changed


def _rows(session):
    return {row.google_event_id: row for row in session.scalars(select(GcalEvent))}


@pytest.fixture
def gsession(session_factory):
    with session_factory(expire_on_commit=False) as session:
        for model in (TripLeg, Trip, GcalEvent):
            session.execute(delete(model))
        session.execute(delete(ImportBatch).where(ImportBatch.source_kind == "google_calendar"))
        yield session


def test_sync_window_spans_home_midnights():
    assert WINDOW.start == date(2026, 10, 23)
    assert WINDOW.end == date(2027, 5, 21)
    assert WINDOW.time_min.isoformat() == "2026-10-23T00:00:00-04:00"
    assert WINDOW.time_max.isoformat() == "2027-05-22T00:00:00-04:00"


def test_sync_file_lock_serializes_overlapping_calls(tmp_path):
    entered = Event()
    release = Event()
    second_entered = Event()
    order = []
    guard = Lock()

    def first():
        with gcal_sync._sync_lock(tmp_path):
            with guard:
                order.append("first")
            entered.set()
            assert release.wait(timeout=5)

    def second():
        assert entered.wait(timeout=5)
        with gcal_sync._sync_lock(tmp_path):
            with guard:
                order.append("second")
            second_entered.set()

    one, two = Thread(target=first), Thread(target=second)
    one.start()
    two.start()
    assert entered.wait(timeout=5)
    assert not second_entered.wait(timeout=0.05)
    release.set()
    one.join(timeout=5)
    two.join(timeout=5)
    assert not one.is_alive() and not two.is_alive()
    assert order == ["first", "second"]


def test_upsert_inserts_with_auto_category(gsession):
    counts = upsert_events(gsession, _records(), WINDOW, NOW)
    rows = _rows(gsession)
    assert counts == {"fetched": 5, "created": 5, "changed": 0, "unchanged": 0, "removed": 0, "restored": 0}
    flight = rows["evt-flight-1"]
    assert (flight.category, flight.auto_category, flight.category_source) == ("flight", "flight", "auto")
    assert (flight.flight_confidence, flight.flight_code, flight.destination_label) == (
        "high",
        "ZZ 101",
        "Synthetic City",
    )
    assert flight.start_at == datetime(2026, 12, 3, 13, 5, tzinfo=UTC)
    assert flight.location_codes == ["JFK"]
    assert flight.version == 1 and flight.first_seen_at == flight.changed_at == NOW
    lodging = rows["evt-lodging-1"]
    assert lodging.category == "lodging" and lodging.start_date == date(2026, 12, 3) and lodging.start_at is None
    assert rows["evt-ooo-1"].category == "out_of_office"
    assert rows["evt-declined-1"].busy is False and rows["evt-declined-1"].category == "other"
    assert {key: row.category for key, row in rows.items()} == _fixture()["expect"]["categories"]


def test_upsert_identical_sync_writes_nothing(gsession):
    records = _records()
    upsert_events(gsession, records, WINDOW, NOW)
    gsession.flush()
    counts = upsert_events(gsession, records, WINDOW, LATER)
    assert counts == {"fetched": 5, "created": 0, "changed": 0, "unchanged": 5, "removed": 0, "restored": 0}
    assert all(row.version == 1 and row.changed_at == NOW for row in _rows(gsession).values())


def test_upsert_change_follows_auto_unless_athlete_chose(gsession):
    records = _records()
    upsert_events(gsession, records, WINDOW, NOW)
    rows = _rows(gsession)
    rows["evt-lodging-1"].category = "social"
    rows["evt-lodging-1"].category_source = "athlete"
    gsession.flush()
    changes = {
        "evt-flight-1": {"summary": "Flight to Synthetic Town (ZZ 105)"},
        "evt-lodging-1": {"summary": "Stay at Synthetic Lodge"},
        "evt-declined-1": {"summary": "Flight to Synthetic City (ZZ 9)"},
    }
    changed_records = [
        _edited(record, **changes[record["google_event_id"]]) if record["google_event_id"] in changes else record
        for record in records
    ]
    counts = upsert_events(gsession, changed_records, WINDOW, LATER)
    rows = _rows(gsession)
    assert counts == {"fetched": 5, "created": 0, "changed": 3, "unchanged": 2, "removed": 0, "restored": 0}
    flight = rows["evt-flight-1"]
    assert flight.version == 2 and flight.changed_at == LATER and flight.destination_label == "Synthetic Town"
    assert flight.flight_code == "ZZ 105" and flight.first_seen_at == NOW
    assert rows["evt-lodging-1"].category == "social" and rows["evt-lodging-1"].auto_category == "lodging"
    assert rows["evt-lodging-1"].version == 2
    declined = rows["evt-declined-1"]
    assert declined.auto_category == declined.category == "flight" and declined.flight_confidence == "medium"


def _event(gsession, google_event_id, *, all_day=False, start_at=None, start_date=None):
    gsession.add(
        GcalEvent(
            google_event_id=google_event_id,
            event_type="default",
            google_status="confirmed",
            summary=None,
            location_codes=[],
            all_day=all_day,
            start_at=start_at,
            end_at=None if all_day else start_at + (LATER - NOW),
            start_date=start_date,
            end_date=start_date + timedelta(days=3) if all_day else None,
            start_tz=None if all_day else "America/New_York",
            end_tz=None if all_day else "America/New_York",
            transparency="opaque",
            response_status=None,
            busy=True,
            category="other",
            auto_category="other",
            category_source="auto",
            content_hash="0" * 64,
            first_seen_at=NOW,
            changed_at=NOW,
            version=1,
        )
    )


def test_upsert_removes_absent_in_window_and_restores(gsession):
    records = _records()
    upsert_events(gsession, records, WINDOW, NOW)
    _event(gsession, "evt-old", start_at=datetime(2026, 1, 1, 15, tzinfo=UTC))
    _event(gsession, "evt-edge", all_day=True, start_date=date(2026, 10, 20))
    gsession.flush()
    remaining = [record for record in records if record["google_event_id"] not in {"evt-focus-1", "evt-lodging-1"}]
    counts = upsert_events(gsession, remaining, WINDOW, LATER)
    rows = _rows(gsession)
    assert counts == {"fetched": 3, "created": 0, "changed": 0, "unchanged": 3, "removed": 2, "restored": 0}
    assert rows["evt-focus-1"].removed_at == rows["evt-lodging-1"].removed_at == LATER
    assert rows["evt-focus-1"].version == rows["evt-lodging-1"].version == 2
    assert rows["evt-old"].removed_at is None and rows["evt-old"].version == 1
    assert rows["evt-edge"].removed_at is None and rows["evt-edge"].version == 1
    restored = upsert_events(gsession, records, WINDOW, LATER)
    rows = _rows(gsession)
    assert restored == {"fetched": 5, "created": 0, "changed": 0, "unchanged": 3, "removed": 0, "restored": 2}
    assert rows["evt-focus-1"].removed_at is rows["evt-lodging-1"].removed_at is None
    assert rows["evt-focus-1"].version == rows["evt-lodging-1"].version == 3


@pytest.fixture
def synced(gsession, tmp_path, monkeypatch, metrics_disabled, profile_factory):
    profile_factory(gsession)
    gsession.flush()
    (tmp_path / TOKEN_FILE).write_text("{}", encoding="utf-8")
    calls = []

    def fetch(http, time_min, time_max):
        calls.append((http, time_min, time_max))
        return [item for page in _fixture()["pages"] for item in page["items"]]

    class SyntheticHttp:
        closed = False

        def close(self):
            self.closed = True

    http = SyntheticHttp()
    monkeypatch.setattr(gcal_sync, "authorized_session", lambda private_dir: http)
    monkeypatch.setattr(gcal_sync, "fetch_events", fetch)
    return gsession, tmp_path, calls, http


def _batches(session):
    return list(
        session.scalars(
            select(ImportBatch).where(ImportBatch.source_kind == "google_calendar").order_by(ImportBatch.started_at)
        )
    )


def test_run_sync_stores_events_detects_trips_and_records_batch(synced):
    session, private_dir, calls, http = synced
    result = gcal_sync.run_sync(session, private_dir, NOW)
    assert result["sync"]["window"] == {"start": "2026-10-23", "end": "2027-05-21"}
    assert result["sync"]["counters"] == {
        "fetched": 5,
        "created": 5,
        "changed": 0,
        "unchanged": 0,
        "removed": 0,
        "restored": 0,
    }
    assert result["sync"]["started_at"] == NOW.isoformat()
    assert result["trips"] == {"created": 1, "updated": 0, "flagged": 0, "deleted": 0}
    assert len(calls) == 1
    http, time_min, time_max = calls[0]
    assert calls[0][0] is http and http.closed
    assert time_min.isoformat() == "2026-10-23T00:00:00-04:00"
    assert time_max.isoformat() == "2027-05-22T00:00:00-04:00"
    batches = _batches(session)
    assert len(batches) == 1
    batch = batches[0]
    assert batch.status == "complete" and batch.adapter_version == "gcal-v1" and batch.error_code is None
    assert batch.started_at == NOW
    assert batch.counters == {
        **result["sync"]["counters"],
        "trips_created": 1,
        "trips_updated": 0,
        "trips_flagged": 0,
        "trips_deleted": 0,
    }
    assert len(_rows(session)) == 5
    assert len(list(session.scalars(select(Trip)))) == 1


def test_run_sync_failure_records_batch_and_keeps_events(synced, monkeypatch):
    session, private_dir, _, _ = synced
    gcal_sync.run_sync(session, private_dir, NOW)

    def limited(http, time_min, time_max):
        raise GcalRemoteError("gcal_rate_limited", 429, "7")

    monkeypatch.setattr(gcal_sync, "fetch_events", limited)
    with pytest.raises(AppError) as caught:
        gcal_sync.run_sync(session, private_dir, LATER)
    assert (caught.value.code, caught.value.status_code, caught.value.message) == (
        "gcal_rate_limited",
        503,
        "Google Calendar is rate limiting requests. Try again shortly.",
    )
    failed = _batches(session)[-1]
    assert failed.status == "failed" and failed.error_code == "gcal_rate_limited" and failed.counters == {}
    assert all(row.removed_at is None and row.version == 1 for row in _rows(session).values())


def test_run_sync_requires_token(synced):
    session, private_dir, calls, _ = synced
    (private_dir / TOKEN_FILE).unlink()
    with pytest.raises(AppError) as caught:
        gcal_sync.run_sync(session, private_dir, NOW)
    assert (caught.value.code, caught.value.status_code, caught.value.message) == (
        "gcal_not_connected",
        409,
        "Google Calendar is not connected. Run calendar-connect.",
    )
    assert _batches(session) == [] and calls == []


def test_run_sync_is_all_or_nothing_and_retry_succeeds(synced, monkeypatch):
    session, private_dir, _, _ = synced
    reconcile = gcal_sync.reconcile_trips

    def fail_after_upsert(session, home):
        raise RuntimeError("synthetic reconcile failure")

    monkeypatch.setattr(gcal_sync, "reconcile_trips", fail_after_upsert)
    with pytest.raises(RuntimeError, match="synthetic reconcile failure"):
        gcal_sync.run_sync(session, private_dir, NOW)
    assert _rows(session) == {}
    assert _batches(session) == []

    monkeypatch.setattr(gcal_sync, "reconcile_trips", reconcile)
    result = gcal_sync.run_sync(session, private_dir, LATER)
    assert result["sync"]["counters"]["created"] == 5
    assert len(_rows(session)) == 5 and len(_batches(session)) == 1
