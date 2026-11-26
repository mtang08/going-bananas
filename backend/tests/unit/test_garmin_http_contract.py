"""Exercises the current Python adapter and official client's HTTP contract offline."""

import base64
import json
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from app.adapters.garmin.personal import GarminConfigurationError, GarminPersonalSource, GarminRemoteError

TOKEN = "/personalapitoken-service/personal-api/personal-api-key/token"
BINARY = "/download-service/files/activity/7"
SEARCH = "/activitylist-service/activities/search/activities"


def test_current_http_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("GARMIN_API_KEY", "synthetic")
    monkeypatch.setenv("GARMIN_PERSONAL_API_BASE_URL", "https://fixture.invalid")
    monkeypatch.setenv("NO_PROXY", "*")
    tokens = []
    requests_seen = []
    binary = b"PK\x03\x04\x00\xff"
    page = json.dumps([{"activityId": 7}]).encode()
    replies = iter(
        [
            (401, b"expired", {}),
            (200, binary, {}),
            (401, b"expired", {}),
            (401, b"expired", {}),
            (429, b"secret-response", {"Retry-After": "37"}),
            (200, page, {}),
            (200, page, {}),
        ]
    )

    def send(self, request, **kwargs):
        parsed = urlsplit(request.url)
        assert parsed.netloc == "fixture.invalid"
        response = requests.Response()
        response.request = request
        response.url = request.url
        if parsed.path == TOKEN:
            assert request.method == "POST"
            assert request.headers["Authorization"] == "ApiKey synthetic"
            body = base64.urlsafe_b64encode(json.dumps({"exp": 4102444800, "i": len(tokens)}).encode()).rstrip(b"=")
            token = b"test." + body + b".fixture"
            tokens.append(token.decode())
            response.status_code, response._content = 200, token
        else:
            assert request.method == "GET"
            assert request.headers["Authorization"] == "Bearer " + tokens[-1]
            if parsed.path == BINARY:
                assert "application/zip" in request.headers["Accept"]
            requests_seen.append((parsed.path, parse_qs(parsed.query)))
            response.status_code, response._content, headers = next(replies)
            response.headers.update(headers)
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    with GarminPersonalSource(tmp_path / "unused", tmp_path / "cache" / "bearer.json") as source:
        assert source.download_activity("7") == binary
        assert len(tokens) == 2
        with pytest.raises(GarminRemoteError) as unauthorized:
            source.download_activity("7")
        assert unauthorized.value.status_code == 401 and len(tokens) == 3
        with pytest.raises(GarminRemoteError) as limited:
            source.download_activity("7")
        assert limited.value.status_code == 429 and limited.value.response.headers["Retry-After"] == "37"
        assert "secret-response" not in str(limited.value) and len(tokens) == 3
        with pytest.raises(GarminConfigurationError, match="repeated_activity_page"):
            list(source.pages(date(2026, 1, 1), date(2026, 1, 2), page_size=1))
    assert [path for path, _ in requests_seen] == [BINARY] * 5 + [SEARCH] * 2
    assert [query for _, query in requests_seen[-2:]] == [
        {"start": [str(n)], "limit": ["1"], "startDate": ["2026-01-01"], "endDate": ["2026-01-02"]} for n in (0, 1)
    ]
