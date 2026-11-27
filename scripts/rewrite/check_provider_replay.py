"""Compare the offline replay command with Python in disposable migrated schemas."""

import hashlib
import json
import os
import runpy
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import psycopg
from sqlalchemy.engine import make_url

from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema


def python_delivery(manifest):
    from sqlalchemy import select

    from app import strong_models  # noqa: F401 - SessionRpe references strong_workouts
    from app.db import SessionLocal
    from app.models import Activity
    from app.services.export_import import import_export
    from app.services.fit_ingest import ingest_activity_fit_bytes
    from app.services.sync import import_activity_page

    page = json.loads(manifest.read_text())
    if "activity_page" in page:
        page["activities"] = json.loads((manifest.parent / page["activity_page"]).read_text())
    target = Path(os.environ["PRIVATE_DIR"])
    with SessionLocal.begin() as session:
        if page.get("export"):
            import_export(session, target, manifest.parent / page["export"], apply=True)
        elif page.get("activities"):
            import_activity_page(
                session, target, page["activities"], account_scope="auto",
                fetched_at=datetime.fromisoformat(page["fetched_at"]),
            )
        for key, path in page.get("fit", {}).items():
            activity = session.scalar(select(Activity).where(Activity.garmin_id == key))
            ingest_activity_fit_bytes(session, target, activity, (manifest.parent / path).read_bytes())


def inputs(directory):
    build = runpy.run_path(str(BACKEND / "tests/fixtures/fit/synthetic.py"))
    (directory / "activity.zip").write_bytes(build["build_synthetic_zip"]())
    (directory / "broken.zip").write_bytes(b"broken fixture")
    at = datetime.fromtimestamp(build["START_FIT_TS"] + build["FIT_EPOCH_OFFSET"], UTC)
    previous_day = datetime(2026, 11, 10, 4, 50, tzinfo=UTC)
    new_day = datetime(2026, 11, 10, 5, 10, tzinfo=UTC)
    rows = [
        {"activityId": i, "userProfileId": 777, "activityType": "track_running",
         "startTimeGmt": int(t.timestamp() * 1000), "distance": 500000, "avgHr": 134,
         "elapsedDuration": 1800000, "movingDuration": 1750000}
        for i, t in [(70, at), (71, previous_day)]
    ]
    with ZipFile(directory / "export.zip", "w") as archive:
        archive.writestr("account/summarizedActivities.json", json.dumps([{"summarizedActivitiesExport": rows}]))
    api = [
        {"activityId": i, "ownerId": 777, "activityType": {"typeKey": "running"},
         "startTimeGMT": t.isoformat(), "distance": 5010.5, "elapsedDuration": 1801,
         "averageRunningCadenceInStepsPerMinute": 170, "note": "résumé & <ok>"}
        for i, t in [(70, at), (71, new_day)]
    ]
    (directory / "activities.json").write_text(json.dumps(api))
    return api


