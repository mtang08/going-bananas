import hashlib
import json
import stat
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import requests
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import AuthorizedSession

from app.adapters import google_calendar
from app.adapters.google_calendar import (
    CLIENT_FILE,
    EVENTS_URL,
    FETCH_FIELDS,
    SCOPES,
    TOKEN_FILE,
    GcalError,
    GcalRemoteError,
    authorized_session,
    connect_flow,
    content_hash,
    fetch_events,
    list_calendars,
    mask_title,
    to_record,
    write_token,
)

FIXTURE = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "gcal" / "basic_pages.json").read_text())
ITEMS = {item["id"]: item for page in FIXTURE["pages"] for item in page["items"]}
RECORD_KEYS = {
    "google_event_id",
    "event_type",
    "google_status",
    "summary",
    "location_codes",
    "all_day",
    "start_at",
    "end_at",
    "start_date",
    "end_date",
    "start_tz",
    "end_tz",
    "transparency",
    "response_status",
    "busy",
    "google_updated_at",
    "content_hash",
}


def _token(private_dir, *, expiry="2999-01-01T00:00:00Z", scopes=SCOPES, mode=0o600):
    private_dir.mkdir(mode=0o700, exist_ok=True)
    path = private_dir / TOKEN_FILE
    info = {
        "token": "synthetic-access",
        "refresh_token": "synthetic-refresh",
        "client_id": "synthetic.apps.example.invalid",
        "client_secret": "synthetic-secret",
        "token_uri": "https://oauth2.example.invalid/token",
        "scopes": list(scopes),
        "expiry": expiry,
    }
    path.write_text(json.dumps(info), encoding="utf-8")
    path.chmod(mode)
    return path


class FakeCredentials:
    def __init__(self, refresh_token="synthetic-refresh", granted_scopes=list(SCOPES)):
        self.refresh_token = refresh_token
        self.granted_scopes = granted_scopes

    def to_json(self):
        return json.dumps({"token": "synthetic-access", "refresh_token": self.refresh_token})


def _fake_flow(monkeypatch, credentials):
    calls = {}

    class FakeFlow:
        def run_local_server(self, **options):
            calls["run"] = options
            if prompt := options.get("authorization_prompt_message"):
                print(prompt.format(url="https://authorization.example.invalid"))
            return credentials

    def from_client_secrets_file(path, scopes, **kwargs):
        calls["init"] = (path, scopes, kwargs)
        return FakeFlow()

    monkeypatch.setattr(
        google_calendar, "InstalledAppFlow", SimpleNamespace(from_client_secrets_file=from_client_secrets_file)
    )
    return calls


class FakeResponse:
    def __init__(self, status_code=200, body=None, headers=None):
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class FakeHttp:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {}), timeout))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


WINDOW = (
    datetime(2026, 10, 23, tzinfo=ZoneInfo("America/New_York")),
    datetime(2027, 5, 22, tzinfo=ZoneInfo("America/New_York")),
)


def test_to_record_projects_allowlisted_fields():
    record = to_record(ITEMS["evt-flight-1"])
    assert set(record) == RECORD_KEYS
    assert len(record.pop("content_hash")) == 64
    assert record == {
        "google_event_id": "evt-flight-1",
        "event_type": "fromGmail",
        "google_status": "confirmed",
        "summary": "Flight to Synthetic City (ZZ 101)",
        "location_codes": ["JFK"],
        "all_day": False,
        "start_at": "2026-12-03T13:05:00+00:00",
        "end_at": "2026-12-03T19:30:00+00:00",
        "start_date": None,
        "end_date": None,
        "start_tz": "America/New_York",
        "end_tz": "America/Los_Angeles",
        "transparency": "opaque",
        "response_status": "accepted",
        "busy": True,
        "google_updated_at": "2026-11-20T10:00:00Z",
    }


def test_to_record_drops_private_fields():
    private = (
        "Confirmation",
        "ZZCONF1",
        "ZZROOM7",
        "example.invalid",
        "Terminal",
        "Example Way",
        "htmlLink",
        "organizer",
        "colleague",
    )
    for item in ITEMS.values():
        if (record := to_record(item)) is not None:
            assert set(record) == RECORD_KEYS
            assert not any(text in json.dumps(record) for text in private)


