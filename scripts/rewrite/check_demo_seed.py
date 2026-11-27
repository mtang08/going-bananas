"""Differential for the complete synthetic demo dashboard and same-day replay."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from check_gcal_replay import connect, test_url
from psycopg import sql
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema

NOW = "2026-11-16T14:00:00+00:00"
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def reference():
    test_url()
    assert re.fullmatch(
        r"-csearch_path=go_parity_[0-9a-f]{32} -cTimeZone=Asia/Kathmandu",
        os.environ["PGOPTIONS"],
    )
    from app import demo_seed
    from app.cli import _prepare_calendar_preview
    from app.db import SessionLocal
    from app.services import calendar, derived, timezone

    derived.install()

    now = datetime.fromisoformat(NOW)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    with (
        patch.object(demo_seed, "datetime", Clock),
        patch.object(calendar, "datetime", Clock),
        patch.object(timezone, "datetime", Clock),
        SessionLocal.begin() as s,
    ):
        s.info["metrics_now"] = now
        _prepare_calendar_preview(s)
        demo_seed.seed_demo(s, Path(os.environ["PRIVATE_DIR"]), now.date())
    with SessionLocal() as s:
        print(json.dumps(demo_seed.demo_totals(s)))


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
        raw = db.execute("SELECT relative_path,sha256 FROM raw_objects ORDER BY relative_path").fetchall()
        for path, digest in raw:
            assert hashlib.sha256((Path(env["PRIVATE_DIR"]) / path).read_bytes()).hexdigest() == digest
        result["raw"] = raw
        return result


def compare(py, go):
    from itertools import zip_longest

    a, b = snapshot(py), snapshot(go)
    errors = []
    for key in a:
        if a[key] != b[key]:
            first = next(
                (pair for pair in zip_longest(a[key], b[key]) if pair[0] != pair[1]),
                None,
            )
            errors.append(f"{key} ({len(a[key])}/{len(b[key])}) first difference: {str(first)[:1500]}")
    if errors:
        raise AssertionError("\n".join(errors))


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
            ({"DATABASE_URL": os.environ["TEST_DATABASE_URL"]}, [], "demo_database_required"),
            ({"PRIVATE_DIR": str(directory)}, [], "expected demo private directory"),
            ({}, ["unexpected"], "usage: seed-demo"),
        ):
            result = subprocess.run(
                [binary, *args],
                cwd=ROOT,
                env={**env, **overrides},
                text=True,
                capture_output=True,
            )
            assert result.returncode == 1 and result.stderr.strip() == expected
        totals = json.loads(output)
        assert totals["activities"] == 14 and totals["recovery_observations"] == 120 and totals["gcal_events"] == 7
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
        migrated_schema(db, url, Path(directory) / "py", "0") as py,
        migrated_schema(db, url, Path(directory) / "go", "0") as go,
    ):
        py["PYTHONPATH"] = str(BACKEND)
        for phase in ("fresh", "replay"):
            expected = json.loads(
                subprocess.check_output([sys.executable, __file__, "reference"], env=py, text=True).splitlines()[-1]
            )
            output = Path(directory) / "totals.json"
            subprocess.run(
                [
                    "go",
                    "test",
                    "-count=1",
                    "-run",
                    "^TestPythonDemoSeed$",
                    "./internal/demoseed",
                ],
                cwd=MODULE,
                env={**go, "DEMO_SEED_OUTPUT": str(output), "DEMO_SEED_NOW": NOW},
                check=True,
            )
            actual = json.loads(output.read_text())
            print(f"{phase}: Python {expected}; Go {actual}", flush=True)
            # Python's commit-time hook supersedes intermediate metric results
            # within its seed transaction. Compare the published results and verify
            # the Go count against its own stored history.
            for env, totals in ((py, expected), (go, actual)):
                with connect(env) as connection:
                    history = connection.execute("SELECT count(*) FROM metric_results WHERE NOT is_current").fetchone()[
                        0
                    ]
                totals["metric_results"] -= history
            compare(py, go)
            assert expected == actual
        check_cli(db, url, Path(directory))
    print("PASS fresh demo sources, calendar, travel, metrics, raw files, prompts and replay")


if __name__ == "__main__":
    if sys.argv[1:] == ["reference"]:
        reference()
    else:
        main()
