from datetime import date
from types import SimpleNamespace

import pytest

from app.adapters.google_calendar import TOKEN_FILE
from app.api import travel

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
