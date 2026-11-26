"""Exercise Strong preview/apply against Python in isolated migrated PostgreSQL schemas."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import psycopg
from sqlalchemy.engine import make_url

from check_strong_csv import csv_text
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema


def reference(path, apply):
    from app.db import SessionLocal
    from app.services.strong_import import import_strong_csv

    with SessionLocal.begin() as session:
        print(json.dumps(import_strong_csv(session, Path(os.environ["PRIVATE_DIR"]), path, apply=apply)))


def conn(env):
    return psycopg.connect(env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"], autocommit=True)


def snapshot(env):
    with conn(env) as db:
        statements = {
            "revision": "SELECT data_revision FROM app_state WHERE id=1",
            "accounts": "SELECT provider,account_scope FROM source_accounts ORDER BY 1,2",
            "raw": "SELECT sha256,relative_path,byte_size,media_type FROM raw_objects ORDER BY 1",
            "history": """SELECT s.source_identity,s.payload_hash,s.fields,s.parser_version,s.source_kind,r.sha256
                FROM source_records s JOIN raw_objects r ON r.id=s.raw_object_id ORDER BY 1,2""",
            "batches": "SELECT status,source_kind,adapter_version,counters FROM import_batches ORDER BY started_at,id",
            "workouts": """SELECT w.source_identity,w.payload_hash,w.local_date,w.local_start,w.workout_name,
                w.duration_s,w.row_count,w.sets,w.resolution_state,r.sha256,s.payload_hash FROM strong_workouts w
                JOIN raw_objects r ON r.id=w.raw_object_id JOIN source_records s ON s.id=w.source_record_id ORDER BY 1""",
            "links": """SELECT c.session_uid,c.match_method,c.status,c.version,w.source_identity FROM session_completions c
                JOIN strong_workouts w ON w.id=c.strong_workout_id ORDER BY 1""",
            "rpe": """SELECT s.rpe,s.source,w.source_identity FROM session_rpe s
                JOIN strong_workouts w ON w.id=s.strong_workout_id ORDER BY w.source_identity""",
            "manual": "SELECT date,kind,duration_s,note,version FROM manual_sessions ORDER BY date",
        }
        return {key: db.execute(sql).fetchall() for key, sql in statements.items()}


def fixture_stamp(env, uid):
    with conn(env) as db:
        (workout,) = db.execute("SELECT id FROM strong_workouts ORDER BY local_start LIMIT 1").fetchone()
        db.execute("""INSERT INTO session_completions(id,session_uid,strong_workout_id,status,match_method,updated_at)
            VALUES(gen_random_uuid(),%s,%s,'completed_as_planned','explicit',now())""", (uid, workout))
        db.execute("""INSERT INTO session_rpe(id,strong_workout_id,rpe,source,collected_at)
            VALUES(gen_random_uuid(),%s,7,'manual',now())""", (workout,))
        db.execute("""INSERT INTO manual_sessions(id,date,kind,duration_s,note,version)
            VALUES(gen_random_uuid(),'2026-11-09','strength',1800,'synthetic manual history',1)""")


def scenario(binary, directory, py, go):
    csv_path = directory / "synthetic.csv"
    py["PYTHONPATH"] = str(BACKEND)
    go["GORACE"] = "atexit_sleep_ms=0"

    def check(apply):
        expected = json.loads(subprocess.check_output([sys.executable, __file__, "reference", csv_path, str(int(apply))], env=py))
        actual = json.loads(subprocess.check_output([binary, *(["-apply"] if apply else []), csv_path], env=go))
        assert actual["summary"] == expected, (actual, expected)
        assert snapshot(go) == snapshot(py), "Strong history and canonical rows differ"
        return actual

    row = ["2026-11-09 19:00:00", "Day A", "45m", "Bench", "1", "45.0", "8", "0", "0", ""]
    other = ["2026-11-10 08:30:00", "Day B", "120h 41m", "Dumbbell", "W", "22.5", "6", "", "", ""]
    csv_path.write_bytes(csv_text([row, other]).encode())
    for mode in ("real", "demo"):
        blocked = subprocess.run([binary, "-apply", csv_path], env=dict(go, APP_MODE=mode), capture_output=True, text=True)
        assert blocked.returncode and blocked.stderr.strip() in {
            "select a test or demo workspace with PRIVATE_DIR", "database name must match synthetic mode"
        }
    before = snapshot(go)
    assert check(False)["summary"]["new"] == 2
    assert snapshot(go) == before and not (Path(go["PRIVATE_DIR"]) / "raw").exists()
    applied = check(True)
    assert len(applied["affected_workout_dates"]) == 2 and snapshot(go)["revision"] == [(1,)]
    replay = check(True)
    assert replay["summary"]["unchanged"] == 2 and not replay["affected_workout_dates"]
    uid = uuid4()
    for env in (py, go):
        fixture_stamp(env, uid)
    changed = list(row)
    changed[5] = "47.5"
    csv_path.write_bytes(csv_text([changed, other]).encode())
    before = snapshot(go)
    assert check(False)["summary"]["changed_revisions"] == 1
    assert snapshot(go) == before
    with conn(go) as db:
        db.execute("""CREATE FUNCTION reject_batch() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'synthetic finalization failure'; END $$;
            CREATE TRIGGER reject_batch BEFORE UPDATE ON import_batches FOR EACH ROW EXECUTE FUNCTION reject_batch()""")
        rejected = subprocess.run([binary, "-apply", csv_path], env=go, capture_output=True, text=True)
        assert rejected.returncode and rejected.stderr.strip() == "strong_import_failed"
        assert snapshot(go) == before
        db.execute("DROP TRIGGER reject_batch ON import_batches")
    result = check(True)
    assert result["summary"]["status"] == "partial" and result["summary"]["revision_conflicts_new"] == 1
    current = snapshot(go)
    assert current["revision"] == [(2,)] and len(current["history"]) == 3
    assert current["manual"] == before["manual"] and current["rpe"] == before["rpe"] and current["links"] == before["links"]
    for earlier, later in zip(before["workouts"], current["workouts"], strict=True):
        assert earlier[:8] == later[:8] and earlier[9:] == later[9:], "canonical values or original source replaced"
    assert check(True)["summary"]["revision_conflicts_new"] == 0
    # Two independent CLI processes compete to add one new workout. Exactly one writes it.
    next_row = list(row)
    next_row[0] = "2026-11-15 10:00:00"
    csv_path.write_bytes(csv_text([next_row]).encode())
    argv = [binary, "-apply", csv_path]
    processes = [subprocess.Popen(argv, env=go, stdout=subprocess.PIPE) for _ in range(2)]
    results = []
    for process in processes:
        stdout, _ = process.communicate(timeout=30)
        assert process.returncode == 0
        results.append(json.loads(stdout)["summary"]["added"])
    assert sorted(results) == [0, 1]
    for _ in range(2):
        subprocess.check_output([sys.executable, __file__, "reference", csv_path, "1"], env=py)
    assert snapshot(go) == snapshot(py)
    for digest, path, size, media in snapshot(go)["raw"]:
        raw = (Path(go["PRIVATE_DIR"]) / path).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest and len(raw) == size and media == "text/csv"
    with conn(go) as db:
        db.execute("UPDATE source_accounts SET account_scope='unexpected' WHERE provider='strong'")
        before = snapshot(go)
        rejected = subprocess.run([binary, csv_path], env=go, capture_output=True, text=True)
        assert rejected.returncode and rejected.stderr.strip() == "mixed_source_account" and snapshot(go) == before
    print("PASS Strong preview, apply, provenance, replay, manual associations, conflicting revision, rollback/restart and concurrent delivery")


def main():
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if (os.environ.get("APP_MODE") != "test" or url.database != "garmin_test"
            or url.host not in {"127.0.0.1", "localhost"} or str(url.port) != os.environ.get("TEST_DATABASE_PORT")
            or url.query or os.environ.get("DATABASE_URL") != os.environ["TEST_DATABASE_URL"]):
        raise SystemExit("run scripts/test-db.py strong on the isolated test database")
    pg_url = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(pg_url, autocommit=True) as db, tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp:
        directory = Path(tmp)
        binary = directory / "strong-import"
        subprocess.run(["go", "build", "-race", "-o", binary, "./cmd/strong-import"], cwd=MODULE, check=True)
        with migrated_schema(db, url, directory / "py", "5173") as py, migrated_schema(db, url, directory / "go", "5173") as go:
            scenario(binary, directory, py, go)


if __name__ == "__main__":
    if sys.argv[1:2] == ["reference"]:
        reference(Path(sys.argv[2]), sys.argv[3] == "1")
    else:
        main()
