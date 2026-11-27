"""Exercise the native Garmin job runner using synthetic HTTP and disposable schemas.

Run python3 scripts/test-db.py provider-jobs with Go on PATH.
"""

import base64
import io
import json
import runpy
import subprocess
import tempfile
import zipfile
from collections import Counter
from contextlib import contextmanager
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from time import sleep as wait
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import psycopg
from check_gcal_replay import connect, test_url
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema

FIRST = date(2026, 11, 10)
RANGES = {"activities": 1, "sleep": 8, "hrv": 1, "resting_hr": 2}
BASE_CLOCK = "2026-11-16T09:"


class SyntheticGarmin:
    def download_activity(self, remote_id):
        assert str(remote_id) in {"1050", "1052"}
        payload = runpy.run_path(str(BACKEND / "tests/fixtures/fit/synthetic.py"))[
            "build_synthetic_fit"
        ]()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr(zipfile.ZipInfo(f"synthetic-{remote_id}.fit"), payload)
        return archive.getvalue()

    def search_page(self, start, limit, first, last):
        assert first <= last and limit == 50
        return [
            {
                "ownerId": 777,
                "activityId": 1000 + i,
                "activityType": {
                    "typeKey": {
                        50: "running",
                        51: "treadmill_running",
                        52: "running",
                    }.get(i, "cycling")
                },
                "startTimeGMT": f"{FIRST}T12:{0 if i == 50 else i:02}:00Z",
                "distance": 1000 + i,
                "elapsedDuration": 300,
            }
            for i in range(start, min(start + limit, 53))
        ]

    def fetch_recovery(self, dataset, first, last):
        field, owner = {
            "sleep": ("sleepTimeSeconds", "userProfilePK"),
            "hrv": ("lastNightAvg", "userProfilePk"),
            "resting_hr": ("restingHeartRate", "userProfilePK"),
        }[dataset]
        rows = [
            {
                owner: 777,
                "calendarDate": (first + timedelta(days=i)).isoformat(),
                field: 40 + (first - FIRST).days + i,
            }
            for i in range((last - first).days + 1)
        ]
        if dataset == "sleep" and first == FIRST:
            rows.extend(
                [
                    {"calendarDate": first.isoformat(), field: 17},
                    dict(rows[0], **{field: None}),
                ]
            )
            rows.append(
                {"userProfilePK": 777, "calendarDate": first.isoformat(), field: -99}
            )
        return rows


def persisted(env):
    with connect(env) as db:
        statements = {
            "jobs": """SELECT dataset,status,start_date,end_date,checkpoint-'pending_coverage_id', checkpoint ? 'pending_coverage_id',
                counters,error_code,finished_at IS NOT NULL FROM sync_jobs ORDER BY dataset""",
            "state": """SELECT dataset,status,reason,requested_start,requested_end,newest_observation_at,
                fully_enumerated,last_success_at IS NOT NULL FROM sync_state ORDER BY dataset""",
            "coverage": """SELECT dataset,start_date,end_date,status,fully_enumerated,reason,observed_start,observed_end
                FROM coverage_intervals ORDER BY dataset,start_date""",
            "sources": """SELECT a.account_scope,s.source_identity,s.payload_hash,s.fields,s.parser_version,s.source_kind,
                s.rejected_reason,r.sha256,r.relative_path FROM source_records s JOIN raw_objects r ON r.id=s.raw_object_id
                JOIN source_accounts a ON a.id=s.source_account_id ORDER BY s.source_identity,s.payload_hash""",
            "activities": "SELECT garmin_id,sport,start_at,distance_m FROM activities ORDER BY garmin_id",
            "recovery": """SELECT o.metric,o.source_date,o.statistic,o.unit,o.value,o.time_semantics,s.payload_hash
                FROM recovery_observations o JOIN source_records s ON s.id=o.source_record_id ORDER BY 1,2""",
            "fit": """SELECT zip_sha256,fit_sha256,profile_version,decode_error,message_inventory,device,decoder_version
                FROM fit_files ORDER BY zip_sha256""",
            "run_metrics": """SELECT a.garmin_id,m.metric_id,m.method_version,m.status,m.quality_status,m.reason_codes,
                CASE WHEN m.metric_id='long_run_exposure' THEN m.value-'activity_id' ELSE NULL END
                FROM metric_results m JOIN activities a ON m.subject_key=a.id::text WHERE m.is_current
                AND m.subject_type='activity' ORDER BY 1,2""",
            "volume": """SELECT subject_key,status,value,quality_flags FROM metric_results WHERE is_current
                AND metric_id='run_volume_frequency' AND subject_type='window' ORDER BY 1""",
            "revision": "SELECT data_revision FROM app_state WHERE id=1",
            "batches": "SELECT status,source_kind,adapter_version,counters FROM import_batches ORDER BY started_at,id",
        }
        return {name: db.execute(sql).fetchall() for name, sql in statements.items()}


