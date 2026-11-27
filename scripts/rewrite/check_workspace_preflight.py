"""Verify read-only cutover readiness against an independently migrated synthetic workspace."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema


def reference():
    from app.api.coach import resolve_kb
    from app.db import SessionLocal
    from app.services.backup import create_backup, validate_backup
    from app.services.calendar import calendar_view
    from app.services.profile import current_profile, profile_data
    from app.services.proposals.lifecycle import submit_proposal
    from app.services.snapshot.build import build_snapshot
    from app.services.timezone import athlete_today
    from app.services.weekly_digest import load_week, week_bounds
    from sqlalchemy import text

    now = datetime.now(UTC)
    with SessionLocal.begin() as s:
        name, schema = s.execute(
            text("SELECT current_database(),current_schema()")
        ).one()
        assert name == "garmin_test" and re.fullmatch(r"go_parity_[0-9a-f]{32}", schema)
        day = athlete_today(s, now)
        first, last = week_bounds(day)
        assert profile_data(current_profile(s))["version"] == 1
        assert calendar_view(s, first, last)["head"] == 1
        assert load_week(s, first, today=day, now=now)
        snapshot = build_snapshot(s, "proceed_or_modify_today", day, now=now)
        doc = {
            "schema_version": "coach_proposal.v2",
            "operation": "proceed_or_modify_today",
            "snapshot_id": snapshot["snapshot_id"],
            "base_calendar_version": 1,
            "base_block_version_id": None,
            "headline": "Private synthetic marker",
            "why": [{"kind": "observation", "text": "Synthetic evidence"}],
            "uncertainty": ["Synthetic uncertainty"],
            "change_triggers": [{"when": "Energy drops", "then": "Rest"}],
            "next_check": {"on": day.isoformat(), "check": "Review response"},
            "confidence": {
                "decision": "moderate",
                "evidence": "moderate",
                "data": "moderate",
            },
            "changes": [
                {
                    "change_id": "c1",
                    "op": "add",
                    "after": {
                        "local_date": day.isoformat(),
                        "kind": "rest",
                        "intent": "Rest",
                    },
                    "reason": "Review",
                }
            ],
            "evidence_ids": [],
            "policy_ids": [],
            "recipe_ids": [],
            "skill_version": "running-coach.v1",
        }
        receipt = submit_proposal(s, doc, now=now, resolve_kb=resolve_kb)
        assert receipt.status == "pending", [i.code for i in receipt.issues]
    private = Path(os.environ["PRIVATE_DIR"])
    archive = private.parent / "synthetic-backup.tar.gz"
    # Freeze the selected schema for pg_dump: the standalone test shares a DB with other suites.
    from unittest.mock import patch

    from app.services import backup

    run = backup._run
    with patch.object(
        backup,
        "_run",
        side_effect=lambda argv, env: run(
            argv[:1] + ["--schema", schema] + argv[1:], env
        ),
    ):
        manifest = create_backup(os.environ["DATABASE_URL"], private, archive)
    verified, _ = validate_backup(archive)
    assert (
        manifest == verified
        and verified["files"]["private/raw/synthetic"]["sha256"]
        == hashlib.sha256(b"fixture").hexdigest()
    )


def snapshots(db, private):
    schema = db.execute("select current_schema()").fetchone()[0]
    tables = db.execute(
        "select tablename from pg_tables where schemaname=%s order by tablename",
        (schema,),
    ).fetchall()
    rows = {}
    for (table,) in tables:
        rows[table] = db.execute(
            sql.SQL(
                "select md5(coalesce(string_agg(to_jsonb(t)::text,'' order by to_jsonb(t)::text),'')) from {} t"
            ).format(sql.Identifier(table))
        ).fetchone()[0]
    paths = {
        str(p.relative_to(private)): (p.lstat().st_mode, p.lstat().st_mtime_ns)
        for p in private.rglob("*")
    }
    return rows, paths


def scenario(binary, tmp, env):
    private = Path(env["PRIVATE_DIR"])
    private.mkdir(exist_ok=True)
    raw = private / "raw" / "synthetic"
    raw.parent.mkdir(exist_ok=True)
    raw.write_bytes(b"fixture")
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    with psycopg.connect(
        env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"], autocommit=True
    ) as db:
        name, schema = db.execute(
            "select current_database(),current_schema()"
        ).fetchone()
        assert name == "garmin_test" and re.fullmatch(r"go_parity_[0-9a-f]{32}", schema)
        db.execute(
            "insert into raw_objects(id,sha256,relative_path,byte_size,media_type) values(gen_random_uuid(),%s,'raw/synthetic',7,'text/plain')",
            (digest,),
        )
        db.execute("""insert into profile_versions(id,version,effective_at,timezone,anchor_confirmed,strength_days_confirmed,scheduled_strength_days,facts,preferences,unknowns)
          values(gen_random_uuid(),1,now(),'America/New_York',false,false,'[]','{}','{}','[]')""")
        db.execute(
            "insert into calendar_versions(id,number,kind,actor) values(gen_random_uuid(),1,'bootstrap','user')"
        )
        db.execute("update app_state set calendar_head_version=1")
        db.execute(
            "insert into sync_jobs(id,dataset,status,start_date,end_date,checkpoint,counters) values(gen_random_uuid(),'activities','queued',CURRENT_DATE,CURRENT_DATE,'{\"offset\":5}','{}')"
        )
        subprocess.run(
            [sys.executable, __file__, "reference"],
            env={**env, "PYTHONPATH": str(BACKEND)},
            check=True,
        )

        def run(ok, key, value, extra=None):
            before = snapshots(db, private)
            proc = subprocess.run(
                [binary, "workspace-preflight", "-repo", ROOT],
                env={**env, **(extra or {})},
                text=True,
                capture_output=True,
                check=False,
            )
            out = json.loads(proc.stdout)
            assert (
                (proc.returncode == 0) == ok
                and out["ready"] == ok
                and out["checks"].get(key) == value
            ), (proc.returncode, out)
            assert proc.stderr == "" and not any(
                s in proc.stdout
                for s in (digest, str(private), "Private synthetic marker", schema)
            )
            assert snapshots(db, private) == before

        run(True, "active_draft", "pending")
        run(False, "workspace", "failed", {"APP_MODE": "real"})
        raw.write_bytes(b"damaged")
        run(False, "raw_references", "failed")
        raw.rename(raw.with_suffix(".save"))
        run(False, "raw_references", "failed")
        raw.symlink_to(raw.with_suffix(".save"))
        run(False, "raw_references", "failed")
        raw.unlink()
        raw.write_bytes(b"fixture")
        db.execute("UPDATE app_state SET calendar_head_version=99")
        run(False, "accepted_calendar", "failed")
        db.execute("UPDATE app_state SET calendar_head_version=1")
        db.execute("UPDATE sync_jobs SET status='running'")
        run(False, "sync_checkpoints", "failed")
        db.execute("UPDATE sync_jobs SET status='queued',checkpoint='{\"offset\":-1}'")
        run(False, "sync_checkpoints", "failed")
        db.execute("UPDATE sync_jobs SET checkpoint='{}'")
        db.execute(
            "alter table import_batches rename column adapter_version to missing_adapter_version"
        )
        run(False, "schema", "failed")
        db.execute(
            "alter table import_batches rename column missing_adapter_version to adapter_version"
        )
        credential = private / "google-calendar-token.json"
        credential.write_text("private synthetic credentials")
        credential.chmod(0o644)
        run(False, "calendar_token", "unsafe_permissions")
        credential.chmod(0o600)
        run(True, "calendar_token", "private")
        db.execute("UPDATE alembic_version SET version_num='0027_rehab_sessions'")
        run(False, "schema", "failed")
        db.execute("DROP TABLE alembic_version")
        run(False, "schema", "failed")
    print(
        "PASS read-only populated workspace, Python backup manifest and domain reads, corrupt/missing/linked raw file, broken calendar, checkpoint, running writer, interrupted migration and mode isolation"
    )


def main():
    url = make_url(os.environ["DATABASE_URL"])
    if url.password is None and os.environ.get("PGPASSWORD"):
        url = url.set(password=os.environ["PGPASSWORD"])
    if (
        os.environ.get("APP_MODE") != "test"
        or url.database != "garmin_test"
        or url.host not in {"localhost", "127.0.0.1"}
    ):
        raise ValueError("requires isolated test workspace")
    with (
        tempfile.TemporaryDirectory(dir=ROOT / "private") as t,
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as db,
    ):
        d = Path(t)
        binary = d / "preflight"
        subprocess.run(
            ["go", "build", "-o", binary, "./cmd/going-bananas"],
            cwd=MODULE,
            check=True,
        )
        with migrated_schema(db, url, d / "workspace", "5173") as env:
            scenario(binary, d, env)


if __name__ == "__main__":
    if sys.argv[1:] == ["reference"]:
        reference()
    else:
        main()
