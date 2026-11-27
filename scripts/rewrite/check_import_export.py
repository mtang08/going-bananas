"""Exercise Garmin export preview, apply and replay using native PostgreSQL."""

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import psycopg
from check_gcal_replay import connect, test_url
from test_proposal_slice import MODULE, ROOT, migrated_schema


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
                """SELECT subject_key,status,value,quality_flags FROM metric_results WHERE is_current
                AND metric_id='run_volume_frequency' AND subject_type='window' ORDER BY 1""",
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
        with migrated_schema(db, url, scratch / "native", "5173") as go:
            go.update(EXPORT_FIXTURE=str(archive), GORACE="atexit_sleep_ms=0")
            with connect(go) as conn:
                conn.execute(
                    "CREATE TABLE fixture_export_refresh(scope jsonb NOT NULL)"
                )
            subprocess.run(
                [binary, "-test.run", "^TestExportFixture$"],
                env={**go, "EXPORT_SEED": "1"},
                check=True,
            )
            root = Path(go["PRIVATE_DIR"])

            def raw():
                return {
                    p.relative_to(root / "raw"): p.read_bytes()
                    for p in (root / "raw").rglob("*")
                    if p.is_file()
                }

            initial, initial_files = snapshot(go), raw()
            for phase, apply in (("preview", False), ("apply", True), ("replay", True)):
                go["EXPORT_APPLY"] = str(int(apply))
                subprocess.run(
                    [binary, "-test.run", "^TestExportFixture$"], env=go, check=True
                )
                summary = json.loads((root / "fixture-result.json").read_text())
                stored = snapshot(go)
                files = raw()
                if phase == "preview":
                    assert initial == stored and initial_files == files
                elif phase == "apply":
                    assert stored[1][0][1] == 2000 and len(stored[1]) == 1
                    measurements = {row[0]: row[2] for row in stored[4]}
                    assert (
                        measurements["hrv"] == 74 and measurements["resting_hr"] == 55
                    )
                    assert len(stored[5]) == 4 and stored[-1]
                    assert stored[7][0][0] == initial[7][0][0] + 1
                    assert not summary.get("replayed")
                    for relative, digest, size, _ in stored[2]:
                        data = files[Path(relative).relative_to("raw")]
                        assert (
                            len(data) == size
                            and hashlib.sha256(data).hexdigest() == digest
                        )
                    applied, applied_files = stored, files
                else:
                    assert summary["replayed"] and applied_files == files
                    assert applied[:6] == stored[:6] and applied[7:] == stored[7:]
                    assert stored[6][:-1] == applied[6]
                    assert stored[6][-1][:3] == (
                        "garmin_export",
                        "partial",
                        "garmin-export-v1",
                    )
                    receipt = stored[6][-1][3]
                    assert (
                        receipt["archive_sha256"]
                        == hashlib.sha256(archive.read_bytes()).hexdigest()
                    )
                    assert receipt["activities"]["new_revisions"] == 0
            with connect(go) as conn:
                scopes = conn.execute(
                    "SELECT scope FROM fixture_export_refresh"
                ).fetchall()
                assert len(scopes) == 1
                scope = scopes[0][0]
                assert len(scope["CoverageIDs"]) == 4 and len(scope["Activities"]) == 1
                assert scope["RecoveryDates"] == ["2026-11-13"]
            assert summary["status"] == "partial"
            assert summary["recovery"] == {"sleep": 1, "resting_hr": 1, "hrv": 1}
    print(
        "PASS Garmin export preflight, shared API precedence, three recovery datasets and byte-identical replay"
    )


if __name__ == "__main__":
    run()
