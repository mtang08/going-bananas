import argparse
import json
import re
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import cli
from app.adapters import google_calendar
from app.adapters.google_calendar import TITLE_ALLOWLIST, GcalError

FIXTURE = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "gcal" / "basic_pages.json").read_text())
ITEMS = [item for page in FIXTURE["pages"] for item in page["items"]]
PRIVATE_KEYS = {"id", "summary", "location", "description", "email", "dateTime", "date", "updated", "htmlLink"}


def _private_strings(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in PRIVATE_KEYS and isinstance(value, str):
                yield value
                yield from value.split()
                if key in {"dateTime", "date", "updated"}:
                    yield value[:10]
            else:
                yield from _private_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _private_strings(value)


def _run(monkeypatch, mode, tmp_path, **args):
    monkeypatch.setattr(cli, "settings", SimpleNamespace(app_mode=mode, private_dir=tmp_path))
    monkeypatch.setattr(cli, "_parse", lambda: argparse.Namespace(**args))
    monkeypatch.setattr(
        cli, "SessionLocal", lambda *a, **k: pytest.fail("the calendar commands must not open the database")
    )
    return cli.main()


def test_probe_lines_match_contract():
    assert cli.probe_lines(FIXTURE["calendars"], ITEMS) == [
        "calendar name=<primary> access_role=owner primary=true",
        "calendar name=<X> access_role=reader primary=false",
        "event type=fromGmail kind=timed start_tz=America/New_York end_tz=America/Los_Angeles "
        'transparency=opaque response=accepted dur_h=6.5 title="Flight to <X> (<AA> <N>)" location="<IATA> <X> <N>"',
        "event type=fromGmail kind=all_day start_tz=- end_tz=- transparency=transparent "
        'response=- dur_h=96.0 title="Stay at <X>" location="<X>, <N> <X>"',
        "event type=default kind=timed start_tz=- end_tz=- transparency=opaque "
        'response=declined dur_h=1.0 title="<X>" location="-"',
        "event type=focusTime kind=timed start_tz=- end_tz=- transparency=transparent "
        'response=- dur_h=2.0 title="<X>" location="-"',
        "event type=outOfOffice kind=timed start_tz=- end_tz=- transparency=opaque "
        'response=- dur_h=120.0 title="Out of office" location="-"',
        "summary events=5 default=1 focusTime=1 fromGmail=2 outOfOffice=1 tz_differs=1 tz_missing=3",
    ]


def test_probe_leaks_no_fixture_text():
    def leaks(output):
        return {
            text
            for text in _private_strings(FIXTURE)
            if len(text) > 3
            and not set(text.split()) <= TITLE_ALLOWLIST
            and re.search(r"(?<!\w)" + re.escape(text) + r"(?!\w)", output)
        }

    output = "\n".join(cli.probe_lines(FIXTURE["calendars"], ITEMS))
    assert leaks(output) == set()
    assert "Synthetic" in leaks(output + " Synthetic")


def test_probe_leaks_no_unexpected_metadata_or_calendar_titles():
    calendar = {"summary": "Hotel Reservation at Secret Retreat", "accessRole": "secret@example.invalid"}
    item = {
        **ITEMS[0],
        "eventType": "Private Event",
        "start": {**ITEMS[0]["start"], "timeZone": "Private/Secret"},
        "transparency": "Unrecognized private visibility",
        "attendees": [{"self": True, "responseStatus": "Unrecognized private RSVP"}],
    }
    lines = cli.probe_lines([calendar], [item])
    assert lines[0] == "calendar name=<X> access_role=- primary=false"
    assert lines[1].startswith(
        "event type=unknown kind=timed start_tz=- end_tz=America/Los_Angeles transparency=opaque response=- "
    )
    assert lines[2] == "summary events=1 unknown=1 tz_differs=0 tz_missing=1"


@pytest.mark.parametrize(
    "args", [{"command": "calendar-connect", "no_browser": True}, {"command": "calendar-probe", "days": 60}]
)
def test_calendar_commands_require_real_mode(monkeypatch, tmp_path, capsys, args):
    assert _run(monkeypatch, "test", tmp_path, **args) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "real_mode_required"}


def test_calendar_probe_prints_report(monkeypatch, tmp_path, capsys):
    calls = []

    def fetch(http, time_min, time_max):
        calls.append((http, time_min, time_max))
        return ITEMS

    monkeypatch.setattr(google_calendar, "authorized_session", lambda private_dir: "synthetic-http")
    monkeypatch.setattr(google_calendar, "list_calendars", lambda http: FIXTURE["calendars"])
    monkeypatch.setattr(google_calendar, "fetch_events", fetch)
    assert _run(monkeypatch, "real", tmp_path, command="calendar-probe", days=30) == 0
    assert capsys.readouterr().out.splitlines() == cli.probe_lines(FIXTURE["calendars"], ITEMS)
    [(http, time_min, time_max)] = calls
    assert http == "synthetic-http"
    assert time_max - time_min == timedelta(days=30)
    assert time_min.tzinfo is not None


def test_calendar_probe_reports_disconnected(monkeypatch, tmp_path, capsys):
    def disconnected(private_dir):
        raise GcalError("gcal_not_connected")

    monkeypatch.setattr(google_calendar, "authorized_session", disconnected)
    assert _run(monkeypatch, "real", tmp_path, command="calendar-probe", days=60) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "gcal_not_connected"}


@pytest.mark.parametrize("days", [0, 181])
def test_calendar_probe_checks_days_before_connecting(monkeypatch, tmp_path, capsys, days):
    def unexpected_session(private_dir):
        pytest.fail("an invalid window must not create an authorized session")

    monkeypatch.setattr(google_calendar, "authorized_session", unexpected_session)
    assert _run(monkeypatch, "real", tmp_path, command="calendar-probe", days=days) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "invalid_date_window"}


def test_calendar_connect_prints_only_status(monkeypatch, tmp_path, capsys):
    calls = []

    def connect(private_dir, *, open_browser):
        calls.append((private_dir, open_browser))

    monkeypatch.setattr(google_calendar, "connect_flow", connect)
    assert _run(monkeypatch, "real", tmp_path, command="calendar-connect", no_browser=True) == 0
    assert capsys.readouterr().out == '{"connected": true, "scope": "calendar.readonly"}\n'
    assert calls == [(tmp_path, False)]
