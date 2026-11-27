"""Compare native FIT maintenance and Python over synthetic files and disposable schemas."""

import json
import os
import runpy
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg
from check_gcal_replay import connect, test_url
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema

NOW = datetime(2026, 11, 16, 9, tzinfo=UTC)
DAY = "2026-11-10"


def reference():
    from app.db import SessionLocal
    from app.services import derived, fit_ingest, sync
    from app.metrics import refresh
    from sqlalchemy import text

    root = Path(os.environ["PRIVATE_DIR"])
    if sys.argv[1] == "seed":
        with SessionLocal.begin() as s:
            rows = [
                {
                    "activityId": str(i),
                    "ownerId": "99",
                    "startTimeGMT": DAY + "T12:00:00Z",
                    "activityType": {"typeKey": "running" if i < 8 else "cycling"},
                    "distance": 1000,
                    "elapsedDuration": 700,
                }
                for i in range(1, 9)
            ]
            sync.import_activity_page(s, root, rows, account_scope="auto")
            s.execute(
                text(
                    "DELETE FROM activity_sources WHERE activity_id=(SELECT id FROM activities WHERE garmin_id='6')"
                )
            )
            s.execute(
                text(
                    "INSERT INTO activity_sources(id,activity_id,source_record_id,selected_fields) SELECT gen_random_uuid(),a.id,s.id,'[]' FROM activities a,source_records s WHERE a.garmin_id='7' AND s.source_identity='garmin:5'"
                )
            )
        return
    derived.install()
    refresh.clock = lambda _session: NOW
    from app.adapters.garmin.personal import GarminRemoteError

    class Source:
        def download_activity(self, rid):
            if rid == "3":
                raise GarminRemoteError(404, None)
            if rid == "4":
                return b"invalid archive"
            if rid not in ("1", "2"):
                raise GarminRemoteError(503, None)
            return (root / f"{rid}.zip").read_bytes()

    args = json.loads(os.environ["FIT_CLI_ARGS"])
    since = date.fromisoformat(args[args.index("--since") + 1])
    if args[0] == "fit-backfill":
        result = fit_ingest.backfill_fit(SessionLocal, Source(), root, since)
    else:
        from uuid import UUID

        uid = (
            UUID(args[args.index("--activity-id") + 1])
            if "--activity-id" in args
            else None
        )
        apply = "--apply" in args
        with SessionLocal() as s:
            result = fit_ingest.reprocess_fits(s, root, since, uid)
            if apply:
                s.commit()
            else:
                s.rollback()
        result["mode"] = "apply" if apply else "dry_run"
    (root / "result.json").write_text(json.dumps(result))


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
        with (
            migrated_schema(conn, url, temp / "py", "5173") as py,
            migrated_schema(conn, url, temp / "go", "5173") as go,
        ):
            builder = runpy.run_path(str(BACKEND / "tests/fixtures/fit/synthetic.py"))
            payload = builder["build_synthetic_fit"]()
            for env in (py, go):
                env.update(PYTHONPATH=str(BACKEND), GORACE="atexit_sleep_ms=0")
                for rid in ("1", "2"):
                    (Path(env["PRIVATE_DIR"]) / f"{rid}.zip").write_bytes(
                        builder["build_synthetic_zip"]({f"{rid}.fit": payload})
                    )
                subprocess.run([sys.executable, __file__, "seed"], env=env, check=True)

            def compare(args, uid=None):
                values = []
                for env, command in [
                    (py, [sys.executable, __file__, "reference"]),
                    (go, [binary, "-test.run=^TestFITCommandFixture$"]),
                ]:
                    argv = args.copy()
                    if uid:
                        with connect(env) as db:
                            argv += [
                                "--activity-id",
                                str(
                                    db.execute(
                                        "SELECT id FROM activities WHERE garmin_id=%s",
                                        (uid,),
                                    ).fetchone()[0]
                                ),
                            ]
                    env["FIT_CLI_ARGS"] = json.dumps(argv)
                    subprocess.run(command, env=env, check=True)
                    values.append(
                        json.loads(
                            (Path(env["PRIVATE_DIR"]) / "result.json").read_text()
                        )
                    )
                assert values[0] == values[1], values
                for i, (a, b) in enumerate(
                    zip(snapshot(py), snapshot(go), strict=True)
                ):
                    assert a == b, (i, a, b)
                return values[0]

            counts = compare(["fit-backfill", "--since", DAY])
            assert counts == {
                "attempted": 7,
                "decoded": 2,
                "unavailable": 1,
                "failed": 4,
            }, counts
            for env in (py, go):
                with connect(env) as db:
                    db.execute(
                        "UPDATE fit_files SET decoder_version=1 WHERE decoded_at IS NOT NULL"
                    )
                    db.execute("UPDATE activity_laps SET intensity=NULL")
            baseline = snapshot(go)
            result = compare(["fit-reprocess", "--since", DAY])
            assert result["reprocessed"] == 2 and snapshot(go) == baseline
            assert compare(["fit-reprocess", "--since", "2027-01-01"])["selected"] == 0
            assert (
                compare(["fit-reprocess", "--since", "2027-01-01", "--apply"], "1")[
                    "reprocessed"
                ]
                == 1
            )
            assert (
                compare(["fit-reprocess", "--since", DAY, "--apply"])["reprocessed"]
                == 1
            )
            assert (
                compare(["fit-reprocess", "--since", DAY, "--apply"])["selected"] == 0
            )
            for env in (py, go):
                with connect(env) as db:
                    db.execute(
                        "UPDATE fit_files SET decoder_version=NULL WHERE decoded_at IS NOT NULL"
                    )
                    paths = db.execute(
                        "SELECT DISTINCT r.relative_path FROM raw_objects r JOIN fit_files f ON f.raw_object_id=r.id WHERE f.decoded_at IS NOT NULL"
                    ).fetchall()
                for (p,) in paths:
                    (Path(env["PRIVATE_DIR"]) / p).unlink()
            assert compare(["fit-reprocess", "--since", DAY, "--apply"])["errors"] == {
                "raw_missing": 2
            }
    print(
        "PASS FIT backfill, source ID resolution, retained FIT preview, targeted apply, idempotency, missing raw files and native derived windows"
    )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        reference()
    else:
        run()
