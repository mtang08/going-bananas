from datetime import date
from types import SimpleNamespace

from app.api import sync
from app.models import CoverageInterval

HEADERS = {"X-Local-Request": "1"}
TODAY = date(2026, 11, 20)


def test_sync_now_uses_each_datasets_last_complete_coverage(api_client, session_factory, monkeypatch):
    # Exercise the real-mode route using the isolated integration database.
    monkeypatch.setattr(sync, "settings", SimpleNamespace(app_mode="real"))
    monkeypatch.setattr("app.services.sync.athlete_today", lambda _session: TODAY)
    with session_factory() as session:
        for dataset, end, status in [
            ("activities", TODAY, "complete"),
            ("sleep", date(2026, 11, 19), "complete"),
            ("resting_hr", date(2026, 11, 17), "complete"),
            ("resting_hr", date(2026, 11, 19), "partial"),
        ]:
            session.add(
                CoverageInterval(
                    dataset=dataset,
                    start_date=date(2026, 11, 14),
                    end_date=end,
                    status=status,
                    fully_enumerated=True,
                )
            )
        session.commit()

    client = api_client(sync.router)
    response = client.post("/api/v1/sync", json={}, headers=HEADERS)
    assert response.status_code == 202, response.text
    jobs = response.json()["data"]["jobs"]
    assert {job["dataset"]: (job["start_date"], job["end_date"]) for job in jobs} == {
        "activities": ("2026-11-20", "2026-11-20"),
        "sleep": ("2026-11-19", "2026-11-20"),
        "resting_hr": ("2026-11-17", "2026-11-20"),
        "hrv": ("2026-11-14", "2026-11-20"),
    }
    repeated = client.post("/api/v1/sync", json={}, headers=HEADERS)
    assert [job["id"] for job in repeated.json()["data"]["jobs"]] == [job["id"] for job in jobs]


def test_explicit_sync_dates_apply_to_every_dataset(api_client, monkeypatch):
    monkeypatch.setattr(sync, "settings", SimpleNamespace(app_mode="real"))
    client = api_client(sync.router)
    body = {"start_date": "2026-10-11", "end_date": "2026-10-12"}
    response = client.post("/api/v1/sync", json=body, headers=HEADERS)
    assert response.status_code == 202, response.text
    jobs = response.json()["data"]["jobs"]
    assert len(jobs) == 4
    assert all({key: job[key] for key in body} == body for job in jobs)
