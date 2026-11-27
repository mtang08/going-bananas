"""Exercise the seven native travel routes with synthetic Calendar pages."""

import json
import re
import selectors
import subprocess
import tempfile
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path

import psycopg
from check_gcal_replay import connect, fixture, test_url
from test_proposal_slice import (
    MODULE,
    ROOT,
    listener,
    migrated_schema,
)

PREFIX = "/api/v1"
FIXED_DAY = "2026-11-22"


@contextmanager
def server(env, binary, mode):
    with listener(
        [binary, "-test.run=^TestTravelFixtureServer$", "-test.timeout=5m"],
        env=dict(
            env,
            TRAVEL_HTTP_FIXTURE_MODE=mode,
            PGOPTIONS=env["PGOPTIONS"] + " -cdefault_transaction_read_only=on",
        ),
        stdout=subprocess.PIPE,
        text=True,
    ) as proc:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=20), "travel fixture listener did not start"
        address = proc.stdout.readline().strip()
        assert re.fullmatch(r"127\.0\.0\.1:\d+", address), address
        yield int(address.split(":")[1])


def request(port, method, path, body):
    conn = HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(
            method,
            PREFIX + path,
            body=json.dumps(body) if body is not None else None,
            headers={"X-Local-Request": "1", "Content-Type": "application/json"},
        )
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    finally:
        conn.close()


def identities(env):
    with connect(env) as db:
        rows = db.execute("""SELECT id,'event:'||google_event_id FROM gcal_events
            UNION ALL SELECT id, 'trip:'||source||':'||start_date::text FROM trips""")
        out = {str(uid): key for uid, key in rows}
        assert len(set(out.values())) == len(out)
        return out