def test_to_record_all_day_declined_and_transparent():
    lodging = to_record(ITEMS["evt-lodging-1"])
    assert lodging["all_day"]
    assert (lodging["start_date"], lodging["end_date"]) == ("2026-12-03", "2026-12-07")
    assert lodging["start_at"] is lodging["end_at"] is lodging["start_tz"] is None
    assert lodging["transparency"] == "transparent"
    assert lodging["busy"] is False
    assert lodging["location_codes"] == []
    declined = to_record(ITEMS["evt-declined-1"])
    assert declined["response_status"] == "declined"
    assert declined["busy"] is False
    assert declined["start_tz"] is declined["end_tz"] is None
    assert declined["start_at"] == "2026-11-24T19:00:00+00:00"
    focus = to_record(ITEMS["evt-focus-1"])
    assert (focus["event_type"], focus["busy"]) == ("focusTime", False)
    ooo = to_record(ITEMS["evt-ooo-1"])
    assert (ooo["event_type"], ooo["busy"]) == ("outOfOffice", True)


def test_to_record_skips_cancelled_and_incomplete():
    assert all(to_record(ITEMS[event_id]) is None for event_id in FIXTURE["expect"]["skipped"])


@pytest.mark.parametrize(
    "item",
    [
        {"status": "confirmed"},
        {"id": "x", "start": {"dateTime": "2026-12-03T08:05:00"}, "end": {"dateTime": "2026-12-03T09:05:00"}},
        {"id": "y", "start": {"date": "2026-13-40"}, "end": {"date": "2026-12-04"}},
        {**ITEMS["evt-flight-1"], "attendees": ["private@example.invalid"]},
        {**ITEMS["evt-flight-1"], "start": ["private"]},
    ],
)
def test_to_record_rejects_malformed_items(item):
    with pytest.raises(GcalError, match="^gcal_invalid_response$"):
        to_record(item)


def test_content_hash_tracks_projected_fields_only():
    item = ITEMS["evt-flight-1"]
    record = to_record(item)
    body = {key: value for key, value in record.items() if key not in ("content_hash", "google_updated_at")}
    data = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = hashlib.sha256(data.encode()).hexdigest()
    assert record["content_hash"] == expected == content_hash(record)
    assert to_record({**item, "description": "distinct"})["content_hash"] == expected
    assert to_record({**item, "updated": "2026-12-03T13:05:00+00:00"})["content_hash"] == expected
    assert to_record({**item, "summary": "Flight to Synthetic Town (ZZ 105)"})["content_hash"] != expected


@pytest.mark.parametrize(
    ("title", "masked"),
    [
        ("Flight to San Francisco (UA 123)", "Flight to <X> (<AA> <N>)"),
        ("Flight to Synthetic City (ZZ 101)", "Flight to <X> (<AA> <N>)"),
        ("Stay at Synthetic Inn", "Stay at <X>"),
        ("JFK Terminal 4", "<IATA> <X> <N>"),
        ("Lunch with athlete@example.invalid", "<X>"),
        ("Train: Synthetic Central → Synthetic Park", "Train: <X> → <X>"),
        ("Out of office", "Out of office"),
        ("ZZ 101 departs", "<X> <N> <X>"),
        ("See https://example.invalid/x now", "<X>"),
        ("Synthetic Inn, 1 Example Way", "<X>, <N> <X>"),
        ("Zürich trip", "<X>"),
        (None, "-"),
        ("", "-"),
        ("   ", "-"),
    ],
)
def test_mask_title(title, masked):
    assert mask_title(title) == masked


def test_write_token_is_atomic_and_private(tmp_path):
    private_dir = tmp_path / "p"
    token = private_dir / TOKEN_FILE
    write_token(private_dir, '{"token": "x"}')
    assert token.read_text() == '{"token": "x"}'
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert stat.S_IMODE(private_dir.stat().st_mode) == 0o700
    assert list(private_dir.iterdir()) == [token]
    write_token(private_dir, '{"token": "y"}')
    assert token.read_text() == '{"token": "y"}'


