"""Compare native Garmin sync HTTP and pending treadmill review in disposable PostgreSQL schemas."""

import json
import os
import re
import runpy
import selectors
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import UTC, datetime
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import psycopg
from check_gcal_replay import connect, test_url
from test_proposal_slice import BACKEND, MODULE, ROOT, listener, migrated_schema

DAY = "2026-11-10"
NOW = datetime(2026, 11, 16, 9, tzinfo=UTC)
JOB = "b1e32fd1-bc9a-42f7-92ff-9246eb562a20"
INTERVAL = "8d9ee0ec-7843-4461-8bb8-e58a6661006b"
BASE = "/api/v1/sync"
REVIEW = "/treadmill-review/1"
LEGACY = "3c0154d9-bf90-4ba5-a7bb-dcdb9f91b505"


def seed(env):
    with connect(env) as db:
        db.execute(
            """INSERT INTO coverage_intervals(id,dataset,start_date,end_date,status,reason,fully_enumerated)
            VALUES(%s,'activities',%s,%s,'partial','treadmill_review_pending',true)""",
            (INTERVAL, DAY, DAY),
        )
        db.execute(
            """INSERT INTO sync_jobs(id,dataset,status,start_date,end_date,checkpoint,counters,finished_at)
            VALUES(%s,'activities','complete',%s,%s,%s,'{"seen":0}',now())""",
            (
                JOB,
                DAY,
                DAY,
                json.dumps(
                    {
                        "pending_treadmill": {
                            "1": {
                                "account_scope": "garmin-owner:17701",
                                "local_date": DAY,
                            }
                        },
                        "pending_coverage_id": INTERVAL,
                        "offset": 50,
                    }
                ),
            ),
        )
        db.execute(
            """INSERT INTO sync_jobs(id,dataset,status,checkpoint,counters,next_attempt_at,error_code)
            VALUES(%s,'hrv','retry_wait','{"page":3}','{"unchanged":5}','2026-11-13T00:00:00.000120Z','fixture_error')""",
            (LEGACY,),
        )
        db.execute("""INSERT INTO sync_state(dataset,status,last_attempt_at,reason,fully_enumerated)
        VALUES('activities','partial','2026-11-10T10:11:00.120Z','treadmill_review_pending',true)
        ON CONFLICT(dataset) DO UPDATE SET status=EXCLUDED.status,reason=EXCLUDED.reason,last_attempt_at=EXCLUDED.last_attempt_at""")
    root = Path(env["PRIVATE_DIR"])
    row = {
        "activityId": "1",
        "activityName": "Fixture treadmill",
        "ownerId": "17701",
        "startTimeGMT": DAY + "T12:00:00Z",
        "activityType": {"typeKey": "treadmill_running"},
        "distance": 3500,
        "elapsedDuration": 650,
    }
    (root / "row.json").write_text(json.dumps(row))
    (root / "synthetic.zip").write_bytes(
        runpy.run_path(str(BACKEND / "tests/fixtures/fit/synthetic.py"))[
            "build_synthetic_zip"
        ]()
    )