def scenario(binary, env):
    folder = Path(env["PRIVATE_DIR"])

    def clock(hour):
        (folder / "now").write_text(f"{FIXED_DAY}T{hour:02}:00:00Z")

    def provider(items=None, error=None):
        (folder / "connected").touch()
        (folder / "google-calendar-token.json").touch()
        pages = (
            [
                {"items": items[:2], "nextPageToken": "2"},
                {"page_token": "2", "items": items[2:]},
            ]
            if items
            else [{"items": []}]
        )
        (folder / "delivery.json").write_text(
            json.dumps({"pages": pages, "error": error})
        )

    def call(method, route, body=None, *, status=200, code=None):
        path = route
        ids = identities(env)
        for uid, alias in ids.items():
            path = path.replace("{" + alias + "}", uid)
        actual, result = request(port, method, path, body)
        assert actual == status, (method, route, actual, result)
        if code:
            error = result["error"]
            assert error["code"] == code and error["request_id"], error
            return error
        with connect(env) as db:
            (revision,) = db.execute(
                "SELECT data_revision FROM app_state WHERE id=1"
            ).fetchone()
        assert result["mode"] == mode and result["data_revision"] == revision
        return result["data"]

    sync = "/google-calendar/sync"
    events = "/google-calendar/events"
    trips = "/trips"
    status_url = "/google-calendar/status"
    clock(8)
    mode = "test"
    with server(env, binary, mode) as port:
        call("POST", sync, {}, status=409, code="real_mode_required")
        assert call("GET", status_url)["connected"] is False
    mode = "real"
    with server(env, binary, mode) as port:
        call("POST", sync, {}, status=409, code="gcal_not_connected")
        assert call("GET", events)["items"] == call("GET", trips)["items"] == []
        originals = [
            e for e in fixture("trips_cross_zone.json") if e["id"].startswith("evt-a-")
        ]
        originals += [
            e for e in fixture("basic_pages.json") if e["id"] != "evt-flight-1"
        ]
        # Fix ordering for two events that share a local date.
        for event in originals:
            if event["id"] == "evt-ooo-1":
                event["start"]["dateTime"] = "2026-12-03T00:01:00-05:00"
        provider(originals)
        assert call("POST", sync, {})["trips"]["created"] == 1
        first_status = call("GET", status_url)
        clock(9)
        duplicate = call("POST", sync, {})
        assert (
            duplicate["sync"]["counters"]["unchanged"]
            == first_status["last_sync"]["counters"]["created"]
        )
        travel_events = call("GET", events + "?category=travel")["items"]
        assert len(travel_events) == 4
        assert (
            len(
                call(
                    "GET", events + "?start=2026-12-03&end=2026-12-03&category=flight"
                )["items"]
            )
            == 2
        )
        assert len(call("GET", events)["items"]) > len(travel_events)
        (trip,) = call("GET", trips)["items"]
        assert len(trip["legs"]) == 3 and trip["legs"][-1]["arrive_local"].endswith(
            "-05:00"
        )
        assert all(
            e["trip_id"] == trip["id"]
            for e in travel_events
            if e["category"] == "flight"
        )
        event_url = events + "/{event:evt-lodging-1}"
        call("PATCH", event_url, {"category": "work", "expected_version": 1})
        call(
            "PATCH",
            event_url,
            {"expected_version": 1, "category": None},
            status=409,
            code="version_conflict",
        )
        call(
            "PATCH",
            event_url,
            {"expected_version": 2},
            status=422,
            code="validation_error",
        )
        call(
            "PATCH",
            event_url,
            {"expected_version": 2, "category": "invalid"},
            status=422,
            code="validation_error",
        )
        call(
            "PATCH",
            events + "/00000000-0000-0000-0000-000000000001",
            {"expected_version": 1, "category": None},
            status=404,
            code="event_not_found",
        )
        detected = trips + "/" + trip["id"]
        call(
            "PATCH",
            detected,
            {
                "expected_version": trip["version"],
                "status": "confirmed",
                "destination_label": "Edited destination",
            },
        )
        changed = [
            dict(e, summary="Flight to Synthetic Center (ZZ 102)")
            if e["id"] == "evt-a-out-2"
            else e
            for e in originals
        ]
        changed = [e for e in changed if e["id"] != "evt-focus-1"]
        clock(10)
        provider(changed)
        assert call("POST", sync, {})["trips"]["flagged"] == 1
        assert [
            identities(env)[e["id"]]
            for e in call("GET", events + "?include_removed=yes")["items"]
            if e["removed"]
        ] == ["event:evt-focus-1"]
        assert (
            call("GET", events + "?category=work")["items"][0]["category_source"]
            == "athlete"
        )
        (current,) = call("GET", trips + "?status=needs_review,confirmed")["items"]
        assert (
            current["destination_label"] == "Edited destination"
            and current["review_reason"] == "source_changed"
        )
        accepted = call(
            "PATCH",
            detected,
            {
                "expected_version": current["version"],
                "accept_detected": True,
                "status": "confirmed",
            },
        )
        assert (
            accepted["review_reason"] is None
            and accepted["destination_label"] != "Edited destination"
        )
        availability = {"date": "2026-12-13", "availability": "reduced"}
        manual = {
            "start_date": "2026-12-12",
            "end_date": "2026-12-14",
            "destination_tz": "Europe/Paris",
            "destination_label": "Synthetic manual",
            "running_access": "limited",
            "gym_access": "none",
            "day_availability": [availability],
        }
        manual_trip = call("POST", trips, manual, status=201)
        manual_url = trips + "/" + manual_trip["id"]
        invalid = [
            (dict(manual, destination_tz="Unknown/City"), "validation_error"),
            (
                dict(manual, day_availability=[availability, availability]),
                "invalid_trip",
            ),
            (dict(manual, ignored=True), "validation_error"),
        ]
        for body, error in invalid:
            call("POST", trips, body, status=422, code=error)
        call(
            "PATCH",
            manual_url,
            {"expected_version": 1, "status": "pending"},
            status=422,
            code="invalid_trip",
        )
        edited = call(
            "PATCH",
            manual_url,
            {"expected_version": 1, "end_date": "2026-12-12", "status": "dismissed"},
        )
        assert edited["day_availability"] == [] and edited["version"] == 2
        assert len(call("GET", trips)["items"]) == 1
        assert call("GET", trips + "?status=dismissed&start=2026-12-12&end=2026-12-12")[
            "items"
        ] == [edited]
        call(
            "PATCH",
            manual_url,
            {"expected_version": 1, "destination_label": None},
            status=409,
            code="version_conflict",
        )
        call(
            "PATCH",
            trips + "/00000000-0000-0000-0000-000000000001",
            {"expected_version": 1},
            status=404,
            code="trip_not_found",
        )
        for route, error in [
            (events + "?category=invalid", "validation_error"),
            (events + "?include_removed=sometimes", "validation_error"),
            (trips + "?status=wrong", "validation_error"),
            (trips + "?start=2026-12-02&end=2026-12-01", "invalid_date_range"),
        ]:
            call("GET", route, status=422, code=error)
        clock(11)
        provider(error="gcal_rate_limited")
        call("POST", sync, {}, status=503, code="gcal_rate_limited")
        failed = call("GET", status_url)
        assert (
            failed["last_sync"]["status"] == "failed"
            and failed["last_success_at"] != failed["last_sync"]["finished_at"]
        )
        assert call("GET", trips + "?status=dismissed")["items"] == [edited]
    print(
        "PASS all seven travel HTTP routes, sync mode and failure, revision, queries, validation, itinerary, edits and replay"
    )


def main():
    url = test_url()
    pg_url = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with (
        psycopg.connect(pg_url, autocommit=True) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
    ):
        directory = Path(tmp)
        binary = directory / "travel-http.test"
        subprocess.run(
            ["go", "test", "-race", "-c", "-o", binary, "./internal/travelhttp"],
            cwd=MODULE,
            check=True,
        )
        with migrated_schema(db, url, directory / "travel", "5173") as env:
            scenario(binary, env)


if __name__ == "__main__":
    main()
