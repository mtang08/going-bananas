"""Google Calendar v3 adapter: credentials, event records, and redacted probe text.

Never logs, prints, or returns descriptions, attendee emails, tokens, or response bodies.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import webbrowser
from contextlib import redirect_stdout
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import requests
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from oauthlib.oauth2 import OAuth2Error

SCOPES = ("https://www.googleapis.com/auth/calendar.readonly",)
CLIENT_FILE = "google-calendar-client.json"
TOKEN_FILE = "google-calendar-token.json"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
CALENDARS_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
FETCH_FIELDS = (
    "nextPageToken,items(id,status,eventType,summary,location,start,end,transparency,updated,"
    "attendees(self,responseStatus))"
)
MAX_PAGES = 20
TIMEOUT_S = 30
RATE_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})

GOOGLE_STATUSES = ("confirmed", "tentative")
RESPONSE_STATUSES = ("needsAction", "declined", "tentative", "accepted")
FLIGHT_CODE = re.compile(r"\b([A-Z0-9]{2})\s?(\d{1,4})\b")
IATA = re.compile(r"\b[A-Z]{3}\b")
MAX_LOCATION_CODES = 4
TITLE_ALLOWLIST = frozenset(
    {
        "Flight",
        "to",
        "from",
        "Stay",
        "at",
        "Hotel",
        "Check-in",
        "Checkout",
        "Train",
        "Bus",
        "Reservation",
        "Rental",
        "Car",
        "Out",
        "of",
        "office",
        "Trip",
    }
)
_KEPT_PUNCTUATION = frozenset("()-:,→/")
_PIECE = re.compile(r"\x00|[^\W\d_]+(?:-[^\W\d_]+)*|\d+|.")
_UNSAFE = ("@", "http", "www")


class GcalError(RuntimeError):
    """A safe failure code from contracts §2.3; `str(exc)` is the code."""


class GcalRemoteError(GcalError):
    """A failed Google request: the code plus HTTP status and Retry-After, never the response body."""

    def __init__(self, code: str, status_code: int | None, retry_after: str | None = None):
        super().__init__(code)
        self.status_code = status_code
        self.retry_after = retry_after


def _private_file(path: Path) -> Path:
    if path.stat().st_mode & 0o077:
        raise GcalError("gcal_credential_permissions")
    return path


def write_token(private_dir: Path, token_json: str) -> None:
    """Atomically replace the token file with mode 0600 inside a 0700 directory."""
    private_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_dir.chmod(0o700)
    fd, temp_name = tempfile.mkstemp(prefix=".gcal-", dir=private_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(token_json)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, private_dir / TOKEN_FILE)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def authorized_session(private_dir: Path) -> AuthorizedSession:
    """A requests session for the stored token; an expired token is refreshed and rewritten first."""
    path = private_dir / TOKEN_FILE
    if not path.is_file():
        raise GcalError("gcal_not_connected")
    try:
        info = json.loads(_private_file(path).read_text(encoding="utf-8"))
        if not isinstance(info, dict):
            raise ValueError
        credentials = Credentials.from_authorized_user_info(info)
        has_scope = credentials.has_scopes(SCOPES)
    except (AttributeError, OSError, TypeError, ValueError):
        raise GcalError("gcal_reauth_required") from None
    if not has_scope:
        raise GcalError("gcal_scope_missing")
    if not credentials.valid:
        try:
            credentials.refresh(Request())
        except RefreshError:
            raise GcalError("gcal_reauth_required") from None
        except TransportError:
            raise GcalRemoteError("gcal_remote_error", None) from None
        if credentials.granted_scopes is not None and SCOPES[0] not in credentials.granted_scopes:
            raise GcalError("gcal_scope_missing")
        write_token(private_dir, credentials.to_json())
    return AuthorizedSession(credentials, max_refresh_attempts=1, refresh_timeout=TIMEOUT_S)


def connect_flow(private_dir: Path, *, open_browser: bool = True) -> None:
    """Run the installed-app consent flow on a loopback port and store the token (calendar-connect)."""
    client = private_dir / CLIENT_FILE
    if not client.is_file():
        raise GcalError("gcal_client_file_missing")
    flow_logger = logging.getLogger("google_auth_oauthlib.flow")
    was_disabled = flow_logger.disabled
    flow_logger.disabled = True
    try:
        _private_file(client)
        flow = InstalledAppFlow.from_client_secrets_file(str(client), list(SCOPES), autogenerate_code_verifier=True)
        with redirect_stdout(sys.stderr):
            credentials = flow.run_local_server(
                host="127.0.0.1",
                port=0,
                open_browser=open_browser,
                authorization_prompt_message=None if open_browser else "Open this authorization URL: {url}",
                access_type="offline",
                prompt="consent",
            )
    except Warning:
        # OAuthlib raises a plain Warning when the granted scopes differ.
        raise GcalError("gcal_scope_missing") from None
    except (AttributeError, KeyError, OAuth2Error, TypeError, ValueError):
        raise GcalError("gcal_reauth_required") from None
    except (OSError, requests.RequestException, webbrowser.Error):
        raise GcalRemoteError("gcal_remote_error", None) from None
    finally:
        flow_logger.disabled = was_disabled
    if not credentials.refresh_token:
        raise GcalError("gcal_no_refresh_token")
    granted = getattr(credentials, "granted_scopes", None)
    if granted is not None and SCOPES[0] not in granted:
        raise GcalError("gcal_scope_missing")
    write_token(private_dir, credentials.to_json())


HASH_EXCLUDED = frozenset({"content_hash", "google_updated_at"})


def content_hash(record: dict[str, Any]) -> str:
    body = {key: value for key, value in record.items() if key not in HASH_EXCLUDED}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def _utc(value: str) -> str:
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        raise ValueError("naive_instant")
    return instant.astimezone(UTC).isoformat()


def _times(start: dict[str, Any], end: dict[str, Any]) -> tuple[Any, Any, Any, Any] | None:
    if "date" in start and "date" in end:
        return None, None, date.fromisoformat(start["date"]).isoformat(), date.fromisoformat(end["date"]).isoformat()
    if "dateTime" in start and "dateTime" in end:
        return _utc(start["dateTime"]), _utc(end["dateTime"]), None, None
    return None


def to_record(item: dict[str, Any]) -> dict[str, Any] | None:
    """Contracts §3 projection of one events.list item; None for a cancelled item or one without start and end."""
    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
        raise GcalError("gcal_invalid_response")
    if item.get("status") == "cancelled":
        return None
    start, end = item.get("start"), item.get("end")
    if start is None or end is None:
        return None
    if not isinstance(start, dict) or not isinstance(end, dict):
        raise GcalError("gcal_invalid_response")
    try:
        times = _times(start, end)
        updated = item.get("updated")
        if updated is not None:
            _utc(updated)
    except (TypeError, ValueError, OverflowError):
        raise GcalError("gcal_invalid_response") from None
    if times is None:
        return None
    start_at, end_at, start_date, end_date = times
    response = _self_response(item.get("attendees"))
    response = response if response in RESPONSE_STATUSES else None
    transparency = "transparent" if item.get("transparency") == "transparent" else "opaque"
    summary, location = item.get("summary"), item.get("location")
    record = {
        "google_event_id": item["id"],
        "event_type": (_optional_string(item.get("eventType")) or "default")[:32],
        "google_status": item["status"] if item.get("status") in GOOGLE_STATUSES else "confirmed",
        "summary": summary if isinstance(summary, str) else None,
        "location_codes": IATA.findall(location)[:MAX_LOCATION_CODES] if isinstance(location, str) else [],
        "all_day": start_date is not None,
        "start_at": start_at,
        "end_at": end_at,
        "start_date": start_date,
        "end_date": end_date,
        "start_tz": _optional_string(start.get("timeZone"), max_length=64),
        "end_tz": _optional_string(end.get("timeZone"), max_length=64),
        "transparency": transparency,
        "response_status": response,
        "busy": transparency != "transparent" and response != "declined",
        "google_updated_at": updated,
    }
    record["content_hash"] = content_hash(record)
    return record


def _optional_string(value: Any, *, max_length: int | None = None) -> str | None:
    if value is not None and (not isinstance(value, str) or (max_length is not None and len(value) > max_length)):
        raise GcalError("gcal_invalid_response")
    return value


def _self_response(attendees: Any) -> str | None:
    if attendees is None:
        return None
    if not isinstance(attendees, list) or not all(isinstance(entry, dict) for entry in attendees):
        raise GcalError("gcal_invalid_response")
    return next((entry.get("responseStatus") for entry in attendees if entry.get("self") is True), None)


def _mask_piece(piece: str) -> str:
    if piece == "\x00":
        return "<AA> <N>"
    if piece in TITLE_ALLOWLIST or piece in _KEPT_PUNCTUATION:
        return piece
    if re.fullmatch(r"[A-Z]{3}", piece):
        return "<IATA>"
    if piece.isdigit():
        return "<N>"
    return "<X>" if piece[0].isalpha() else ""


def mask_title(text: str | None) -> str:
    """Redacted shape of a title or location for the probe (design §3); "-" when empty."""
    if not text or not text.strip():
        return "-"
    if "flight" in text.lower():
        text = FLIGHT_CODE.sub("\x00", text)
    words = []
    for token in text.split():
        if any(marker in token.lower() for marker in _UNSAFE):
            words.append("<X>")
        else:
            words.append("".join(_mask_piece(piece) for piece in _PIECE.findall(token)))
    return re.sub(r"<X>(?:\s*<X>)+", "<X>", " ".join(word for word in words if word))


def _reason(response: Any) -> str | None:
    try:
        reason = response.json()["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return reason if isinstance(reason, str) else None


def _get_json(http: Any, url: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        response = http.get(url, params=params, timeout=TIMEOUT_S)
    except RefreshError:
        raise GcalError("gcal_reauth_required") from None
    except (TransportError, requests.RequestException):
        raise GcalRemoteError("gcal_remote_error", None) from None
    status = response.status_code
    if status == 401:
        raise GcalRemoteError("gcal_reauth_required", status)
    if status == 429 or (status == 403 and _reason(response) in RATE_REASONS):
        raise GcalRemoteError("gcal_rate_limited", status, response.headers.get("Retry-After"))
    if status != 200:
        raise GcalRemoteError("gcal_remote_error", status)
    try:
        data = response.json()
    except ValueError:
        raise GcalError("gcal_invalid_response") from None
    if not isinstance(data, dict):
        raise GcalError("gcal_invalid_response")
    return data


def _items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items", [])
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise GcalError("gcal_invalid_response")
    return items


def list_calendars(http: Any) -> list[dict[str, Any]]:
    """The account's calendars (summary, access role, primary flag) for the probe."""
    return _items(_get_json(http, CALENDARS_URL, {"fields": "items(summary,accessRole,primary)", "maxResults": 250}))


def fetch_events(http: Any, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
    """Every primary-calendar item overlapping [time_min, time_max), in start order, across pages."""
    if time_min.tzinfo is None or time_max.tzinfo is None:
        raise ValueError("naive_instant")
    params: dict[str, Any] = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "showDeleted": "false",
        "maxResults": 2500,
        "timeMin": time_min.isoformat(),
        "timeMax": time_max.isoformat(),
        "fields": FETCH_FIELDS,
    }
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _ in range(MAX_PAGES):
        data = _get_json(http, EVENTS_URL, params)
        items.extend(_items(data))
        token = data.get("nextPageToken")
        if token is None or token == "":
            return items
        if not isinstance(token, str) or token in seen:
            raise GcalError("gcal_invalid_response")
        seen.add(token)
        params = {**params, "pageToken": token}
    raise GcalError("gcal_invalid_response")
