from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_server_error_redacts_canary():
    from app.db import get_session

    def broken_session():
        raise RuntimeError("secret-canary-value")

    app.dependency_overrides[get_session] = broken_session
    try:
        response = TestClient(app, raise_server_exceptions=False).get("/api/v1/profile")
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert "secret-canary-value" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_legacy_routes_are_removed():
    paths = set(app.openapi()["paths"])
    removed = {
        "/api/v1/summary",
        "/api/v1/recovery",
        "/api/v1/checkins",
        "/api/v1/manual-sessions",
        "/api/v1/plans",
        "/api/v1/conflicts",
        "/api/v1/imports",
        "/api/v1/context",
        "/api/v1/weekly-summary",
        "/api/v1/weekly-snapshots",
        "/api/v1/coach/daily",
        "/api/v1/coach/weekly",
        "/api/v1/coach/context",
        "/api/v1/coach/agent/context",
        "/api/v1/strength/years",
        "/api/v1/history/checkins",
        "/api/v1/metrics/explain/{result_id}",
    }
    assert removed.isdisjoint(paths)
    assert {
        "/api/v1/profile",
        "/api/v1/activities",
        "/api/v1/metrics/long-runs",
        "/api/v1/strength/history/{workout_id}/rpe",
    } <= paths
    assert TestClient(app).get("/api/v1/summary").status_code == 404