def test_authorized_session_requires_private_token(tmp_path):
    with pytest.raises(GcalError, match="^gcal_not_connected$"):
        authorized_session(tmp_path)
    path = _token(tmp_path, mode=0o644)
    with pytest.raises(GcalError, match="^gcal_credential_permissions$"):
        authorized_session(tmp_path)
    path.chmod(0o600)
    for contents in ("not json", "[]"):
        path.write_text(contents)
        with pytest.raises(GcalError, match="^gcal_reauth_required$"):
            authorized_session(tmp_path)


def test_authorized_session_checks_scope_and_uses_valid_token(tmp_path):
    path = _token(tmp_path)
    before = path.read_text()
    with authorized_session(tmp_path) as session:
        assert isinstance(session, AuthorizedSession)
    assert path.read_text() == before
    _token(tmp_path, scopes=("https://www.googleapis.com/auth/calendar.events.readonly",))
    with pytest.raises(GcalError, match="^gcal_scope_missing$"):
        authorized_session(tmp_path)


def test_authorized_session_refreshes_expired_token(tmp_path, monkeypatch):
    token = _token(tmp_path, expiry="2000-01-01T00:00:00Z")

    def refresh(credentials, request):
        credentials.token = "synthetic-refreshed"
        credentials.expiry = datetime(2999, 1, 1)

    monkeypatch.setattr(google_calendar.Credentials, "refresh", refresh)
    with authorized_session(tmp_path) as session:
        assert isinstance(session, AuthorizedSession)
    assert json.loads(token.read_text())["token"] == "synthetic-refreshed"
    assert stat.S_IMODE(token.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("error", "code"), [(RefreshError, "gcal_reauth_required"), (TransportError, "gcal_remote_error")]
)
def test_authorized_session_preserves_token_on_refresh_failure(tmp_path, monkeypatch, error, code):
    token = _token(tmp_path, expiry="2000-01-01T00:00:00Z")

    def refresh(credentials, request):
        raise error("private response")

    monkeypatch.setattr(google_calendar.Credentials, "refresh", refresh)
    with pytest.raises(GcalError, match=f"^{code}$"):
        authorized_session(tmp_path)
    assert json.loads(token.read_text())["token"] == "synthetic-access"


def test_connect_flow_stores_token_and_keeps_prompt_off_stdout(tmp_path, monkeypatch, capsys):
    client = tmp_path / CLIENT_FILE
    client.write_text("{}")
    client.chmod(0o600)
    calls = _fake_flow(monkeypatch, FakeCredentials())
    connect_flow(tmp_path, open_browser=False)
    assert calls["init"] == (str(client), list(SCOPES), {"autogenerate_code_verifier": True})
    assert calls["run"] == {
        "host": "127.0.0.1",
        "port": 0,
        "open_browser": False,
        "access_type": "offline",
        "prompt": "consent",
        "authorization_prompt_message": "Open this authorization URL: {url}",
    }
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Open this authorization URL: https://authorization.example.invalid\n"
    token = tmp_path / TOKEN_FILE
    assert token.read_text() == FakeCredentials().to_json()
    assert stat.S_IMODE(token.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("mode", "credentials", "code"),
    [
        (None, FakeCredentials(), "gcal_client_file_missing"),
        (0o644, FakeCredentials(), "gcal_credential_permissions"),
        (0o600, FakeCredentials(refresh_token=None), "gcal_no_refresh_token"),
        (0o600, FakeCredentials(granted_scopes=["openid"]), "gcal_scope_missing"),
    ],
)
def test_connect_flow_errors(tmp_path, monkeypatch, mode, credentials, code):
    client = tmp_path / CLIENT_FILE
    if mode is not None:
        client.write_text("{}")
        client.chmod(mode)
    _fake_flow(monkeypatch, credentials)
    with pytest.raises(GcalError, match=f"^{code}$"):
        connect_flow(tmp_path)
    assert not (tmp_path / TOKEN_FILE).exists()


