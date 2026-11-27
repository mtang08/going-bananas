"""Exercise native Garmin queue and treadmill HTTP against synthetic PostgreSQL."""

import json
import runpy
import selectors
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from pathlib import Path

import psycopg
from check_gcal_replay import connect, test_url
from test_proposal_slice import BACKEND, MODULE, ROOT, listener, migrated_schema

DAY = "2026-11-10"
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

    def send(method, path, body=None, *, status=200, error=None):
        code, value = request(method, BASE + path, body)
        assert code == status, (method, path, code, value)
        if error is not None:
            issue = value["error"]
            assert issue["code"] == error and issue["request_id"], issue
            return issue
        assert value["mode"] == mode and value["schema_version"] == "v1"
        with connect(env) as db:
            (revision,) = db.execute(
                "SELECT data_revision FROM app_state WHERE id=1"
            ).fetchone()
        assert value["data_revision"] == revision
        return value["data"]

    first = send("GET", "/status")
    assert first["pending_treadmill_runs"] == [{"id": "1", "local_date": DAY}]
    assert [job["id"] for job in first["active_jobs"]] == [LEGACY]
    current = send("GET", "/jobs/" + JOB)
    assert current["status"] == "complete" and current["checkpoint"] == {"offset": 50}
    prior = send("GET", "/jobs/" + LEGACY)
    assert prior["status"] == "retry_wait" and prior["checkpoint"] == {"page": 3}
    assert prior["next_attempt_at"].endswith("+05:45")
    send("GET", "/jobs/" + INTERVAL, status=404, error="job_not_found")
    send("GET", "/jobs/xyz", status=422, error="validation_error")
    for body in (
        {"start_date": "invalid"},
        {"start_date": "2026-01-10", "end_date": "2025-01-10"},
    ):
        send("POST", "", body, status=422, error="validation_error")
    send("POST", REVIEW, {}, status=422, error="validation_error")
    if mode == "test":
        for body in ({"start_date": "2026-12-10"}, {}, {}):
            send("POST", "", body, status=409, error="real_mode_required")
        send("GET", REVIEW, status=409, error="real_mode_required")
        send(
            "POST",
            REVIEW,
            {"preview_token": "stale", "paces": []},
            status=409,
            error="real_mode_required",
        )
        assert send("GET", "/status") == first
        return
    send(
        "POST", "", {"start_date": "2026-12-10"}, status=422, error="invalid_sync_range"
    )
    jobs = send("POST", "", {}, status=202)["jobs"]
    assert {job["dataset"] for job in jobs} == {
        "activities",
        "sleep",
        "resting_hr",
        "hrv",
    }
    assert send("POST", "", {}, status=202)["jobs"] == jobs
    for job in jobs:
        assert send("GET", "/jobs/" + job["id"]) == job
    send(
        "GET",
        "/treadmill-review/missing",
        status=404,
        error="treadmill_review_not_found",
    )
    send(
        "POST",
        REVIEW,
        {"preview_token": "stale", "paces": []},
        status=409,
        error="treadmill_review_reload_required",
    )
    row = json.loads((root / "row.json").read_text())
    for changed, status, error in (
        ({"activityId": "different"}, 502, "treadmill_summary_unavailable"),
        ({"ownerId": "different"}, 502, "treadmill_review_unavailable"),
        ({"activityType": {"typeKey": "running"}}, 409, "treadmill_summary_changed"),
    ):
        (root / "row.json").write_text(json.dumps({**row, **changed}))
        send("GET", REVIEW, status=status, error=error)
    (root / "row.json").write_text(json.dumps(row))
    (root / "download_status").write_text("429")
    send("GET", REVIEW, status=502, error="treadmill_review_unavailable")
    (root / "download_status").write_text("404")
    unavailable_fit = send("GET", REVIEW)
    assert unavailable_fit["intervals"] == [] and unavailable_fit["timer_s"] is None
    (root / "download_status").unlink()
    data = send("GET", REVIEW)
    token = data["preview_token"]
    assert token and token != unavailable_fit["preview_token"]
    assert len(data["intervals"]) == 2 and data["timer_s"] > 0
    for paces, error in (
        ([{"lap_index": 8, "pace_seconds_per_mile": 380}], "treadmill_lap_invalid"),
        ([{"lap_index": 0, "pace_seconds_per_mile": 455}] * 2, "validation_error"),
    ):
        send(
            "POST",
            REVIEW,
            {"preview_token": token, "paces": paces},
            status=422,
            error=error,
        )
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
    send("POST", REVIEW, valid, status=500, error="internal_error")
    assert persisted(env) == before
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
    saved = responses[0][1]
    assert saved["mode"] == mode
    with connect(env) as db:
        (activity_id,) = db.execute(
            "SELECT id::text FROM activities WHERE garmin_id='1'"
        ).fetchone()
    assert saved["data"] == {"activity_id": activity_id}
    activities, laps, coverage, checkpoints, sources, revisions, metrics = persisted(
        env
    )
    assert len(activities) == 1 and activities[0][0:2] == ("1", "decoded")
    paces = activities[0][2]
    assert set(paces) == {"1"} and paces["1"]["pace_s_per_mile"] == 490
    assert paces["1"]["lap_identity"] and [row[0] for row in laps] == [0, 1]
    assert coverage == [("complete", None, True)]
    checkpoint, counters = checkpoints[0]
    assert not checkpoint.get("pending_treadmill") and counters["changed"] == 1
    assert sources and metrics
    assert revisions == [(saved["data_revision"],)]
    assert saved["data_revision"] == before[5][0][0] + 1
    send(
        "POST",
        REVIEW,
        {"preview_token": token, "paces": []},
        status=409,
        error="treadmill_review_reload_required",
    )
    send("GET", REVIEW, status=404, error="treadmill_review_not_found")
    assert send("GET", "/status")["pending_treadmill_runs"] == []
    assert persisted(env) == [
        activities,
        laps,
        coverage,
        checkpoints,
        sources,
        revisions,
        metrics,
    ]


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
            with migrated_schema(db, url, tmp / mode, "5173") as env:
                seed(env)
                env.update(SYNC_ROUTE_MODE=mode, SYNC_HTTP_FIXTURE="1")
                with listener(
                    [binary, "-test.run=^TestHTTPFixture$"],
                    env=env,
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

                    exercise(send, mode, env)
    print(
        "PASS Garmin sync HTTP mode gates, queue state, review confirmation, persisted lap paces, coverage and derived windows"
    )


if __name__ == "__main__":
    run()
