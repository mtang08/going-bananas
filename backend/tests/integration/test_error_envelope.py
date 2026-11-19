import dataclasses
from uuid import uuid4

from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)
H = {"x-local-request": "1", "content-type": "application/json"}


def test_sync_requires_real_mode():
    response = client.post("/api/v1/sync", json={}, headers=H)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "real_mode_required"


def test_unknown_sync_job():
    response = client.get(f"/api/v1/sync/jobs/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


def test_router_405_uses_envelope():
    response = client.delete("/api/v1/no-such-route", headers=H)
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert response.json()["error"]["retryable"] is False
    assert "X-Request-ID" in response.headers


def test_frontend_fallbacks(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, frontend_dist=tmp_path / "missing"))
    response = client.get("/some/page")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "frontend_not_built"
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, frontend_dist=tmp_path))
    response = client.get("/missing.js")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_api_404_unchanged():
    response = client.get("/api/v1/no-such-route")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