def test_connect_flow_masks_malformed_client(tmp_path):
    client = tmp_path / CLIENT_FILE
    client.write_text('{"synthetic": "protected"}')
    client.chmod(0o600)
    with pytest.raises(GcalError, match="^gcal_reauth_required$"):
        connect_flow(tmp_path)


def test_fetch_events_uses_partial_fields_and_follows_pages():
    http = FakeHttp(*(FakeResponse(200, page) for page in FIXTURE["pages"]))
    assert fetch_events(http, *WINDOW) == list(ITEMS.values())
    params = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "showDeleted": "false",
        "maxResults": 2500,
        "timeMin": "2026-10-23T00:00:00-04:00",
        "timeMax": "2027-05-22T00:00:00-04:00",
        "fields": FETCH_FIELDS,
    }
    assert http.calls == [(EVENTS_URL, params, 30), (EVENTS_URL, {**params, "pageToken": "p2"}, 30)]
    assert "description" not in FETCH_FIELDS
    assert "email" not in FETCH_FIELDS


@pytest.mark.parametrize(("tokens", "count"), [(["same", "same"], 2), ([f"t{i}" for i in range(20)], 20), ([[]], 1)])
def test_fetch_events_stops_on_bad_token_or_page_limit(tokens, count):
    http = FakeHttp(*(FakeResponse(200, {"items": [], "nextPageToken": token}) for token in tokens))
    with pytest.raises(GcalError, match="^gcal_invalid_response$"):
        fetch_events(http, *WINDOW)
    assert len(http.calls) == count


def _forbidden(reason):
    return FakeResponse(403, {"error": {"errors": [{"reason": reason}], "message": "secret body text"}})


@pytest.mark.parametrize(
    ("response", "code", "status", "retry_after"),
    [
        (FakeResponse(401), "gcal_reauth_required", 401, None),
        (FakeResponse(429, headers={"Retry-After": "7"}), "gcal_rate_limited", 429, "7"),
        (_forbidden("rateLimitExceeded"), "gcal_rate_limited", 403, None),
        (_forbidden("userRateLimitExceeded"), "gcal_rate_limited", 403, None),
        (_forbidden("forbidden"), "gcal_remote_error", 403, None),
        (_forbidden([]), "gcal_remote_error", 403, None),
        (FakeResponse(500, {"error": {"message": "secret body text"}}), "gcal_remote_error", 500, None),
        (requests.ConnectionError("secret"), "gcal_remote_error", None, None),
        (TransportError("secret"), "gcal_remote_error", None, None),
    ],
)
def test_http_failures_map_to_safe_codes(response, code, status, retry_after):
    with pytest.raises(GcalRemoteError, match=f"^{code}$") as exc:
        fetch_events(FakeHttp(response), *WINDOW)
    assert exc.value.status_code == status
    assert exc.value.retry_after == retry_after


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (RefreshError("secret"), "gcal_reauth_required"),
        (FakeResponse(200, ValueError("bad json")), "gcal_invalid_response"),
        (FakeResponse(200, ["not", "a", "dict"]), "gcal_invalid_response"),
        (FakeResponse(200, {"items": "nope"}), "gcal_invalid_response"),
    ],
)
def test_transport_and_shape_failures(response, code):
    with pytest.raises(GcalError, match=f"^{code}$"):
        fetch_events(FakeHttp(response), *WINDOW)


def test_fetch_events_rejects_naive_window():
    http = FakeHttp()
    with pytest.raises(ValueError, match="^naive_instant$"):
        fetch_events(http, datetime(2026, 10, 23), WINDOW[1])
    assert http.calls == []


def test_list_calendars_returns_items():
    http = FakeHttp(FakeResponse(200, {"items": FIXTURE["calendars"]}))
    assert list_calendars(http) == FIXTURE["calendars"]
    assert http.calls[0][1] == {"fields": "items(summary,accessRole,primary)", "maxResults": 250}