def connect(env):
    return psycopg.connect(env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"], autocommit=True)


def snapshot(env):
    with connect(env) as db:
        def rows(query):
            return db.execute(query).fetchall()

        # Stable source identities replace runtime-specific UUIDs in provenance.
        hashes = dict(rows("SELECT id::text,payload_hash FROM source_records"))
        activities = []
        for (item,) in rows("SELECT to_jsonb(a) - ARRAY['id','source_account_id','fit_file_id'] FROM activities a ORDER BY source_identity"):
            for ref in item["field_provenance"].values():
                if "source_record_id" in ref:
                    ref["source_record_id"] = hashes[ref["source_record_id"]]
            activities.append(item)
        result = {"activities": activities,
                  "records": rows("""SELECT s.source_identity,s.payload_hash,s.source_kind,s.parser_version,
                    s.fields,s.rejected_reason,r.sha256,r.relative_path,r.byte_size
                    FROM source_records s JOIN raw_objects r ON r.id=s.raw_object_id ORDER BY 1,2"""),
                  "links": rows("""SELECT a.garmin_id,s.payload_hash,l.selected_fields FROM activity_sources l
                    JOIN activities a ON a.id=l.activity_id JOIN source_records s ON s.id=l.source_record_id ORDER BY 1,2"""),
                  "files": rows("""SELECT zip_sha256,fit_sha256,profile_version,decode_error,last_error,
                    message_inventory,device,decoder_version FROM fit_files ORDER BY zip_sha256"""),
                  "rpe": rows("SELECT rpe,source,collected_at FROM session_rpe ORDER BY collected_at"),
                  "accounts": rows("SELECT provider,account_scope FROM source_accounts ORDER BY 1,2")}
        for table, order in [("activity_laps", "lap_index"), ("activity_workout_steps", "message_index"), ("activity_streams", "activity_id")]:
            result[table] = rows(f"SELECT to_jsonb(t)-ARRAY['id','activity_id'] FROM {table} t ORDER BY {order}")
        return result


def compare(reference, candidate):
    left, right = snapshot(reference), snapshot(candidate)
    for name, expected in left.items():
        if expected != right[name]:
            raise AssertionError(f"{name} differs: Python {str(expected)[:1200]}, Go {str(right[name])[:1200]}")


def scenario(binary, directory, api, ref, go, export_first):
    go["GORACE"] = "atexit_sleep_ms=0"
    job = str(uuid4())
    target = directory / "delivery.json"

    def run(page, *, reference=True, failure=False):
        target.write_text(json.dumps(dict(job_id=job, fetched_at="2026-11-11T00:00:00+00:00", **page)))
        args = [str(binary), "-page", str(target)]
        proc = subprocess.run(args, env=go, capture_output=True, text=True)
        if failure:
            assert proc.returncode != 0, "expected page rollback"
            return
        if proc.returncode:
            raise RuntimeError(proc.stderr)
        if reference:
            subprocess.run([sys.executable, __file__, "python", target], env=ref, check=True)
            compare(ref, go)
        return json.loads(proc.stdout)

    order = [{"export": "export.zip"}, {"activity_page": "activities.json", "fit": {"70": "activity.zip"}}]
    if not export_first:
        order.reverse()
    go["PRIVATE_DIR"] = str(Path(go["PRIVATE_DIR"]).resolve())
    first = run(dict(index=0, **order[0]))
    assert first["offset"] == 2 and first["counters"]["new_revisions"] == 2
    with connect(go) as db:
        # Force rollback after activity, provenance, links and batch writes, immediately before checkpoint.
        db.execute("""CREATE FUNCTION reject_checkpoint() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'synthetic checkpoint failure'; END $$;
            CREATE TRIGGER reject_checkpoint BEFORE UPDATE ON sync_jobs FOR EACH ROW EXECUTE FUNCTION reject_checkpoint()""")
        before = snapshot(go)
        run(dict(index=1, **order[1]), reference=False, failure=True)
        assert snapshot(go) == before
        assert db.execute("SELECT checkpoint->>'offset' FROM sync_jobs WHERE id=%s", (job,)).fetchone() == ("2",)
        db.execute("DROP TRIGGER reject_checkpoint ON sync_jobs")
    second = run(dict(index=1, **order[1]))
    if export_first:
        assert second["affected_dates"] == ["2026-11-09", "2026-11-10"]
    duplicate = run(dict(index=1, **order[1]), reference=False)
    assert duplicate["duplicate"] and duplicate["counters"] == second["counters"] and duplicate["affected_dates"] == []
    run(dict(index=1, activities=[]), reference=False, failure=True)
    run(dict(index=4, activities=[]), reference=False, failure=True)
    prior = snapshot(go)
    third = run(dict(index=2, activities=api, fit={"70": "broken.zip"}))
    assert third["counters"]["fit_failed"] == 1
    after = snapshot(go)
    assert after["activities"] == prior["activities"] and after["activity_streams"] == prior["activity_streams"]
    rejected = {"ownerId": 777, "activityId": 99, "activityType": "run"}
    last = run(dict(index=3, final=True, activities=[api[0], rejected]))
    assert last["status"] == "partial" and last["counters"]["rejected"] == 1
    assert last["offset"] == 8 and last["counters"]["new_revisions"] == 5
    with connect(go) as db:
        ids = {str(row[0]) for row in db.execute("SELECT id FROM activities")}
        assert set(first["affected_activity_dates"]) == ids
        assert db.execute("SELECT checkpoint->'affected_dates' FROM sync_jobs WHERE id=%s", (job,)).fetchone()[0] == (
            ["2026-11-09", "2026-11-10"] if export_first else ["2026-11-10"])
        assert db.execute("SELECT sdk_version FROM fit_files").fetchone()[0] == "muktihari/fit@0.28.7"
        raw_files = db.execute("SELECT sha256,relative_path FROM raw_objects").fetchall()
        for digest, path in raw_files:
            assert hashlib.sha256((Path(go["PRIVATE_DIR"]) / path).read_bytes()).hexdigest() == digest
        file_id, raw_path = db.execute("""SELECT f.activity_id,r.relative_path FROM fit_files f
            JOIN raw_objects r ON r.id=f.raw_object_id""").fetchone()
        db.execute("UPDATE fit_files SET decoder_version=1")
        reprocess = [binary, "-reprocess", str(file_id)]
        assert json.loads(subprocess.check_output(reprocess, env=go))["status"] == "reprocessed"
        good = snapshot(go)
        db.execute("UPDATE fit_files SET decoder_version=1")
        (Path(go["PRIVATE_DIR"]) / raw_path).write_bytes(b"damaged retained fixture")
        assert json.loads(subprocess.check_output(reprocess, env=go))["status"] == "fit_raw_hash_mismatch"
        damaged = snapshot(go)
        for key in ("activities", "activity_laps", "activity_workout_steps", "activity_streams", "rpe"):
            assert damaged[key] == good[key]
    if export_first:
        # Isolate a two-page strength replay from the prior FIT-reprocessing checks.
        job = str(uuid4())
        base = dict(ownerId=777, activityType={"typeKey": "strength_training"},
                    startTimeGMT="2026-11-15T16:00:00+00:00", distance=0, elapsedDuration=900)
        def revision(env):
            with connect(env) as conn:
                return conn.execute("SELECT data_revision FROM app_state WHERE id=1").fetchone()[0]
        def apply(rows, index, expected_delta):
            before = [revision(env) for env in (ref, go)]
            page = dict(index=index, activities=rows, final=index == 2)
            result = run(page, reference=False)
            subprocess.run([sys.executable, __file__, "python", target], env=ref, check=True)
            assert [revision(env)-old for env, old in zip((ref, go), before, strict=True)] == [expected_delta]*2
            return result
        apply([dict(base, activityId=401)], 0, 1)
        for env in (ref, go):
            with connect(env) as conn:
                conn.execute("INSERT INTO manual_sessions(id,version,date,kind) VALUES(gen_random_uuid(),1,'2026-11-15','strength')")
        new_rows = [dict(base, activityId=402), dict(base)]
        result = apply(new_rows, 1, 1)
        for env in (ref, go):
            with connect(env) as conn:
                held = dict(conn.execute("SELECT id::text,local_date::text FROM activities WHERE resolution_state='pending'"))
                assert len(held) == 3
                if env is go:
                    assert result["affected_activity_dates"] == held
                    assert result["affected_dates"] == ["2026-11-15"]
                assert dict(conn.execute("SELECT kind,count(*) FROM conflicts GROUP BY kind")) == {
                    "manual_import_overlap": 3, "activity_overlap": 2}
        repeated = apply(new_rows, 2, 0)
        assert not repeated["affected_activity_dates"]
    print(f"PASS {'export → API' if export_first else 'API → export'}: source history, ZIP and fields, checkpoint rollback, restart, duplicate, partial page, retained archive repair/error")


def main():
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if (os.environ.get("APP_MODE") != "test" or url.database != "garmin_test"
            or url.host not in {"127.0.0.1", "localhost"} or str(url.port) != os.environ.get("TEST_DATABASE_PORT")
            or url.query or os.environ.get("DATABASE_URL") != os.environ["TEST_DATABASE_URL"]):
        raise SystemExit("use the isolated PostgreSQL test runner with its test environment")
    pg_url = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(pg_url, autocommit=True) as db, tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp:
        directory = Path(tmp)
        api = inputs(directory)
        binary = directory / "garmin-replay"
        subprocess.run(["go", "build", "-race", "-o", binary, "./cmd/garmin-replay"], cwd=MODULE, check=True)
        for index, export_first in enumerate([True, False]):
            with migrated_schema(db, url, directory / f"ref-{index}", "5173") as ref, migrated_schema(
                    db, url, directory / f"go-{index}", "5173") as go:
                ref["PYTHONPATH"] = str(BACKEND)
                scenario(binary, directory, api, ref, go, export_first)


if __name__ == "__main__":
    if sys.argv[1:2] == ["python"]:
        python_delivery(Path(sys.argv[2]))
    else:
        main()
