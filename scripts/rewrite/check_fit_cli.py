"""Exercise native FIT maintenance with synthetic files and PostgreSQL."""

import json
import runpy
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import psycopg
from check_gcal_replay import connect, test_url
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema

DAY = "2026-11-10"


def seed(env, scratch):
    manifest = scratch / "fit-summaries.json"
    manifest.write_text(
        json.dumps(
            {
                "account_scope": "auto",
                "job_id": str(uuid4()),
                "fetched_at": "2026-11-16T09:00:00Z",
                "activities": [
                    {
                        "activityId": str(i),
                        "ownerId": "99",
                        "startTimeGMT": DAY + "T12:00:00Z",
                        "activityType": {"typeKey": "running" if i < 8 else "cycling"},
                        "distance": 1000,
                        "elapsedDuration": 700,
                    }
                    for i in range(1, 9)
                ],
            }
        )
    )
    subprocess.run(
        ["go", "run", "./cmd/garmin-replay", "-page", manifest],
        cwd=MODULE,
        env=env,
        stdout=subprocess.DEVNULL,
        check=True,
    )
    with connect(env) as db:
        db.execute(
            "DELETE FROM activity_sources WHERE activity_id=(SELECT id FROM activities WHERE garmin_id='6')"
        )
        db.execute("""INSERT INTO activity_sources(id,activity_id,source_record_id,selected_fields)
            SELECT gen_random_uuid(),a.id,s.id,'[]' FROM activities a,source_records s
            WHERE a.garmin_id='7' AND s.source_identity='garmin:5'""")


def snapshot(env):
    with connect(env) as db:
        return [
            db.execute(sql).fetchall()
            for sql in (
                "SELECT a.garmin_id,a.fit_status,a.canonical_revision,a.timer_s,a.end_at,f.decoder_version,f.last_error,f.decode_error,f.message_inventory,f.fit_sha256 FROM activities a LEFT JOIN fit_files f ON f.activity_id=a.id ORDER BY 1",
                "SELECT a.garmin_id,l.lap_index,l.intensity,l.end_at FROM activity_laps l JOIN activities a ON a.id=l.activity_id ORDER BY 1,2",
                "SELECT metric_id,subject_key,status,value FROM metric_results WHERE metric_id='run_volume_frequency' AND is_current ORDER BY 2",
                "SELECT data_revision FROM app_state WHERE id=1",
                "SELECT sha256,byte_size,media_type FROM raw_objects ORDER BY 1",
            )
        ]


def run():
    url = test_url()
    with (
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as conn,
    ):
        temp = Path(tmp)
        binary = temp / "fixture"
        subprocess.run(
            ["go", "test", "-race", "-c", "-o", binary, "./internal/garmincli"],
            cwd=MODULE,
            check=True,
        )
        with migrated_schema(conn, url, temp / "native", "5173") as go:
            builder = runpy.run_path(str(BACKEND / "tests/fixtures/fit/synthetic.py"))
            payload = builder["build_synthetic_fit"]()
            go["GORACE"] = "atexit_sleep_ms=0"
            for rid in ("1", "2"):
                (Path(go["PRIVATE_DIR"]) / f"{rid}.zip").write_bytes(
                    builder["build_synthetic_zip"]({f"{rid}.fit": payload})
                )
            seed(go, temp)

            def invoke(args, uid=None):
                argv = args.copy()
                if uid:
                    with connect(go) as db:
                        (uid,) = db.execute(
                            "SELECT id FROM activities WHERE garmin_id=%s", (uid,)
                        ).fetchone()
                    argv += ["--activity-id", str(uid)]
                subprocess.run(
                    [binary, "-test.run=^TestFITCommandFixture$"],
                    env={**go, "FIT_CLI_ARGS": json.dumps(argv)},
                    check=True,
                )
                return json.loads((Path(go["PRIVATE_DIR"]) / "result.json").read_text())

            counts = invoke(["fit-backfill", "--since", DAY])
            assert counts == {
                "attempted": 7,
                "decoded": 2,
                "unavailable": 1,
                "failed": 4,
            }, counts
            activities, laps, metrics, _, raw = snapshot(go)
            assert [row[0] for row in activities if row[1] == "decoded"] == ["1", "2"]
            assert len(laps) == 4 and metrics and raw
            with connect(go) as db:
                db.execute(
                    "UPDATE fit_files SET decoder_version=1 WHERE decoded_at IS NOT NULL"
                )
                db.execute("UPDATE activity_laps SET intensity=NULL")
            baseline = snapshot(go)
            result = invoke(["fit-reprocess", "--since", DAY])
            assert result["reprocessed"] == 2 and snapshot(go) == baseline
            assert invoke(["fit-reprocess", "--since", "2027-01-01"])["selected"] == 0
            assert (
                invoke(["fit-reprocess", "--since", "2027-01-01", "--apply"], "1")[
                    "reprocessed"
                ]
                == 1
            )
            assert (
                invoke(["fit-reprocess", "--since", DAY, "--apply"])["reprocessed"] == 1
            )
            assert invoke(["fit-reprocess", "--since", DAY, "--apply"])["selected"] == 0
            with connect(go) as db:
                db.execute(
                    "UPDATE fit_files SET decoder_version=NULL WHERE decoded_at IS NOT NULL"
                )
                paths = db.execute(
                    """SELECT DISTINCT r.relative_path FROM raw_objects r JOIN fit_files f
                    ON f.raw_object_id=r.id WHERE f.decoded_at IS NOT NULL"""
                ).fetchall()
            for (path,) in paths:
                (Path(go["PRIVATE_DIR"]) / path).unlink()
            assert invoke(["fit-reprocess", "--since", DAY, "--apply"])["errors"] == {
                "raw_missing": 2
            }
    print(
        "PASS FIT backfill, source ID resolution, retained FIT preview, targeted apply, idempotency, missing raw files and native derived windows"
    )


if __name__ == "__main__":
    run()
