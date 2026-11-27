"""Compare Garmin export preview, apply and replay using disposable schemas."""

import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import psycopg

from check_gcal_replay import connect, test_url
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema


def fixture(path):
    activities = [
        {
            "activityId": 1234,
            "userProfileId": 777,
            "activityType": "running",
            "startTimeGmt": 1794556800000,
            "distance": 100000,
            "elapsedDuration": 300000,
        }
    ]
    sleep = {
        "calendarDate": "2026-11-13",
        "sleepStartTimestampGMT": "2026-11-12T23:00:00",
        "sleepEndTimestampGMT": "2026-11-13T07:00:00Z",
        "awakeSleepSeconds": 90,
        "napList": [{"minutes": 20}],
    }
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as z:
        for name, rows in {
            "summarizedActivities.json": [{"summarizedActivitiesExport": activities}],
            "recovery/2026-11-10_2026-11-15_777_sleepData.json": [sleep, None, {}],
            "recovery/2026-11-10_2026-11-15_777_healthStatusData.json": [
                {
                    "calendarDate": "2026-11-13",
                    "metrics": [{"type": "HRV", "value": 60}, {"type": "other"}],
                },
                {"calendarDate": "2026-11-14", "metrics": []},
            ],
            "recovery/UDSFile_2026-11-10_2026-11-15.json": [
                {
                    "calendarDate": "2026-11-13",
                    "userProfilePK": 777,
                    "restingHeartRate": 55,
                },
                {
                    "calendarDate": "2026-11-14",
                    "userProfilePK": 777,
                    "restingHeartRate": 0,
                },
            ],
            "other/unsupported.json": [{"untouched": True}],
        }.items():
            z.writestr(name, json.dumps(rows, ensure_ascii=False).encode())


def reference():
    from app import strong_models  # noqa: F401
    from app.db import SessionLocal
    from app.services.export_import import import_export
    from app.services.sync import import_activity_page, import_recovery_page

    root = Path(os.environ["PRIVATE_DIR"])
    with SessionLocal.begin() as session:
        if sys.argv[1] == "seed":
            row = {
                "activityId": 1234,
                "ownerId": 777,
                "activityType": {"typeKey": "running"},
                "startTimeGMT": "2026-11-13T08:00:00Z",
                "distance": 2000,
                "elapsedDuration": 300,
            }
            import_activity_page(session, root, [row], account_scope="auto")
            import_recovery_page(
                session,
                root,
                "hrv",
                [
                    {
                        "userProfilePk": 777,
                        "calendarDate": "2026-11-13",
                        "lastNightAvg": 74,
                    }
                ],
                fetched_at=datetime(2026, 11, 13, tzinfo=UTC),
            )
        else:
            result = import_export(
                session,
                root,
                Path(os.environ["EXPORT_FIXTURE"]),
                apply=os.environ["EXPORT_APPLY"] == "1",
            )
            (root / "fixture-result.json").write_text(json.dumps(result))


def snapshot(env):
    with connect(env) as db:
        return [
            db.execute(q).fetchall()
            for q in (
                "SELECT account_scope FROM source_accounts ORDER BY 1",
                "SELECT garmin_id,distance_m,start_at,elapsed_s FROM activities ORDER BY 1",
                "SELECT relative_path,sha256,byte_size,media_type FROM raw_objects ORDER BY 1",
                """SELECT s.source_identity,s.payload_hash,s.source_kind,s.parser_version,s.fields,s.rejected_reason,r.sha256
            FROM source_records s JOIN raw_objects r ON s.raw_object_id=r.id ORDER BY 1,2""",
                """SELECT metric,source_date,value,unit,statistic,time_semantics,source_revision FROM recovery_observations ORDER BY 1,2""",
                "SELECT dataset,start_date,end_date,observed_start,observed_end,fully_enumerated,status,reason FROM coverage_intervals ORDER BY 1",
                "SELECT source_kind,status,adapter_version,counters FROM import_batches ORDER BY started_at,id",
                "SELECT data_revision FROM app_state WHERE id=1",
            )
        ]


def run():
    url = test_url()
    pg_url = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with (
        psycopg.connect(pg_url, autocommit=True) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
    ):
        scratch = Path(tmp)
        archive = scratch / "synthetic.zip"
        fixture(archive)
        binary = scratch / "export-test"
        subprocess.run(
            ["go", "test", "-race", "-c", "-o", binary, "./internal/exportcli"],
            cwd=MODULE,
            check=True,
        )
        with (
            migrated_schema(db, url, scratch / "py", "5173") as py,
            migrated_schema(db, url, scratch / "go", "5173") as go,
        ):
            for env in (py, go):
                env.update(
                    EXPORT_FIXTURE=str(archive),
                    PYTHONPATH=str(BACKEND),
                    GORACE="atexit_sleep_ms=0",
                )
                subprocess.run([sys.executable, __file__, "seed"], env=env, check=True)
            for apply in (False, True, True):
                before = snapshot(go)
                raw = lambda env: {
                    p.relative_to(Path(env["PRIVATE_DIR"]) / "raw"): p.read_bytes()
                    for p in (Path(env["PRIVATE_DIR"]) / "raw").rglob("*")
                    if p.is_file()
                }
                files = raw(go)
                for env in (py, go):
                    env["EXPORT_APPLY"] = str(int(apply))
                subprocess.run([sys.executable, __file__, "ref"], env=py, check=True)
                subprocess.run(
                    [binary, "-test.run", "^TestExportFixture$"], env=go, check=True
                )
                a, b = (
                    json.loads(
                        (Path(e["PRIVATE_DIR"]) / "fixture-result.json").read_text()
                    )
                    for e in (py, go)
                )
                assert a == b, (a, b)
                expected, got = snapshot(py), snapshot(go)
                for i, (x, y) in enumerate(zip(expected, got, strict=True)):
                    assert x == y, (i, x, y)
                assert raw(py) == raw(go)
                if not apply:
                    assert before == got and files == raw(go)
            assert a["replayed"] and a["status"] == "partial"
            assert a["recovery"] == {"sleep": 1, "resting_hr": 1, "hrv": 1}
    print(
        "PASS Garmin export preflight, shared API precedence, three recovery datasets and byte-identical replay"
    )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        reference()
    else:
        run()