class Remote:
    def __init__(self):
        self.waiting = Event()
        self.release = Event()
        self.block_offset = True
        self.requests = Counter()
        self.source = SyntheticGarmin()

    def reply(self, method, path, query, auth):
        self.requests[path] += 1
        if method == "POST":
            assert (
                path.endswith("/personal-api-key/token")
                and auth == "ApiKey synthetic-provider-jobs"
            )
            claims = base64.urlsafe_b64encode(b'{"exp":4102444800}').rstrip(b"=")
            return 200, b"fixture." + claims + b".synthetic", {}
        assert auth.startswith("Bearer fixture.")
        if "/files/activity/" in path:
            return 200, self.source.download_activity(path.rsplit("/", 1)[1]), {}
        if path.endswith("/activities/search/activities"):
            offset = int(query["start"][0])
            self.requests[f"offset:{offset}"] += 1
            if offset == 50 and self.block_offset:
                self.block_offset = False
                self.waiting.set()
                assert self.release.wait(30)
            return (
                200,
                self.source.search_page(offset, int(query["limit"][0]), FIRST, FIRST),
                {},
            )
        if path.endswith("/dailySleepSummariesByDate"):
            if self.requests[path] == 1:
                return 429, {}, {"Retry-After": "65"}
            start, end = (
                date.fromisoformat(query[k][0]) for k in ("startDate", "endDate")
            )
            return 200, self.source.fetch_recovery("sleep", start, end), {}
        if "/hrv-service/" in path:
            if self.requests[path] == 1:
                return 503, {}, {"Retry-After": "1"}
            first, last = map(date.fromisoformat, path.split("/")[-2:])
            rows = self.source.fetch_recovery("hrv", first, last)
            for row in rows:
                del row["userProfilePk"]
            return 200, {"userProfilePk": 777, "hrvSummaries": rows}, {}
        assert path.endswith("/dailyHeartRate")
        day = date.fromisoformat(query["date"][0])
        return 200, self.source.fetch_recovery("resting_hr", day, day)[0], {}


@contextmanager
def endpoint(remote):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            target = urlsplit(self.path)
            code, data, headers = remote.reply(
                self.command,
                target.path,
                parse_qs(target.query),
                self.headers.get("Authorization"),
            )
            body = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(code)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (ConnectionResetError, BrokenPipeError):
                pass  # The first worker was deliberately killed after page one.

        do_POST = do_GET

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            remote.release.set()
            server.shutdown()
            thread.join()