def exercise(request, mode, env):
    root = Path(env["PRIVATE_DIR"])
    results = []
    ids = {}

    def normalize(code, value):
        if "error" in value:
            value["error"].pop("request_id")
        else:
            assert value["mode"] == mode
            data = value["data"]
            if isinstance(data, dict):
                for job in data.get("jobs", []) + data.get("active_jobs", []):
                    raw = job["id"]
                    key = (job["dataset"], job["start_date"], job["end_date"])
                    assert ids.setdefault(key, raw) == raw
                    job["id"] = ":".join(str(item) for item in key)
                if (
                    "id" in data
                    and "dataset" in data
                    and data["id"] not in {JOB, LEGACY}
                ):
                    key = (data["dataset"], data["start_date"], data["end_date"])
                    assert data["id"] == ids[key]
                    data["id"] = ":".join(str(item) for item in key)

                if "activity_id" in data:
                    with connect(env) as db:
                        assert (
                            db.execute(
                                "SELECT id::text FROM activities WHERE garmin_id='1'"
                            ).fetchone()[0]
                            == data["activity_id"]
                        )
                    data["activity_id"] = "<saved>"
        results.append((code, value))
        return value.get("data", {})

    def send(method, path, body=None):
        return normalize(*request(method, BASE + path, body))

    for method, path, body in [
        ("GET", "/status", None),
        ("GET", "/jobs/" + JOB, None),
        ("GET", "/jobs/" + LEGACY, None),
        ("GET", "/jobs/" + INTERVAL, None),
        ("GET", "/jobs/xyz", None),
        ("POST", "", {"start_date": "invalid"}),
        ("POST", "", {"start_date": "2026-01-10", "end_date": "2025-01-10"}),
        ("POST", "", {"start_date": "2026-12-10"}),
        ("POST", "", {}),
        ("POST", "", {}),
        ("GET", "/treadmill-review/missing", None),
        ("POST", REVIEW, {}),
        ("POST", REVIEW, {"preview_token": "stale", "paces": []}),
    ]:
        send(method, path, body)
    if mode != "real":
        return results
    for raw in ids.values():
        send("GET", "/jobs/" + raw)
    row = json.loads((root / "row.json").read_text())
    for changed in (
        {"activityId": "different"},
        {"ownerId": "different"},
        {"activityType": {"typeKey": "running"}},
    ):
        (root / "row.json").write_text(json.dumps({**row, **changed}))
        send("GET", REVIEW)
    (root / "row.json").write_text(json.dumps(row))
    for remote in (429, 404):
        (root / "download_status").write_text(str(remote))
        response = send("GET", REVIEW)
        if remote == 404:
            assert response["intervals"] == [] and response["timer_s"] is None
            response["preview_token"] = "<missing-fit-preview>"
    (root / "download_status").unlink()
    data = send("GET", REVIEW)
    token = data.get("preview_token")
    if not token:
        raise AssertionError(data)
    data["preview_token"] = "<preview>"
    assert len(data["intervals"]) == 2
    for paces in (
        [{"lap_index": 8, "pace_seconds_per_mile": 380}],
        [{"lap_index": 0, "pace_seconds_per_mile": 455}] * 2,
    ):
        send("POST", REVIEW, {"preview_token": token, "paces": paces})
    valid = {
        "preview_token": token,
        "paces": [{"lap_index": "1", "pace_seconds_per_mile": "490"}],
    }
    before = persisted(env)
    with connect(env) as db:
        db.execute("""CREATE FUNCTION synthetic_refresh_failure() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN RAISE EXCEPTION 'synthetic metric refresh failure'; END $$""")
        db.execute("""CREATE TRIGGER synthetic_refresh_failure BEFORE INSERT ON metric_results
        FOR EACH ROW EXECUTE FUNCTION synthetic_refresh_failure()""")
    send("POST", REVIEW, valid)
    assert results[-1][0] == 500 and persisted(env) == before
    with connect(env) as db:
        db.execute("DROP TRIGGER synthetic_refresh_failure ON metric_results")
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [
            workers.submit(request, "POST", BASE + REVIEW, valid) for _ in range(2)
        ]
        responses = sorted(
            (task.result() for task in futures), key=lambda pair: pair[0]
        )
    assert responses[0][0] == 200 and responses[1][0] in {404, 409}, responses
    assert responses[1][1]["error"]["code"] in {
        "treadmill_review_not_found",
        "treadmill_review_reload_required",
    }
    normalize(*responses[0])
    send("POST", REVIEW, {"preview_token": token, "paces": []})
    send("GET", REVIEW)
    send("GET", "/status")
    return results


