from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.adapters.google_calendar import TOKEN_FILE
from app.api import travel
from app.models import ImportBatch
from app.travel_models import GcalEvent

HEADERS = {"X-Local-Request": "1"}
MANUAL = {
    "start_date": "2027-02-10",
    "end_date": "2027-02-13",
    "destination_tz": "America/New_York",
    "destination_label": "Synthetic cabin",
    "gym_access": "none",
    "day_availability": [
        {"date": "2027-02-12", "availability": "reduced"},
        {"date": "2027-02-11", "availability": "unavailable"},
    ],
}


def test_manual_trip_lifecycle(api_client, monkeypatch):
    client = api_client(travel.router)
    monkeypatch.setattr(travel, "athlete_today", lambda _: date(2026, 11, 22))
    response = client.post("/api/v1/trips", json=MANUAL, headers=HEADERS)
    assert response.status_code == 201, response.text
    trip = response.json()["data"]
    assert (trip["source"], trip["status"], trip["edited"], trip["legs"], trip["confidence"]) == (
        "manual",
        "confirmed",
        True,
        [],
        None,
    )
    assert trip["day_availability"] == list(reversed(MANUAL["day_availability"]))
    path = "/api/v1/trips/" + trip["id"]

    def edit(body, version=1):
        return client.patch(path, json={"expected_version": version, **body}, headers=HEADERS)

    for invalid in [
        {"status": "pending"},
        {"end_date": None},
        {"accept_detected": True},
        {"day_availability": None},
        {"start_date": None},
        {"destination_tz": None},
    ]:
        assert edit(invalid).status_code == 422
    changed = edit({"end_date": "2027-02-11", "status": "dismissed"})
    assert changed.status_code == 200
    assert changed.json()["data"]["day_availability"] == [MANUAL["day_availability"][1]]
    assert edit({"status": "confirmed"}).status_code == 409
    assert client.get("/api/v1/trips").json()["data"]["items"] == []
    assert len(client.get("/api/v1/trips?status=dismissed").json()["data"]["items"]) == 1
    assert edit({"status": "confirmed"}, 2).status_code == 200
    assert len(client.get("/api/v1/trips?start=2027-02-11&end=2027-02-11").json()["data"]["items"]) == 1
    assert client.get("/api/v1/trips?start=2027-02-12&end=2027-02-14").json()["data"]["items"] == []
    assert client.get("/api/v1/trips?status=unknown").status_code == 422


@pytest.mark.parametrize(
    "change",
    [
        {"start_date": "2027-02-14"},
        {"end_date": None},
        {"destination_tz": "Unknown/Nowhere"},
        {"day_availability": [{"date": "2027-02-15", "availability": "normal"}]},
        {"day_availability": [MANUAL["day_availability"][0]] * 2},
        {"running_access": "unknown"},
    ],
)
def test_invalid_manual_trip(api_client, change):
    client = api_client(travel.router)
    assert client.post("/api/v1/trips", json=MANUAL | change, headers=HEADERS).status_code == 422


def test_status_uses_connection_file(api_client, monkeypatch, tmp_path):
    monkeypatch.setattr(travel, "settings", SimpleNamespace(private_dir=tmp_path))
    client = api_client(travel.router)
    status = client.get("/api/v1/google-calendar/status").json()["data"]
    assert status == {
        "connected": False,
        "last_sync": None,
        "last_success_at": None,
        "window": {"days_back": 30, "days_ahead": 180},
    }
    (tmp_path / TOKEN_FILE).touch()
    assert client.get("/api/v1/google-calendar/status").json()["data"]["connected"]


NOW = datetime(2026, 11, 22, 21, tzinfo=UTC)


def _event(session, gid: str, *, start_at=None, start_date=None, category="other", removed=False) -> GcalEvent:
    all_day = start_date is not None
    row = GcalEvent(
        google_event_id=gid,
        event_type="default",
        google_status="confirmed",
        summary=f"Synthetic {gid}",
        location_codes=[],
        all_day=all_day,
        start_at=None if all_day else start_at,
        end_at=None if all_day else start_at + timedelta(hours=1),
        start_date=start_date,
        end_date=start_date + timedelta(days=1) if all_day else None,
        start_tz=None if all_day else "America/New_York",
        end_tz=None if all_day else "America/New_York",
        transparency="opaque",
        response_status=None,
        busy=True,
        flight_code=None,
        destination_label=None,
        category=category,
        auto_category=category,
        category_source="auto",
        flight_confidence=None,
        content_hash=gid.ljust(64, "0")[:64],
        first_seen_at=NOW,
        changed_at=NOW,
        removed_at=NOW if removed else None,
        version=1,
    )
    session.add(row)
    return row


def test_events_use_home_dates_and_show_removals(api_client, session_factory, profile_factory):
    with session_factory() as session:
        profile_factory(session)
        _event(session, "out", start_at=datetime(2026, 12, 3, 3, 30, tzinfo=UTC), category="flight")
        _event(session, "hotel", start_date=date(2026, 12, 3), category="lodging")
        _event(session, "work", start_at=datetime(2026, 12, 3, 15, tzinfo=UTC), category="work", removed=True)
        _event(session, "other", start_at=datetime(2026, 12, 4, 15, tzinfo=UTC))
        _event(session, "outside", start_date=date(2026, 12, 10))
        session.commit()
    client = api_client(travel.router)
    path = "/api/v1/google-calendar/events?start=2026-12-02&end=2026-12-04"

    def events(suffix):
        response = client.get(path + suffix)
        assert response.status_code == 200
        return response.json()["data"]["items"]

    rows = events("")
    assert [e["summary"] for e in rows] == ["Synthetic out", "Synthetic hotel", "Synthetic other"]
    assert rows[0]["local_date"] == "2026-12-02"
    assert [e["category"] for e in events("&category=travel")] == ["flight", "lodging"]
    assert events("&include_removed=true&category=work")[0]["removed"]
    assert client.get(path + "&category=unknown").status_code == 422
    assert client.get("/api/v1/google-calendar/events?start=2026-12-04&end=2026-12-02").status_code == 422


def test_status_distinguishes_last_attempt_from_last_success(api_client, session_factory, monkeypatch, tmp_path):
    monkeypatch.setattr(travel, "settings", SimpleNamespace(private_dir=tmp_path))
    with session_factory() as session:
        for index, (kind, status) in enumerate(
            [("google_calendar", "complete"), ("google_calendar", "failed"), ("garmin_api", "complete")]
        ):
            started = NOW + timedelta(hours=index)
            session.add(
                ImportBatch(
                    source_kind=kind,
                    status=status,
                    adapter_version="synthetic",
                    started_at=started,
                    finished_at=started + timedelta(minutes=1),
                    counters={},
                    error_code="gcal_rate_limited" if status == "failed" else None,
                )
            )
        session.commit()
    status = api_client(travel.router).get("/api/v1/google-calendar/status").json()["data"]
    assert status["last_sync"]["error_code"] == "gcal_rate_limited"
    assert datetime.fromisoformat(status["last_success_at"]) == NOW + timedelta(minutes=1)
