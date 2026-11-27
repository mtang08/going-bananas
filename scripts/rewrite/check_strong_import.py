"""Exercise Strong preview/apply in isolated PostgreSQL."""

import csv
import hashlib
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import psycopg
from sqlalchemy.engine import make_url
from test_proposal_slice import MODULE, ROOT, migrated_schema


def csv_text(rows):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(
        (
            "Date",
            "Workout Name",
            "Duration",
            "Exercise Name",
            "Set Order",
            "Weight",
            "Reps",
            "Distance",
            "Seconds",
            "RPE",
        )
    )
    writer.writerows(rows)
    return out.getvalue()


def conn(env):
    return psycopg.connect(
        env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"], autocommit=True
    )


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
            "links": """SELECT CASE WHEN c.status='extra' THEN 'extra:'||w.source_identity ELSE c.session_uid::text END,c.match_method,c.status,c.version,w.source_identity FROM session_completions c
                JOIN strong_workouts w ON w.id=c.strong_workout_id ORDER BY 1""",
            "rpe": """SELECT s.rpe,s.source,w.source_identity FROM session_rpe s
                JOIN strong_workouts w ON w.id=s.strong_workout_id ORDER BY w.source_identity""",
            "manual": "SELECT date,kind,duration_s,note,version FROM manual_sessions ORDER BY date",
            "metrics": """SELECT metric_id,COALESCE('strong:'||w.source_identity,'extra:'||extra.source_identity,m.subject_key),status,value,reason_codes,config_hash,timezone
                FROM metric_results m LEFT JOIN strong_workouts w ON m.subject_key='strong:'||w.id::text
                LEFT JOIN (select c.session_uid::text,w.source_identity from session_completions c join strong_workouts w on w.id=c.strong_workout_id where c.status='extra') extra ON extra.session_uid=m.subject_key
                WHERE m.is_current ORDER BY 1,2""",
            "prompts": "SELECT kind,status,opens_at,closes_at,session_uid,activity_id FROM prompts ORDER BY kind,opens_at,session_uid NULLS LAST",
        }
        for uid, workout in db.execute(
            "SELECT session_uid,strong_workout_id FROM session_completions WHERE status='extra' AND strong_workout_id IS NOT NULL"
        ):
            assert uid == uuid5(
                UUID("e35269d4-74b0-53bf-8a74-f01b3ef69218"), f"extra:strong:{workout}"
            )
        return {key: db.execute(sql).fetchall() for key, sql in statements.items()}


def fixture_stamp(env, uid):
    with conn(env) as db:
        (workout,) = db.execute(
            "SELECT id FROM strong_workouts ORDER BY local_start LIMIT 1"
        ).fetchone()
        db.execute(
            "INSERT INTO calendar_versions(id,number,kind,actor) VALUES(%s,1,'manual_edit','user')",
            (uid,),
        )
        db.execute("UPDATE app_state SET calendar_head_version=1 WHERE id=1")
        db.execute(
            """INSERT INTO calendar_session_revisions(id,session_uid,revision,calendar_version_number,local_date,kind,certainty,intent,planned_duration_s) VALUES(%s,%s,1,1,'2026-11-09','strength','committed','Test strength',2700)""",
            (uid, uid),
        )
        db.execute(
            """INSERT INTO session_completions(id,session_uid,strong_workout_id,status,match_method,updated_at)
            VALUES(gen_random_uuid(),%s,%s,'completed_as_planned','explicit',now())""",
            (uid, workout),
        )
        db.execute(
            """INSERT INTO session_rpe(id,strong_workout_id,rpe,source,collected_at)
            VALUES(gen_random_uuid(),%s,7,'manual',now())""",
            (workout,),
        )
        db.execute(
            """INSERT INTO manual_sessions(id,date,kind,duration_s,note,version)
            VALUES(%s,'2026-11-09','strength',1800,'synthetic manual history',1)""",
            (uid,),
        )


