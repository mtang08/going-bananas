"""Local operational CLI. Run with ``python -m app.cli`` in backend."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, bump_data_revision, engine
from app.models import Activity, AppState, ProfileVersion
from app.services.backup import BackupError, create_backup, restore_backup
from app.services.export_import import import_export
from app.services.sync import ADVISORY_LOCK, enqueue_catchup, enqueue_sync, import_activity_page, run_one_job
from app.services.timezone import local_date


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
    seed = sub.add_parser("seed-demo")
    seed.add_argument("--calendar-preview", action="store_true")
    sync = sub.add_parser("sync")
    sync.add_argument("--start", type=date.fromisoformat)
    sync.add_argument("--end", type=date.fromisoformat)
    sub.add_parser("worker")
    export_import = sub.add_parser("import-export")
    export_import.add_argument("archive", type=Path)
    export_import.add_argument("--apply", action="store_true")
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
    metrics = sub.add_parser("metrics-recompute")
    metrics.add_argument("--metric", default="all")
    metrics.add_argument("--since", type=date.fromisoformat)
    metrics.add_argument("--until", type=date.fromisoformat)
    fit = sub.add_parser("fit-backfill")
    fit.add_argument("--since", type=date.fromisoformat, required=True)
    strong = sub.add_parser("strong-import")
    strong.add_argument("csv", type=Path)
    strong.add_argument("--apply", action="store_true")
    coach = sub.add_parser('coach')
    coach_sub = coach.add_subparsers(dest='coach_command', required=True)
    coach_sub.add_parser('schema')
    from app.services.knowledge import SUPPORTED_OPERATIONS
    snapshot = coach_sub.add_parser('snapshot')
    snapshot.add_argument('--operation', choices=sorted(SUPPORTED_OPERATIONS), required=True)
    snapshot.add_argument('--as-of', type=date.fromisoformat)
    query = coach_sub.add_parser('query')
    query.add_argument('name', choices=['activity_execution', 'long_run_history', 'recovery_nights', 'calendar_diff', 'explain_metric'])
    query.add_argument('--activity-id', type=uuid.UUID)
    query.add_argument('--start', type=date.fromisoformat)
    query.add_argument('--end', type=date.fromisoformat)
    query.add_argument('--from', dest='from_version', type=int)
    query.add_argument('--to', dest='to_version', type=int)
    query.add_argument('--result-id', type=uuid.UUID)
    submit = coach_sub.add_parser('submit')
    submit.add_argument('--file', type=Path, required=True)
    revise = coach_sub.add_parser('revise')
    revise.add_argument('id', type=uuid.UUID)
    revise.add_argument('--expected-revision', type=int, required=True)
    revise.add_argument('--reason', required=True)
    revise.add_argument('--file', type=Path, required=True)
    cutover = sub.add_parser("planning-cutover")
    cutover_mode = cutover.add_mutually_exclusive_group()
    cutover_mode.add_argument("--dry-run", action="store_true")
    cutover_mode.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _coach(args) -> int:
    from fastapi import HTTPException
    from pydantic import ValidationError

    from app.services import knowledge, proposals
    from app.services.decision_inputs import VerifiedKnowledge
    from app.services.timezone import athlete_tz, local_date

    def output(value, *, error=False):
        print(json.dumps(value, default=str, ensure_ascii=False), file=sys.stderr if error else sys.stdout)

    def resolve_kb(selection):
        return VerifiedKnowledge(**knowledge.verify_selection(selection))

    try:
        now = datetime.now(UTC)
        if args.coach_command == 'schema':
            output({'protocol': 'coach_proposal.v1', 'activation': 'manual', 'required_authority': 'calendar',
                'proposal': proposals.ProposalDoc.model_json_schema(),
                'revision': proposals.RevisionRequest.model_json_schema()})
            return 0
        if args.coach_command == 'snapshot':
            from app.services.snapshot import build_snapshot
            with SessionLocal.begin() as session:
                result = build_snapshot(session, args.operation, args.as_of or local_date(now, athlete_tz(session)), now=now)
            output(result)
            return 0
        if args.coach_command in {'submit', 'revise'}:
            try:
                raw = json.loads(args.file.read_text(encoding='utf-8'))
                if not isinstance(raw, dict):
                    raise ValueError('not_object')
            except (OSError, UnicodeError, ValueError):
                output({'proposal_id': None, 'revision': None, 'status': 'invalid', 'errors': [
                    {'code': 'V1.schema', 'path': '', 'message': 'File is not a JSON object'}]})
                return 2
            if args.coach_command == 'revise':
                try:
                    request = proposals.RevisionRequest(expected_revision=args.expected_revision,
                        reason=args.reason, document=raw)
                except ValidationError:
                    output({'proposal_id': str(args.id), 'revision': None, 'status': 'invalid',
                        'error': 'invalid_revision_request', 'errors': [
                            {'code': 'invalid_revision_request', 'path': '', 'message': 'Invalid revision request'}]})
                    return 2
            with SessionLocal.begin() as session:
                if args.coach_command == 'submit':
                    submitted = proposals.submit_proposal(session, raw, now=now, resolve_kb=resolve_kb)
                else:
                    submitted = proposals.revise_proposal(session, args.id, request, now=now, resolve_kb=resolve_kb)
            output({'proposal_id': str(submitted.proposal_id) if submitted.proposal_id else None,
                'revision': submitted.revision, 'status': submitted.status,
                'errors': [issue.to_json() for issue in submitted.issues]})
            return {'pending': 0, 'stale': 3}.get(submitted.status, 2)
        required = {'activity_execution': ('activity_id',), 'long_run_history': ('start', 'end'),
            'recovery_nights': ('start', 'end'), 'calendar_diff': ('from_version', 'to_version'),
            'explain_metric': ('result_id',)}
        flags = {'from_version': '--from', 'to_version': '--to'}
        for field in required[args.name]:
            if getattr(args, field) is None:
                output({'error': 'missing_argument', 'message': f"{flags.get(field, '--'+field.replace('_','-'))} required"}, error=True)
                return 2
        from app.api.metrics import activity_execution, explain_metric, long_run_history, recovery_nights
        from app.services.calendar import calendar_diff
        data: Any
        with SessionLocal() as session:
            if args.name == 'activity_execution':
                data = activity_execution(session, args.activity_id)
            elif args.name == 'long_run_history':
                data = long_run_history(session, args.start, args.end)
            elif args.name == 'recovery_nights':
                data = recovery_nights(session, args.start, args.end)
            elif args.name == 'calendar_diff':
                data = calendar_diff(session, args.from_version, args.to_version)
            else:
                data = explain_metric(session, args.result_id)
            output({'query': args.name, 'data': data})
        return 0
    except knowledge.KnowledgeIntegrityError:
        output({'error': 'knowledge_unavailable'}, error=True)
        return 4
    except proposals.DecisionError as exc:
        if args.coach_command in {'submit', 'revise'}:
            output({'proposal_id': str(args.id) if args.coach_command == 'revise' else None,
                'revision': None, 'status': 'invalid', 'error': exc.code,
                'errors': [issue.to_json() for issue in exc.fields]
                or [{'code': exc.code, 'path': '', 'message': exc.message}]})
        else:
            output({'error': exc.code, 'message': exc.message}, error=True)
        return 3 if exc.code == 'stale_evidence' else 2
    except HTTPException as exc:
        code = exc.detail.get('code', 'request_error') if isinstance(exc.detail, dict) else 'request_error'
        output({'error': code}, error=True)
        return 4 if exc.status_code == 404 else 2
    except Exception:
        output({'error': 'unexpected_error'}, error=True)
        return 1


def main() -> int:
    args = _parse()
    from app.metrics.engine import install_triggers
    install_triggers()
    try:
        if args.command == "coach":
            return _coach(args)
        if args.command == "planning-cutover":
            from fastapi import HTTPException

            from app.services.legacy_cutover import migrate_legacy_state
            try:
                with SessionLocal() as session:
                    report = migrate_legacy_state(session, dry_run=not args.apply)
                    if args.apply:
                        session.commit()
                    else:
                        session.rollback()
            except HTTPException as exc:
                detail: dict = exc.detail if isinstance(exc.detail, dict) else {}
                raise ValueError(detail.get('code', 'cutover_failed')) from None
            print(json.dumps(report, sort_keys=True))
        elif args.command == "metrics-recompute":
            from app.metric_models import MetricResult
            from app.metrics import engine as metrics_engine
            metrics_engine.metric_modules()
            if args.metric != 'all' and args.metric not in metrics_engine.REGISTRY:
                raise ValueError('invalid_metric')
            with SessionLocal.begin() as session:
                today = metrics_engine._today(session)
                since, until = args.since or today - timedelta(days=83), args.until or today
                if since > until or until > today:
                    raise ValueError('invalid_date_window')
                if args.metric != 'all':
                    wanted = {args.metric}
                    pending = [args.metric]
                    while pending:
                        for dependency in metrics_engine.REGISTRY[pending.pop()].depends_on:
                            if dependency not in wanted:
                                wanted.add(dependency)
                                pending.append(dependency)
                    session.info['metrics_filter'] = wanted
                for day_offset in range((until - since).days + 1):
                    metrics_engine.ensure_windows(session, since + timedelta(days=day_offset))
                query = select(MetricResult)
                if args.metric != 'all':
                    query = query.where(MetricResult.metric_id == args.metric)
                rows = list(session.scalars(query))
                metric_summary = {'metric': args.metric, 'since': str(since), 'until': str(until),
                    'subjects': len({(row.metric_id, row.subject_key) for row in rows}),
                    'results_current': sum(row.is_current for row in rows), 'history_rows': len(rows)}
            print(json.dumps(metric_summary))
        elif args.command == "fit-backfill":
            from app.adapters.garmin.personal import GarminPersonalSource
            from app.services.fit_ingest import backfill_fit
            if settings.app_mode != 'real':
                raise ValueError('real_mode_required')
            if args.since > date.today():
                raise ValueError('invalid_date_window')
            key_file = Path(os.getenv('GARMIN_KEY_FILE', settings.private_dir / 'garmin-key'))
            with GarminPersonalSource(key_file, settings.private_dir / 'garmin-token.json') as source:
                print(json.dumps(backfill_fit(SessionLocal, source, settings.private_dir, args.since)))
        elif args.command == "strong-import":
            from app.services.strong_import import import_strong_csv
            with SessionLocal() as session:
                strong_summary = import_strong_csv(session, settings.private_dir, args.csv, apply=args.apply)
                if args.apply:
                    session.commit()
                else:
                    session.rollback()
            print(json.dumps(strong_summary, default=str))
        elif args.command == "seed-demo":
            if settings.app_mode != "demo":
                raise ValueError("demo_mode_required")
            with SessionLocal.begin() as session:
                state = session.get(AppState, 1)
                if args.calendar_preview:
                    if state is None or state.planning_authority != 'calendar':
                        raise ValueError("calendar_preview_authority_required")
                    if state.calendar_head_version == 0 and session.scalar(select(Activity.id).limit(1)):
                        raise ValueError("calendar_preview_requires_empty_activities")
                    from app.demo_seed import seed_demo
                    today = local_date(datetime.now(UTC), ZoneInfo("America/New_York"))
                    counts = seed_demo(session, settings.private_dir, today)
                else:
                    if state is not None and state.planning_authority != 'legacy':
                        raise ValueError("legacy_authority_required")
                    counts = import_activity_page(session, settings.private_dir, _demo_records(),
                                                  account_scope="synthetic-demo", source_kind="demo_fixture")
            if args.calendar_preview:
                from app.demo_seed import demo_totals
                with SessionLocal() as session:
                    counts = demo_totals(session)
            print(json.dumps(counts, sort_keys=True))
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
        elif args.command == "import-export":
            if settings.app_mode != "real":
                raise ValueError("real_mode_required")
            if args.apply:
                with engine.begin() as connection:
                    connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADVISORY_LOCK})
                    with Session(bind=connection) as session:
                        export_result = import_export(session, settings.private_dir, args.archive, apply=True)
                        session.flush()
            else:
                with SessionLocal() as session:
                    export_result = import_export(session, settings.private_dir, args.archive)
            print(json.dumps(export_result, sort_keys=True))
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
