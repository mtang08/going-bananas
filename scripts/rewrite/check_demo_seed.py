"""Exercise the full synthetic demo seed and same-day replay."""

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import psycopg
from check_gcal_replay import connect, test_url
from psycopg import sql
from test_proposal_slice import MODULE, ROOT, migrated_schema

NOW = "2026-11-16T14:00:00+00:00"
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def snapshot(env):
    with connect(env) as db:
        ids = dict(
            db.execute("""SELECT id::text,'activity:'||garmin_id FROM activities
            UNION ALL SELECT session_uid::text,'plan:'||local_date::text||':'||slot||':'||kind
                FROM calendar_session_revisions
            UNION ALL SELECT id::text,'slot:'||label FROM strength_routine_slots
            UNION ALL SELECT id::text,'record:'||source_identity FROM source_records
            UNION ALL SELECT id::text,'checkin:'||idempotency_key FROM checkins_v2
            UNION ALL SELECT id::text,'event:'||google_event_id FROM gcal_events
            UNION ALL SELECT id::text,'trip:'||source||':'||start_date::text FROM trips
            UNION ALL SELECT id::text,'recovery:'||metric||':'||source_date::text FROM recovery_observations
            UNION ALL SELECT id::text,'account:'||account_scope FROM source_accounts
            UNION ALL SELECT id::text,'coverage:'||dataset FROM coverage_intervals
            UNION ALL SELECT c.session_uid::text,'extra:'||a.garmin_id
                FROM session_completions c JOIN activities a ON a.id=c.activity_id WHERE c.status='extra'
            UNION ALL SELECT id::text,'completion:'||session_uid::text FROM session_completions
            UNION ALL SELECT id::text,'raw:'||sha256 FROM raw_objects""").fetchall()
        )

        def canonical(x):
            if isinstance(x, list):
                return [canonical(i) for i in x]
            if isinstance(x, dict):
                return {k: canonical(v) for k, v in x.items()}
            if isinstance(x, str):
                return UUID.sub(lambda m: ids.get(m[0], m[0]), x)
            return x

        checks = {
            "activities": "SELECT to_jsonb(a)-'id'-'source_account_id' FROM activities a",
            "records": "SELECT to_jsonb(s)-'id'-'fetched_at' FROM source_records s",
            "recovery": "SELECT to_jsonb(s)-'id' FROM recovery_observations s",
            "coverage": "SELECT to_jsonb(s)-'id'-'completed_at' FROM coverage_intervals s",
            "laps": "SELECT to_jsonb(l)-'id' FROM activity_laps l",
            "steps": "SELECT to_jsonb(s)-'id' FROM activity_workout_steps s",
            "streams": """SELECT jsonb_build_array(a.garmin_id,md5((to_jsonb(s)-'activity_id')::text))
                FROM activity_streams s JOIN activities a ON s.activity_id=a.id""",
            "calendar": "SELECT to_jsonb(r)-'id' FROM calendar_session_revisions r",
            "version": "SELECT to_jsonb(v)-'id'-'created_at' FROM calendar_versions v",
            "completions": "SELECT to_jsonb(c)-'id'-'updated_at' FROM session_completions c",
            "prompts": "SELECT to_jsonb(p)-'id' FROM prompts p",
            "metrics": """SELECT jsonb_build_array(metric_id,method_version,subject_type,subject_key,status,
                quality_status,value,unit,reason_codes,quality_flags) FROM metric_results WHERE is_current""",
            "events": "SELECT to_jsonb(e)-'id'-'first_seen_at'-'last_seen_at' FROM gcal_events e",
            "trips": "SELECT to_jsonb(t)-'id'-'created_at'-'updated_at' FROM trips t",
            "legs": "SELECT to_jsonb(l)-'id' FROM trip_legs l",
            "profile": "SELECT to_jsonb(p)-'id'-'recorded_at' FROM profile_versions p",
            "slots": "SELECT to_jsonb(s)-'id' FROM strength_routine_slots s",
            "checkins": "SELECT to_jsonb(c)-'id' FROM checkins_v2 c",
            "symptoms": "SELECT to_jsonb(s)-'id' FROM symptom_reports s",
            "rpe": "SELECT to_jsonb(r)-'id' FROM session_rpe r",
            "state": "SELECT to_jsonb(s) FROM app_state s",
        }
        result = {}
        for name, query in checks.items():
            rows = [canonical(r[0]) for r in db.execute(query)]
            result[name] = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True))
        raw = db.execute(
            "SELECT relative_path,sha256 FROM raw_objects ORDER BY relative_path"
        ).fetchall()
        for path, digest in raw:
            assert (
                hashlib.sha256(
                    (Path(env["PRIVATE_DIR"]) / path).read_bytes()
                ).hexdigest()
                == digest
            )
        result["raw"] = raw
        return result