def scenario(binary, operator, directory, go):
    csv_path = directory / "synthetic.csv"
    native = dict(
        go,
        GORACE="atexit_sleep_ms=0",
        PGOPTIONS=go["PGOPTIONS"] + " -cdefault_transaction_read_only=on",
    )

    def check(apply):
        return json.loads(
            subprocess.check_output(
                [binary, *(["-apply"] if apply else []), csv_path], env=native
            )
        )

    row = [
        "2026-11-09 19:00:00",
        "Day A",
        "45m",
        "Bench",
        "1",
        "45.0",
        "8",
        "0",
        "0",
        "",
    ]
    other = [
        "2026-11-10 08:30:00",
        "Day B",
        "120h 41m",
        "Dumbbell",
        "W",
        "22.5",
        "6",
        "",
        "",
        "",
    ]
    csv_path.write_bytes(csv_text([row, other]).encode())
    for mode in ("real", "demo"):
        blocked = subprocess.run(
            [binary, "-apply", csv_path],
            env=dict(native, APP_MODE=mode),
            capture_output=True,
            text=True,
            check=False,
        )
        assert blocked.returncode and blocked.stderr.strip() in {
            "database name must match APP_MODE"
        }

    def cli(apply):
        return subprocess.run(
            [operator, "strong-import", csv_path, *(["--apply"] if apply else [])],
            env=native,
            capture_output=True,
            text=True,
            check=False,
        )

    preview = cli(False)
    assert preview.returncode == 0 and json.loads(preview.stdout)["new"] == 2
    before = snapshot(go)
    assert check(False)["summary"]["new"] == 2
    assert snapshot(go) == before and not (Path(go["PRIVATE_DIR"]) / "raw").exists()
    applied = check(True)
    assert len(applied["affected_workout_dates"]) == 2 and snapshot(go)["revision"] == [
        (1,)
    ]
    replay = check(True)
    assert replay["summary"]["unchanged"] == 2 and not replay["affected_workout_dates"]
    uid = uuid4()
    fixture_stamp(go, uid)
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
        rejected = subprocess.run(
            [binary, "-apply", csv_path],
            env=native,
            capture_output=True,
            text=True,
            check=False,
        )
        assert rejected.returncode and rejected.stderr.strip() == "strong_import_failed"
        assert snapshot(go) == before
        db.execute("DROP TRIGGER reject_batch ON import_batches")
    result = check(True)
    assert (
        result["summary"]["status"] == "partial"
        and result["summary"]["revision_conflicts_new"] == 1
    )
    current = snapshot(go)
    assert current["revision"] == [(2,)] and len(current["history"]) == 3
    assert (
        current["manual"] == before["manual"]
        and current["rpe"] == before["rpe"]
        and [r[:2] + r[4:] for r in current["links"]]
        == [r[:2] + r[4:] for r in before["links"]]
    )
    for earlier, later in zip(before["workouts"], current["workouts"], strict=True):
        assert earlier[:8] == later[:8] and earlier[9:] == later[9:], (
            "canonical values or original source replaced"
        )
    replay_cli = cli(True)
    assert (
        replay_cli.returncode == 0
        and json.loads(replay_cli.stdout)["revision_conflicts_new"] == 0
    )
    assert check(True)["summary"]["revision_conflicts_new"] == 0
    extra_row = [*row]
    extra_row[0] = "2026-11-13 10:00:00"
    csv_path.write_bytes(csv_text([extra_row]).encode())
    apply_cli = cli(True)
    assert apply_cli.returncode == 0 and json.loads(apply_cli.stdout)["added"] == 1
    # Two independent CLI processes compete to add one new workout. Exactly one writes it.
    next_row = list(row)
    next_row[0] = "2026-11-15 10:00:00"
    csv_path.write_bytes(csv_text([next_row]).encode())
    argv = [binary, "-apply", csv_path]
    processes = [
        subprocess.Popen(argv, env=native, stdout=subprocess.PIPE) for _ in range(2)
    ]
    results = []
    for process in processes:
        stdout, _ = process.communicate(timeout=30)
        assert process.returncode == 0
        results.append(json.loads(stdout)["summary"]["added"])
    assert sorted(results) == [0, 1]
    actual = snapshot(go)
    assert len(actual["workouts"]) == 4 and actual["revision"] == [(4,)]
    assert actual["metrics"] and actual["links"]
    for digest, path, size, media in snapshot(go)["raw"]:
        raw = (Path(go["PRIVATE_DIR"]) / path).read_bytes()
        assert (
            hashlib.sha256(raw).hexdigest() == digest
            and len(raw) == size
            and media == "text/csv"
        )
    with conn(go) as db:
        db.execute(
            "UPDATE source_accounts SET account_scope='unexpected' WHERE provider='strong'"
        )
        before = snapshot(go)
        rejected = subprocess.run(
            [binary, csv_path], env=native, capture_output=True, text=True, check=False
        )
        assert (
            rejected.returncode
            and rejected.stderr.strip() == "mixed_source_account"
            and snapshot(go) == before
        )
    csv_path.write_text("Wrong,Columns\n")
    invalid = cli(False)
    assert invalid.returncode == 2 and json.loads(invalid.stderr.splitlines()[-1]) == {
        "error": "unsupported_columns"
    }
    print(
        "PASS Strong preview, apply, provenance, replay, manual associations, conflicting revision, rollback/restart and concurrent delivery"
    )


def main():
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if (
        os.environ.get("APP_MODE") != "test"
        or url.database != "garmin_test"
        or url.host not in {"127.0.0.1", "localhost"}
        or str(url.port) != os.environ.get("TEST_DATABASE_PORT")
        or url.query
        or os.environ.get("DATABASE_URL") != os.environ["TEST_DATABASE_URL"]
    ):
        raise SystemExit("run scripts/test-db.py strong on the isolated test database")
    pg_url = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with (
        psycopg.connect(pg_url, autocommit=True) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
    ):
        directory = Path(tmp)
        binary = directory / "strong-import"
        subprocess.run(
            ["go", "build", "-race", "-o", binary, "./cmd/strong-import"],
            cwd=MODULE,
            check=True,
        )
        operator = directory / "going-bananas"
        subprocess.run(
            ["go", "build", "-race", "-o", operator, "./cmd/going-bananas"],
            cwd=MODULE,
            check=True,
        )
        with migrated_schema(
            db, url, directory / "native", "5173", app_binary=operator
        ) as go:
            scenario(binary, operator, directory, go)


if __name__ == "__main__":
    main()
