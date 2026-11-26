"""Compare Google Calendar replay to the Python sync in disposable PostgreSQL schemas.

Run from the repository root with python3 scripts/test-db.py gcal.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

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
        raise SystemExit(
            "run python3 scripts/test-db.py gcal on the isolated test database"
        )
    url = make_url(raw)
    if (
        url.database != "garmin_test"
        or url.host not in {"localhost", "127.0.0.1"}
        or str(url.port) != os.environ.get("TEST_DATABASE_PORT")
        or url.query
    ):
        raise SystemExit("expected a dedicated local garmin_test database")
    return url


def reference(path):
    test_url()
    if not re.fullmatch(
        r"-csearch_path=go_parity_[0-9a-f]{32} -cTimeZone=Asia/Kathmandu",
        os.environ.get("PGOPTIONS", ""),
    ):
        raise SystemExit("expected a disposable comparison schema")
    from app.adapters.google_calendar import TOKEN_FILE, GcalError
    from app.db import SessionLocal
    from app.errors import AppError
    from app.services import derived, gcal_sync

    derived.install()

    data = json.loads(path.read_text())
    pages = iter(data["pages"])

    def get(_, *, params, timeout):
        response = Mock(status_code=200)
        try:
            page = next(pages)
            if page.get("page_token", "") != params.get("pageToken", ""):
                raise GcalError("gcal_invalid_response")
            response.json.return_value = page
        except StopIteration:
            raise GcalError("gcal_invalid_response") from None
        return response

    http = Mock()
    http.get.side_effect = get
    private = Path(os.environ["PRIVATE_DIR"])
    (private / TOKEN_FILE).touch()
    with (
        SessionLocal() as session,
        patch.object(gcal_sync, "authorized_session", return_value=http),
    ):
        try:
            print(
                json.dumps(
                    gcal_sync.run_sync(
                        session, private, datetime.fromisoformat(data["now"])
                    )
                )
            )
        except AppError as exc:
            sys.exit(exc.code)


def connect(env):
    return psycopg.connect(
        env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"], autocommit=True
    )


def snapshot(env, *, raw=False):
    with connect(env) as db:
        if raw:
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
        events = db.execute(
            "SELECT to_jsonb(e)-'id' FROM gcal_events e ORDER BY google_event_id"
        ).fetchall()
        # Compare ordered associations via provider identity. Also compare every trip business column.
        trips = db.execute("""
            SELECT to_jsonb(t)-ARRAY['id','created_at','updated_at'],
                   CASE WHEN t.source='manual' THEN t.created_at::text ELSE 'database creation time' END,
                   CASE WHEN t.source='detected' AND t.updated_at=t.created_at THEN 'database creation time'
                        ELSE t.updated_at::text END,
                   coalesce((SELECT jsonb_agg(jsonb_build_array(e.google_event_id,l.seq,l.leg_hash) ORDER BY l.seq)
                       FROM trip_legs l JOIN gcal_events e ON e.id=l.gcal_event_id WHERE l.trip_id=t.id),'[]')
            FROM trips t ORDER BY t.source,t.start_date,t.destination_label""").fetchall()
        batches = db.execute("""
            SELECT to_jsonb(b)-ARRAY['id','finished_at'],finished_at IS NOT NULL
            FROM import_batches b ORDER BY started_at""").fetchall()
        app = db.execute("SELECT to_jsonb(a) FROM app_state a ORDER BY id").fetchall()
        return {"events": events, "trips": trips, "batches": batches, "app": app}


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


def scenario(binary, directory, py, go):
    py["PYTHONPATH"] = str(BACKEND)
    go["GORACE"] = "atexit_sleep_ms=0"
    path = directory / "synthetic-pages.json"
    commands = [
        (py, [sys.executable, __file__, "reference", path]),
        (go, [binary, "-input", path]),
    ]

    def compare():
        expected, actual = snapshot(py), snapshot(go)
        for key in expected:
            if expected[key] != actual[key]:
                raise AssertionError(
                    f"Different {key}: Python={expected[key]!r} Go={actual[key]!r}"
                )

    def run(hour, pages, error=None, *, minute=0):
        now = f"2026-11-22T{hour:02}:{minute:02}:00+00:00"
        path.write_text(json.dumps({"now": now, "pages": pages}))
        results = []
        for env, cmd in commands:
            proc = subprocess.run(
                cmd, check=False, env=env, capture_output=True, text=True
            )
            if error:
                assert proc.returncode and error in proc.stderr, (error, proc.stderr)
                continue
            if proc.returncode:
                raise RuntimeError(proc.stderr)
            result = json.loads(proc.stdout)
            sync = result["sync"]
            assert datetime.fromisoformat(
                sync.pop("started_at")
            ) == datetime.fromisoformat(now)
            finished = datetime.fromisoformat(sync.pop("finished_at"))
            with connect(env) as db:
                receipt = db.execute(
                    "SELECT finished_at FROM import_batches WHERE started_at=%s", (now,)
                ).fetchone()
                assert (
                    receipt and abs((finished - receipt[0]).total_seconds()) <= 0.000001
                )
            results.append(result)
        compare()
        if results:
            assert results[0] == results[1], results
            return results[0]

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
    before = snapshot(go, raw=True)
    replay = run(5, pair(originals))
    assert (
        replay["sync"]["counters"]["unchanged"]
        == first["sync"]["counters"]["created"] - 1
    )
    after = snapshot(go, raw=True)
    assert all(
        before[t] == after[t]
        for t in ("gcal_events", "trips", "trip_legs", "app_state")
    )

    for env, _ in commands:
        athlete_edits(env)
    compare()
    before = snapshot(go, raw=True)
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
    after = snapshot(go, raw=True)
    assert all(
        before[t] == after[t]
        for t in ("gcal_events", "trips", "trip_legs", "app_state")
    )
    assert len(after["import_batches"]) == len(before["import_batches"]) + 2

    # Fail after the Python-equivalent calendar/trip writes, before the success receipt commits.
    path.write_text(json.dumps({"now": "2026-11-22T07:00:00Z", "pages": pages}))
    with connect(go) as db:
        db.execute("""CREATE FUNCTION reject_batch() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'synthetic batch failure'; END $$;
            CREATE TRIGGER reject_batch BEFORE INSERT ON import_batches FOR EACH ROW EXECUTE FUNCTION reject_batch()""")
        failed = subprocess.run(
            commands[1][1], check=False, env=go, capture_output=True
        )
        assert failed.returncode and snapshot(go, raw=True) == after
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
    current = snapshot(go, raw=True)
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
    dismissed_alias(run, py, go, connect)
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
        with (
            migrated_schema(db, url, directory / "py", "5173") as py,
            migrated_schema(db, url, directory / "go", "5173") as go,
        ):
            scenario(binary, directory, py, go)


if __name__ == "__main__":
    if sys.argv[1:2] == ["reference"]:
        reference(Path(sys.argv[2]))
    else:
        main()