def failure_coverage(go, remote, enqueue, task, argv):
    with connect(go) as db:

        def revision():
            return db.execute(
                "SELECT data_revision FROM app_state WHERE id=1"
            ).fetchone()[0]

        def failed_interval(job):
            return db.execute(
                """
                SELECT j.status,j.error_code,c.status,c.reason,c.fully_enumerated,c.completed_at,
                       s.status,s.reason,s.fully_enumerated
                FROM sync_jobs j JOIN sync_state s ON j.dataset=s.dataset
                JOIN coverage_intervals c ON j.dataset=c.dataset AND c.reason=j.error_code
                WHERE j.id=%s""",
                (job,),
            ).fetchone()

        job = enqueue("sleep")
        before = revision()
        with patch.object(
            remote, "reply", return_value=(429, {}, {"Retry-After": "60"})
        ):
            for minute in (10, 12, 14):
                assert task(*argv(minute))["status"] == "retry_wait"
                assert revision() == before
            assert task(*argv(16))["status"] == "failed"
        assert db.execute(
            "SELECT checkpoint->>'attempts' FROM sync_jobs WHERE id=%s", (job,)
        ).fetchone() == ("3",)
        expected = (
            "failed",
            "remote_or_import_error",
            "failed",
            "remote_or_import_error",
            False,
            None,
            "failed",
            "remote_or_import_error",
            False,
        )
        assert failed_interval(job) == expected and revision() == before + 1

        # Fail after importing a changed observation. Both the revisioned source and its
        # winning projection must roll back with the checkpoint and receipt.
        job = enqueue("hrv")
        before = revision()
        batches = db.execute("SELECT count(*) FROM import_batches").fetchone()
        sources = db.execute("SELECT count(*) FROM source_records").fetchone()[0]

        def observed():
            return db.execute(
                "SELECT value,source_record_id FROM recovery_observations WHERE metric='hrv' AND source_date=%s",
                (FIRST,),
            ).fetchone()

        original = observed()
        original_reply = remote.reply

        def corrected(method, path, query, auth):
            status, data, headers = original_reply(method, path, query, auth)
            if "/hrv-service/" in path and status == 200:
                data["hrvSummaries"][0]["lastNightAvg"] = 78
            return status, data, headers

        with patch.object(remote, "reply", side_effect=corrected):
            db.execute("""CREATE FUNCTION reject_job_checkpoint() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF NEW.checkpoint IS DISTINCT FROM OLD.checkpoint THEN
                    RAISE EXCEPTION 'synthetic checkpoint failure'; END IF; RETURN NEW; END $$;
                CREATE TRIGGER reject_job_checkpoint BEFORE UPDATE ON sync_jobs
                FOR EACH ROW EXECUTE FUNCTION reject_job_checkpoint()""")
            try:
                assert task(*argv(18))["status"] == "failed"
            finally:
                db.execute("DROP TRIGGER reject_job_checkpoint ON sync_jobs")
            assert (
                db.execute("SELECT count(*) FROM import_batches").fetchone() == batches
            )
            assert (
                db.execute("SELECT count(*) FROM source_records").fetchone()[0]
                == sources
            )
            assert observed() == original
            assert db.execute(
                "SELECT checkpoint FROM sync_jobs WHERE id=%s", (job,)
            ).fetchone() == ({"offset": 0},)
            assert failed_interval(job) == expected and revision() == before + 1
            enqueue("hrv")
            assert task(*argv(20))["status"] == "complete"
            assert (
                db.execute("SELECT count(*) FROM source_records").fetchone()[0]
                == sources + 1
            )
            value, source = observed()
            assert value == 78 and source != original[1]


