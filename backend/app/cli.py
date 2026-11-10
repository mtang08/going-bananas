"""Local operational CLI. Run with ``python -m app.cli`` in backend."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.config import settings
from app.db import SessionLocal, bump_data_revision
from app.models import ProfileVersion
from app.services.backup import BackupError, create_backup, restore_backup
from app.services.sync import enqueue_catchup, enqueue_sync, import_activity_page, run_one_job


def _scope() -> str:
    if not (os.getenv("GARMIN_API_KEY") or os.getenv("GARMIN_PERSONAL_API_KEY") or
            Path(os.getenv("GARMIN_KEY_FILE", settings.private_dir / "garmin-key")).is_file()):
        raise ValueError("garmin_credential_missing")
    return "auto"  # Every live page is bound to its verified Garmin ownerId.


def _demo_records() -> list[dict]:
    today = date.today()
    def stamp(days_ago: int) -> str:
        return (today - timedelta(days=days_ago)).isoformat() + "T12:00:00Z"
    return [
        {"activityId": 1001, "startTimeGMT": stamp(13), "activityType": {"typeKey": "running"},
         "distance": 1609.344, "elapsedDuration": 700, "movingDuration": 600},
        {"activityId": 1002, "startTimeGMT": stamp(7), "activityType": {"typeKey": "running"},
         "distance": 3218.688, "elapsedDuration": 1300, "movingDuration": 1250},
        {"activityId": 1003, "startTimeGMT": stamp(4), "activityType": {"typeKey": "running"},
         "distance": 4828.032, "elapsedDuration": 1950, "movingDuration": 1890},
        {"activityId": 1004, "startTimeGMT": stamp(1), "activityType": {"typeKey": "running"},
         "distance": 6437.376, "elapsedDuration": 2400, "movingDuration": 2350},
        {"activityId": 1005, "startTimeGMT": stamp(2), "activityType": {"typeKey": "strength_training"},
         "elapsedDuration": 2700, "movingDuration": 2400},
    ]


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed-demo")
    sync = sub.add_parser("sync")
    sync.add_argument("--start", type=date.fromisoformat)
    sync.add_argument("--end", type=date.fromisoformat)
    sub.add_parser("worker")
    backup = sub.add_parser("backup")
    backup.add_argument("output", type=Path)
    restore = sub.add_parser("restore")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--target-database-name", required=True)
    restore.add_argument("--target-private-dir", required=True, type=Path)
    context = sub.add_parser("export-context")
    context.add_argument("output", type=Path)
    profile = sub.add_parser("init-profile")
    profile.add_argument("--timezone", default="America/New_York")
    profile.add_argument("--facts-file", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse()
    try:
        if args.command == "seed-demo":
            if settings.app_mode != "demo":
                raise ValueError("demo_mode_required")
            with SessionLocal.begin() as session:
                counts = import_activity_page(session, settings.private_dir, _demo_records(),
                                              account_scope="synthetic-demo", source_kind="demo_fixture")
            print(json.dumps(counts))
        elif args.command in {"sync", "worker"}:
            if settings.app_mode != "real":
                raise ValueError("real_mode_required")
            key_file = Path(os.getenv("GARMIN_KEY_FILE", settings.private_dir / "garmin-key"))
            if args.command == "sync":
                scope = _scope()
                end = args.end or date.today()
                start = args.start or end - timedelta(days=13)
                with SessionLocal.begin() as session:
                    jobs = [enqueue_sync(session, start, end, "activities")]
                    recovery_start = start if args.start else end - timedelta(days=6)
                    jobs += [enqueue_sync(session, recovery_start, end, dataset)
                             for dataset in ("sleep", "hrv", "resting_hr")]
                    print(json.dumps({"job_ids": [str(job.id) for job in jobs]}))
                results = [run_one_job(settings.private_dir, key_file, scope) for _ in jobs]
                print(json.dumps({"results": results}))
                return 0 if all(result == "complete" for result in results) else 1
            need_catchup = True
            while True:
                try:
                    scope = _scope()
                except ValueError:
                    time.sleep(60)
                    continue
                if need_catchup:
                    with SessionLocal.begin() as session:
                        enqueue_catchup(session, date.today())
                    need_catchup = False
                result = run_one_job(settings.private_dir, key_file, scope)
                if result == "complete":
                    need_catchup = True
                if result is None:
                    time.sleep(15)
        elif args.command == "backup":
            manifest = create_backup(settings.database_url, settings.private_dir, args.output)
            print(json.dumps({"created_at": manifest["created_at"], "file_count": len(manifest["files"])}))
        elif args.command == "restore":
            if not args.target_database_name.replace("_", "").isalnum():
                raise ValueError("invalid_target_database_name")
            current_url = make_url(settings.database_url)
            if args.target_database_name == current_url.database:
                raise ValueError("restore_target_is_current_database")
            target_url = current_url.set(database=args.target_database_name).render_as_string(hide_password=False)
            manifest = restore_backup(args.archive, target_url, args.target_private_dir)
            print(json.dumps({"restored_at": manifest["created_at"], "file_count": len(manifest["files"])}))
        elif args.command == "init-profile":
            facts = json.loads(args.facts_file.read_text()) if args.facts_file else {}
            if not isinstance(facts, dict):
                raise ValueError("invalid_profile_facts")
            with SessionLocal.begin() as session:
                latest = session.scalar(select(ProfileVersion).order_by(ProfileVersion.version.desc()))
                if latest:
                    raise ValueError("profile_already_initialized")
                session.add(ProfileVersion(version=1, effective_at=datetime.now(UTC),
                                           timezone=args.timezone, facts=facts, preferences={},
                                           unknowns=[]))
                bump_data_revision(session)
            print(json.dumps({"profile_version": 1}))
        elif args.command == "export-context":
            from app.services.summary import build_context
            with SessionLocal() as session:
                context = build_context(session)
            if args.output.exists():
                raise ValueError("context_output_exists")
            args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            args.output.write_text(json.dumps(context, default=str, sort_keys=True))
            args.output.chmod(0o600)
            print(json.dumps({"status": "created"}))
        return 0
    except (ValueError, BackupError) as exc:
        # Known safe codes only; never echo raw network exceptions or payloads.
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
