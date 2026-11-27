"""Exercise native Google Calendar replay against synthetic provider pages.

Run from the repository root with python3 scripts/test-db.py gcal.
"""

import json
import os
import subprocess
import tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import psycopg
from gcal_dismissed_alias import dismissed_alias
from sqlalchemy.engine import make_url
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema


def test_url():
    raw = os.environ.get("TEST_DATABASE_URL")
    if (
        not raw
        or os.environ.get("DATABASE_URL") != raw
        or os.environ.get("APP_MODE") != "test"
    ):
        raise SystemExit("use scripts/test-db.py with the isolated test database")
    url = make_url(raw)
    if (
        url.database != "garmin_test"
        or url.host not in {"localhost", "127.0.0.1"}
        or str(url.port) != os.environ.get("TEST_DATABASE_PORT")
        or url.query
    ):
        raise SystemExit("expected a dedicated local garmin_test database")
    return url


def connect(env):
    return psycopg.connect(
        env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"], autocommit=True
    )


def fixture(name):
    content = json.loads((BACKEND / "tests/fixtures/gcal" / name).read_text())
    assert content["synthetic"] is True
    return [event for page in content["pages"] for event in page["items"]]


def athlete_edits(env):
    with connect(env) as db:
        db.execute("""INSERT INTO trips(id,status,start_date,end_date,destination_label,destination_tz,source,
                    running_access,gym_access,day_availability,edited,detected,version,created_at,updated_at)
            VALUES (gen_random_uuid(),'confirmed','2026-12-03','2026-12-08','Manual destination','Asia/Tokyo',
                    'manual','normal','none','[]',true,'{}',3,'2026-11-22T10:00Z','2026-11-22T11:00Z')""")
        assert (
            db.execute("""UPDATE trips SET status='confirmed',edited=true,destination_label='Athlete destination',
            running_access='limited',gym_access='full',day_availability='[{"date":"2026-12-04","availability":"reduced"}]',
            version=version+1,updated_at='2026-11-22T12:00Z'
            WHERE source='detected' AND start_date='2026-12-03'""").rowcount
            == 1
        )
        assert (
            db.execute("""UPDATE gcal_events SET category='social',category_source='athlete',version=version+1
            WHERE google_event_id='evt-lodging-1'""").rowcount
            == 1
        )


def pair(events):
    # Deliver a superseded occurrence on page 1 to verify last-record-wins across pages.
    first, *rest = events
    return [
        {
            "items": [dict(first, summary="Earlier title"), *rest[:2]],
            "nextPageToken": "p2",
        },
        {"items": [first, *rest[2:]], "page_token": "p2"},
    ]


def snapshot(env):
    with connect(env) as db:
        return {
            table: db.execute(
                f"SELECT to_jsonb(t) FROM {table} t ORDER BY id"
            ).fetchall()
            for table in (
                "gcal_events",
                "trips",
                "trip_legs",
                "import_batches",
                "app_state",
            )
        }


