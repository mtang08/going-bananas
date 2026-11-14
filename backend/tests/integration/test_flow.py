from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_server_error_redacts_canary():
    from app.db import get_session
    def broken_session():
        raise RuntimeError('secret-canary-value')
    app.dependency_overrides[get_session] = broken_session
    try:
        response = TestClient(app, raise_server_exceptions=False).get('/api/v1/profile')
        assert response.status_code == 500
        assert response.json()['error']['code'] == 'internal_error'
        assert 'secret-canary-value' not in response.text
    finally:
        app.dependency_overrides.clear()