def scenario(binary, go):
    remote = Remote()
    with endpoint(remote) as url:
        env = dict(
            go,
            GARMIN_PERSONAL_API_BASE_URL=url,
            RECORD_FIXTURE_REFRESH="1",
            GORACE="atexit_sleep_ms=0",
            PGOPTIONS=go["PGOPTIONS"] + " -cdefault_transaction_read_only=on",
        )

        Path(go["PRIVATE_DIR"]).chmod(0o700)

        def task(*args):
            return json.loads(
                subprocess.check_output([binary, *args], env=env, text=True)
            )

        def enqueue(dataset):
            return task(
                "-dataset",
                dataset,
                "-start",
                FIRST.isoformat(),
                "-end",
                (FIRST + timedelta(days=RANGES[dataset] - 1)).isoformat(),
                "enqueue",
            )["id"]

        def argv(minute=0):
            return ["-now", BASE_CLOCK + f"{minute:02}:00Z", "run"]

        with connect(go) as db:
            db.execute("CREATE TABLE fixture_provider_refresh(scope jsonb NOT NULL)")
        job = enqueue("activities")
        assert enqueue("activities") == job
        with subprocess.Popen(
            [binary, *argv()], env=env, stdout=subprocess.PIPE
        ) as worker:
            try:
                if not remote.waiting.wait(30):
                    with connect(go) as db:
                        progress = db.execute(
                            "SELECT status,error_code,checkpoint FROM sync_jobs WHERE id=%s",
                            (job,),
                        ).fetchone()
                    raise AssertionError(
                        (
                            "first page did not commit",
                            worker.poll(),
                            dict(remote.requests),
                            progress,
                        )
                    )
                assert task(*argv())["status"] == "", (
                    "another worker claimed a running job"
                )
                with connect(go) as db:
                    assert db.execute(
                        "SELECT checkpoint->>'offset',status FROM sync_jobs WHERE id=%s",
                        (job,),
                    ).fetchone() == ("50", "running")
                    assert db.execute("SELECT count(*) FROM activities").fetchone() == (
                        50,
                    )
                    assert db.execute(
                        "SELECT count(*) FROM coverage_intervals"
                    ).fetchone() == (0,)
            finally:
                worker.kill()
                worker.wait()
                remote.release.set()
        assert task(*argv())["status"] == "complete"
        assert remote.requests["offset:0"] == 1 and remote.requests["offset:50"] == 2
        sleep = enqueue("sleep")
        assert task(*argv())["status"] == "retry_wait"
        with connect(go) as db:
            assert db.execute(
                "SELECT error_code,checkpoint->>'attempts' FROM sync_jobs WHERE id=%s",
                (sleep,),
            ).fetchone() == ("remote_retry", "1")
        assert task(*argv())["status"] == ""
        assert task(*argv(2))["status"] == "partial"
        for dataset in ("hrv", "resting_hr"):
            enqueue(dataset)
            assert task(*argv(2))["status"] == "complete"
        assert (
            sum(n for path, n in remote.requests.items() if "/hrv-service/" in path)
            == 2
        )
        assert (
            sum(
                n
                for path, n in remote.requests.items()
                if path.endswith("/personal-api-key/token")
            )
            == 1
        )
        actual = persisted(go)
        assert actual["run_metrics"] and actual["volume"]
        assert {row[3] for row in actual["fit"]} == {None, "FIT_START_MISMATCH"}
        with connect(go) as db:
            scopes = [
                r[0] for r in db.execute("SELECT scope FROM fixture_provider_refresh")
            ]
            coverage = {
                str(r[0]) for r in db.execute("SELECT id FROM coverage_intervals")
            }
            assert {i for s in scopes for i in s["CoverageIDs"] or []} == coverage
            activities = {i for s in scopes for i in s["Activities"] or {}}
            expected_ids = {str(r[0]) for r in db.execute("SELECT id FROM activities")}
            assert activities == expected_ids
            fit_id = str(
                db.execute(
                    "SELECT activity_id FROM fit_files WHERE decoded_at IS NOT NULL LIMIT 1"
                ).fetchone()[0]
            )
            assert sum(fit_id in (s["Activities"] or {}) for s in scopes) >= 2
            assert any(s["RecoveryDates"] and not s["Activities"] for s in scopes)
        assert len(actual["activities"]) == 52 and len(actual["recovery"]) == 11
        assert sorted((row[0], row[3]) for row in actual["coverage"]) == [
            ("activities", "partial"),
            ("hrv", "complete"),
            ("resting_hr", "complete"),
            ("sleep", "partial"),
        ]
        # The daemon catches up completed datasets through the athlete's local day,
        # leaves today's partial jobs alone, then waits until cancelled.
        with subprocess.Popen(
            [binary, "-now", BASE_CLOCK + "03:00Z", "worker"], env=env
        ) as daemon:
            try:
                deadline = monotonic() + 30
                with connect(go) as db:
                    while monotonic() < deadline:
                        count = db.execute(
                            "SELECT count(*) FROM sync_jobs WHERE dataset IN ('hrv','resting_hr') "
                            "AND end_date='2026-11-16' AND status='complete'"
                        ).fetchone()[0]
                        if count == 2:
                            break
                        assert daemon.poll() is None, (
                            "worker exited before catch-up completed"
                        )
                        wait(0.05)
                    else:
                        raise AssertionError("worker did not finish catch-up")
            finally:
                daemon.terminate()
                assert daemon.wait(timeout=5) == 0
        failure_coverage(go, remote, enqueue, task, argv)
        lines = subprocess.check_output(
            [
                binary,
                "-start",
                FIRST.isoformat(),
                "-end",
                FIRST.isoformat(),
                *argv(22)[:-1],
                "sync",
            ],
            env=env,
            text=True,
        ).splitlines()
        assert (
            len(json.loads(lines[0])["job_ids"])
            == len(json.loads(lines[1])["results"])
            == 4
        )
    print(
        "PASS four provider jobs on PostgreSQL, process interruption, concurrent claim, 429/503 retry and coverage"
    )


def main():
    url = test_url()
    with (
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
    ):
        folder = Path(tmp)
        binary = folder / "provider-jobs"
        subprocess.run(
            ["go", "build", "-race", "-o", binary, "./cmd/provider-jobs"],
            cwd=MODULE,
            check=True,
        )
        with migrated_schema(db, url, folder / "native", "5173") as go:
            subprocess.run(
                [
                    "go",
                    "test",
                    "-race",
                    "-run",
                    "^TestCoverageDelta$",
                    "./internal/garmincli",
                ],
                cwd=MODULE,
                env=go,
                check=True,
            )
            scenario(binary, go)


if __name__ == "__main__":
    main()