def python_ref():
    test_url()
    assert re.fullmatch(
        r"-csearch_path=go_parity_[0-9a-f]{32} -cTimeZone=Asia/Kathmandu",
        os.environ["PGOPTIONS"],
    )
    from app.adapters.garmin.personal import GarminRemoteError
    from app.api import responses
    from app.api import sync as api
    from app.main import app
    from app.metrics import refresh
    from app.services import sync, treadmill_review
    from fastapi.testclient import TestClient

    mode = os.environ["SYNC_ROUTE_MODE"]
    root = Path(os.environ["PRIVATE_DIR"])

    class Source:
        def pages(self, *_):
            yield 0, [json.loads((root / "row.json").read_text())]

        def download_activity(self, _):
            status = root / "download_status"
            if status.exists():
                raise GarminRemoteError(int(status.read_text()), None)
            return (root / "synthetic.zip").read_bytes()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    settings = SimpleNamespace(app_mode=mode, private_dir=root)
    with (
        patch.object(api, "settings", settings),
        patch.object(responses, "settings", settings),
        patch.object(treadmill_review, "datetime", Clock),
        patch.object(
            treadmill_review, "GarminPersonalSource", lambda *_: nullcontext(Source())
        ),
        patch.object(sync, "athlete_today", lambda _: NOW.date()),
        patch.object(refresh, "clock", lambda _: NOW),
        TestClient(app, base_url="http://localhost") as client,
    ):

        def send(method, path, body):
            resp = client.request(
                method, path, json=body, headers={"X-Local-Request": "1"}
            )
            return resp.status_code, resp.json()

        return exercise(send, mode, os.environ)


def persisted(env):
    with connect(env) as db:
        return [
            db.execute(sql).fetchall()
            for sql in (
                "SELECT garmin_id,fit_status,treadmill_interval_paces FROM activities ORDER BY 1",
                "SELECT lap_index,timer_s,avg_speed_mps FROM activity_laps ORDER BY 1",
                "SELECT status,reason,fully_enumerated FROM coverage_intervals ORDER BY 1",
                "SELECT checkpoint,counters FROM sync_jobs WHERE id='" + JOB + "'",
                "SELECT source_identity,payload_hash FROM source_records ORDER BY 1",
                "SELECT data_revision FROM app_state WHERE id=1",
                "SELECT metric_id,status,value FROM metric_results WHERE metric_id='run_volume_frequency' AND is_current ORDER BY subject_key",
            )
        ]


def run():
    url = test_url()
    with (
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as db,
    ):
        tmp = Path(tmp)
        binary = tmp / "sync-http"
        subprocess.run(
            ["go", "test", "-race", "-c", "-o", binary, "./internal/synchttp"],
            cwd=MODULE,
            check=True,
        )
        for mode in ("test", "real"):
            with (
                migrated_schema(db, url, tmp / ("py-" + mode), "5173") as py,
                migrated_schema(db, url, tmp / ("go-" + mode), "5173") as go,
            ):
                for env in (py, go):
                    seed(env)
                    env.update(
                        SYNC_ROUTE_MODE=mode,
                        SYNC_HTTP_FIXTURE="1",
                        PYTHONPATH=str(BACKEND),
                    )
                expected = json.loads(
                    subprocess.check_output(
                        [sys.executable, __file__, "reference"], env=py, text=True
                    ).splitlines()[-1]
                )
                with listener(
                    [binary, "-test.run=^TestHTTPFixture$"],
                    env=go,
                    stdout=subprocess.PIPE,
                    text=True,
                ) as proc:
                    with selectors.DefaultSelector() as sel:
                        sel.register(proc.stdout, selectors.EVENT_READ)
                        assert sel.select(30)
                    port = int(proc.stdout.readline().strip())

                    def send(method, path, body, port=port):
                        conn = HTTPConnection("127.0.0.1", port, timeout=30)
                        conn.request(
                            method,
                            path,
                            json.dumps(body) if body is not None else None,
                            {"Content-Type": "application/json"},
                        )
                        resp = conn.getresponse()
                        item = resp.status, json.load(resp)
                        conn.close()
                        return item

                    actual = exercise(send, mode, go)
                for i, (a, b) in enumerate(zip(expected, actual, strict=True)):
                    assert a == list(b), (i, a, b)
                assert persisted(py) == persisted(go), (persisted(py), persisted(go))
    print(
        "PASS Garmin sync HTTP mode gates, queue state, review confirmation, persisted lap paces, coverage and derived windows"
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["reference"]:
        print(json.dumps(python_ref()))
    else:
        run()