def check_cli(db, url, directory):
    name = "go_parity_" + uuid4().hex + "_demo"
    identifier = sql.Identifier(name)
    root = directory / "demo"
    root.mkdir(mode=0o700)
    env = {
        **os.environ,
        "APP_MODE": "demo",
        "DATABASE_URL": url.set(database=name).render_as_string(hide_password=False),
        "PRIVATE_DIR": str(root),
        "PGOPTIONS": "-csearch_path=public",
    }
    db.execute(sql.SQL("CREATE DATABASE {}").format(identifier))
    try:
        for command in ("workspace-migrate", "seed-demo"):
            binary = directory / command
            subprocess.run(
                ["go", "build", "-o", binary, "./cmd/" + command],
                cwd=MODULE,
                check=True,
            )
            output = subprocess.check_output([binary], cwd=ROOT, env=env, text=True)
        for overrides, args, expected in (
            ({"APP_MODE": "test"}, [], "demo_mode_required"),
            (
                {"DATABASE_URL": os.environ["TEST_DATABASE_URL"]},
                [],
                "demo_database_required",
            ),
            ({"PRIVATE_DIR": str(directory)}, [], "expected demo private directory"),
            ({}, ["unexpected"], "usage: seed-demo"),
        ):
            result = subprocess.run(
                [binary, *args],
                cwd=ROOT,
                env={**env, **overrides},
                text=True,
                capture_output=True,
                check=False,
            )
            assert result.returncode == 1 and result.stderr.strip() == expected
        totals = json.loads(output)
        assert (
            totals["activities"] == 14
            and totals["recovery_observations"] == 120
            and totals["gcal_events"] == 7
        )
        assert len(list((root / "raw").glob("*/*.json"))) == 134
    finally:
        db.execute(sql.SQL("DROP DATABASE {}").format(identifier))


def main():
    url = test_url()
    with (
        tempfile.TemporaryDirectory(dir=ROOT / "private") as directory,
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as db,
        migrated_schema(db, url, Path(directory) / "native", "0") as env,
    ):
        before = None
        for phase in ("fresh", "replay"):
            output = Path(directory) / "totals.json"
            subprocess.run(
                [
                    "go",
                    "test",
                    "-race",
                    "-count=1",
                    "-run",
                    "^TestDemoSeedFixture$",
                    "./internal/demoseed",
                ],
                cwd=MODULE,
                env={**env, "DEMO_SEED_OUTPUT": str(output), "DEMO_SEED_NOW": NOW},
                check=True,
            )
            actual = json.loads(output.read_text())
            assert actual["activities"] == 14 and actual["metric_results"] == 183, (
                actual
            )
            state = snapshot(env)
            assert len(state["raw"]) == 134
            assert any(row["status"] == "open" for row in state["prompts"])
            assert len(state["legs"]) >= 2 and len(state["calendar"]) == 29
            if before is not None:
                assert state == before, [
                    key for key in state if state[key] != before[key]
                ]
            before = state
            print(f"{phase}: {actual}", flush=True)
        check_cli(db, url, Path(directory))
    print(
        "PASS fresh demo sources, calendar, travel, metrics, raw files, prompts and replay"
    )


if __name__ == "__main__":
    main()