def scenario(binary, directory, go):
    go["GORACE"] = "atexit_sleep_ms=0"
    path = directory / "synthetic-pages.json"
    command = [binary, "-input", path]

    def run(hour, pages, error=None, *, minute=0):
        now = f"2026-11-22T{hour:02}:{minute:02}:00+00:00"
        path.write_text(json.dumps({"now": now, "pages": pages}))
        proc = subprocess.run(
            command, env=go, capture_output=True, text=True, check=False
        )
        if error:
            assert proc.returncode and error in proc.stderr, (error, proc.stderr)
            return
        proc.check_returncode()
        result = json.loads(proc.stdout)
        sync = result["sync"]
        assert datetime.fromisoformat(sync["started_at"]) == datetime.fromisoformat(now)
        with connect(go) as db:
            (finished,) = db.execute(
                "SELECT finished_at FROM import_batches WHERE started_at=%s", (now,)
            ).fetchone()
        assert (
            abs(
                (datetime.fromisoformat(sync["finished_at"]) - finished).total_seconds()
            )
            <= 0.000001
        )
        return result

    cross = fixture("trips_cross_zone.json")
    basic = fixture("basic_pages.json")
    originals = [e for e in cross if e["id"].startswith(("evt-a-", "evt-c-"))]
    originals += [e for e in basic if e["id"] != "evt-flight-1"]
    # A fetch from an earlier window left an all-day event that ends at this window's open boundary.
    outside = {
        "id": "outside",
        "start": {"date": "2026-10-22"},
        "end": {"date": "2026-10-23"},
    }
    first = run(4, pair([*originals, outside]))
    assert first["trips"]["created"] == 2
    before = snapshot(go)
    replay = run(5, pair(originals))
    assert (
        replay["sync"]["counters"]["unchanged"]
        == first["sync"]["counters"]["created"] - 1
    )
    after = snapshot(go)
    assert all(
        before[t] == after[t]
        for t in ("gcal_events", "trips", "trip_legs", "app_state")
    )

    athlete_edits(go)
    before = snapshot(go)
    manual = [row for (row,) in before["trips"] if row["source"] == "manual"]
    changed = deepcopy(originals)
    for event in changed:
        if event["id"] == "evt-a-out-2":
            event["summary"] = "Flight to Synthetic Center (ZZ 102)"
        if event["id"] == "evt-lodging-1":
            event["summary"] = "Synthetic rehearsal"
    pages = pair(changed)
    run(6, pages[:1], error="gcal_invalid_response")
    wrong_continuation = [pages[0], dict(pages[1], page_token="skipped-page")]
    run(6, wrong_continuation, error="gcal_invalid_response", minute=30)
    after = snapshot(go)
    assert all(
        before[t] == after[t]
        for t in ("gcal_events", "trips", "trip_legs", "app_state")
    )
    assert len(after["import_batches"]) == len(before["import_batches"]) + 2

    # Fail after the calendar and trip writes, before the success receipt commits.
    path.write_text(json.dumps({"now": "2026-11-22T07:00:00Z", "pages": pages}))
    with connect(go) as db:
        db.execute("""CREATE FUNCTION reject_batch() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'synthetic batch failure'; END $$;
            CREATE TRIGGER reject_batch BEFORE INSERT ON import_batches FOR EACH ROW EXECUTE FUNCTION reject_batch()""")
        failed = subprocess.run(command, check=False, env=go, capture_output=True)
        assert failed.returncode and snapshot(go) == after
        db.execute("DROP TRIGGER reject_batch ON import_batches")
    updated = run(7, pages)
    assert (
        updated["trips"]["flagged"] == 1 and updated["sync"]["counters"]["changed"] == 2
    )
    cancelled = [
        {"id": e["id"], "status": "cancelled"}
        if e["id"].startswith(("evt-a-", "evt-c-"))
        else e
        for e in changed
    ]
    # Keep a complete page where every former leg is absent/explicitly cancelled.
    removed = run(8, [{"items": cancelled}])
    assert removed["trips"]["deleted"] == 1 and removed["trips"]["flagged"] == 1
    restored = run(9, pages)
    assert (
        restored["sync"]["counters"]["restored"] == 4
        and restored["trips"]["created"] == 1
    )
    current = snapshot(go)
    assert manual == [row for (row,) in current["trips"] if row["source"] == "manual"]
    (edited,) = [
        row
        for (row,) in current["trips"]
        if row["destination_label"] == "Athlete destination"
    ]
    assert (
        edited["running_access"],
        edited["gym_access"],
        edited["day_availability"],
        edited["status"],
    ) == (
        "limited",
        "full",
        [{"date": "2026-12-04", "availability": "reduced"}],
        "needs_review",
    )
    (event,) = [
        row
        for (row,) in current["gcal_events"]
        if row["google_event_id"] == "evt-lodging-1"
    ]
    assert (event["category"], event["category_source"]) == ("social", "athlete")
    dismissed_alias(run, go, connect)
    print(
        "PASS Google Calendar paginated replay, rollback/retry, cancel/restore, trip legs, versions and athlete edits"
    )


def main():
    url = test_url()
    pg_url = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with (
        psycopg.connect(pg_url, autocommit=True) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
    ):
        directory = Path(tmp)
        binary = directory / "gcal-replay"
        subprocess.run(
            ["go", "build", "-race", "-o", binary, "./cmd/gcal-replay"],
            cwd=MODULE,
            check=True,
        )
        with migrated_schema(db, url, directory / "native", "5173") as go:
            scenario(binary, directory, go)


if __name__ == "__main__":
    main()
