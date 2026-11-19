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

from sqlalchemy import MetaData, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, engine, global_write_lock
from app.domain.local_time import date_in_zone
from app.logs import configure
from app.models import AppState
from app.services.backup import BackupError, create_backup, restore_backup
from app.services.export_import import import_export
from app.services.sync import ADVISORY_LOCK, enqueue_catchup, enqueue_sync, run_one_job
from app.services.timezone import DEFAULT_TIMEZONE


def _scope() -> str:
    if not (
        os.getenv("GARMIN_API_KEY")
        or os.getenv("GARMIN_PERSONAL_API_KEY")
        or Path(os.getenv("GARMIN_KEY_FILE", settings.private_dir / "garmin-key")).is_file()
    ):
        raise ValueError("garmin_credential_missing")
    return "auto"  # Every live page is bound to its verified Garmin ownerId.


def _prepare_calendar_preview(session: Session) -> AppState:
    global_write_lock(session)
    state = session.get(AppState, 1, with_for_update=True)
    assert state is not None
    if state.calendar_head_version == 0:
        metadata = MetaData()
        metadata.reflect(bind=session.connection())
        if state.data_revision != 0 or any(
            session.scalar(select(1).select_from(table).limit(1)) is not None
            for table in metadata.tables.values()
            if table.name not in {"app_state", "alembic_version"}
        ):
            raise ValueError("calendar_preview_requires_empty_database")
    return state


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed-demo")
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
    metrics = sub.add_parser("metrics-recompute")
    metrics.add_argument("--metric", default="all")
    metrics.add_argument("--since", type=date.fromisoformat)
    metrics.add_argument("--until", type=date.fromisoformat)
    sub.add_parser("metrics-refresh-today")
    assess = sub.add_parser("metrics-assess-session")
    assess.add_argument("--session-uid", type=uuid.UUID, required=True)
    assess.add_argument("--apply", action="store_true")
    fit = sub.add_parser("fit-backfill")
    fit.add_argument("--since", type=date.fromisoformat, required=True)
    reprocess = sub.add_parser(
        "fit-reprocess",
        description="Re-decode retained FIT archives offline. "
        "Applying re-runs metric refresh and same-day matching for the touched dates.",
    )
    reprocess.add_argument("--since", type=date.fromisoformat, required=True)
    reprocess.add_argument("--activity-id", type=uuid.UUID)
    reprocess.add_argument("--apply", action="store_true")
    strong = sub.add_parser("strong-import")
    strong.add_argument("csv", type=Path)
    strong.add_argument("--apply", action="store_true")
    coach = sub.add_parser("coach")
    coach_sub = coach.add_subparsers(dest="coach_command", required=True)
    coach_sub.add_parser("schema")
    from app.services.knowledge import SUPPORTED_OPERATIONS

    snapshot = coach_sub.add_parser("snapshot")
    snapshot.add_argument("--operation", choices=sorted(SUPPORTED_OPERATIONS), required=True)
    snapshot.add_argument("--as-of", type=date.fromisoformat)
    query = coach_sub.add_parser("query")
    query.add_argument(
        "name", choices=["activity_execution", "long_run_history", "recovery_nights", "calendar_diff", "explain_metric"]
    )
    query.add_argument("--activity-id", type=uuid.UUID)
    query.add_argument("--start", type=date.fromisoformat)
    query.add_argument("--end", type=date.fromisoformat)
    query.add_argument("--from", dest="from_version", type=int)
    query.add_argument("--to", dest="to_version", type=int)
    query.add_argument("--result-id", type=uuid.UUID)
    submit = coach_sub.add_parser("submit")
    submit.add_argument("--file", type=Path, required=True)
    revise = coach_sub.add_parser("revise")
    revise.add_argument("id", type=uuid.UUID)
    revise.add_argument("--expected-revision", type=int, required=True)
    revise.add_argument("--reason", required=True)
    revise.add_argument("--file", type=Path, required=True)
    return parser.parse_args()


def _coach(args) -> int:
    from pydantic import ValidationError

    from app.errors import AppError
    from app.services import knowledge
    from app.services.decision_inputs import VerifiedKnowledge
    from app.services.proposals.lifecycle import RevisionRequest, revise_proposal, submit_proposal
    from app.services.proposals.schema import DecisionError, ProposalDoc
    from app.services.timezone import athlete_tz

    def output(value, *, error=False):
        print(json.dumps(value, default=str, ensure_ascii=False), file=sys.stderr if error else sys.stdout)

    def resolve_kb(selection):
        return VerifiedKnowledge(**knowledge.verify_selection(selection))

    try:
        now = datetime.now(UTC)
        if args.coach_command == "schema":
            output(
                {
                    "protocol": "coach_proposal.v1",
                    "activation": "manual",
                    "required_authority": "calendar",
                    "proposal": ProposalDoc.model_json_schema(),
                    "revision": RevisionRequest.model_json_schema(),
                }
            )
            return 0
        if args.coach_command == "snapshot":
            from app.services.snapshot.build import build_snapshot

            with SessionLocal.begin() as session:
                result = build_snapshot(
                    session, args.operation, args.as_of or date_in_zone(now, athlete_tz(session)), now=now
                )
            output(result)
            return 0
        if args.coach_command in {"submit", "revise"}:
            try:
                raw = json.loads(args.file.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("not_object")
            except (OSError, UnicodeError, ValueError):
                output(
                    {
                        "proposal_id": None,
                        "revision": None,
                        "status": "invalid",
                        "errors": [{"code": "V1.schema", "path": "", "message": "File is not a JSON object"}],
                    }
                )
                return 2
            if args.coach_command == "revise":
                try:
                    request = RevisionRequest(
                        expected_revision=args.expected_revision, reason=args.reason, document=raw
                    )
                except ValidationError:
                    output(
                        {
                            "proposal_id": str(args.id),
                            "revision": None,
                            "status": "invalid",
                            "error": "invalid_revision_request",
                            "errors": [
                                {"code": "invalid_revision_request", "path": "", "message": "Invalid revision request"}
                            ],
                        }
                    )
                    return 2
            with SessionLocal.begin() as session:
                if args.coach_command == "submit":
                    submitted = submit_proposal(session, raw, now=now, resolve_kb=resolve_kb)
                else:
                    submitted = revise_proposal(session, args.id, request, now=now, resolve_kb=resolve_kb)
            output(
                {
                    "proposal_id": str(submitted.proposal_id) if submitted.proposal_id else None,
                    "revision": submitted.revision,
                    "status": submitted.status,
                    "errors": [issue.to_json() for issue in submitted.issues],
                }
            )
            return {"pending": 0, "stale": 3}.get(submitted.status, 2)
        required = {
            "activity_execution": ("activity_id",),
            "long_run_history": ("start", "end"),
            "recovery_nights": ("start", "end"),
            "calendar_diff": ("from_version", "to_version"),
            "explain_metric": ("result_id",),
        }
        flags = {"from_version": "--from", "to_version": "--to"}
        for field in required[args.name]:
            if getattr(args, field) is None:
                output(
                    {
                        "error": "missing_argument",
                        "message": f"{flags.get(field, '--' + field.replace('_', '-'))} required",
                    },
                    error=True,
                )
                return 2
        from app.api.metrics import activity_execution, explain_metric, long_run_history, recovery_nights
        from app.services.calendar import calendar_diff

        data: Any
        with SessionLocal() as session:
            if args.name == "activity_execution":
                data = activity_execution(session, args.activity_id)
            elif args.name == "long_run_history":
                data = long_run_history(session, args.start, args.end)
            elif args.name == "recovery_nights":
                data = recovery_nights(session, args.start, args.end)
            elif args.name == "calendar_diff":
                data = calendar_diff(session, args.from_version, args.to_version)
            else:
                data = explain_metric(session, args.result_id)
            output({"query": args.name, "data": data})
        return 0
    except knowledge.KnowledgeIntegrityError:
        output({"error": "knowledge_unavailable"}, error=True)
        return 4
    except DecisionError as exc:
        if args.coach_command in {"submit", "revise"}:
            output(
                {
                    "proposal_id": str(args.id) if args.coach_command == "revise" else None,
                    "revision": None,
                    "status": "invalid",
                    "error": exc.code,
                    "errors": [issue.to_json() for issue in exc.fields]
                    or [{"code": exc.code, "path": "", "message": exc.message}],
                }
            )
        else:
            output({"error": exc.code, "message": exc.message}, error=True)
        return 3 if exc.code == "stale_evidence" else 2
    except AppError as exc:
        output({"error": exc.code}, error=True)
        return 4 if exc.status_code == 404 else 2
    except Exception:
        output({"error": "unexpected_error"}, error=True)
        return 1


def main() -> int:
    args = _parse()
    configure(settings.private_dir)
    from app.services import derived

    derived.install()
    try:
        if args.command == "coach":
            return _coach(args)
        if args.command == "metrics-refresh-today":
            with SessionLocal.begin() as session:
                startup_summary = derived.refresh_today(session)
            print(json.dumps(startup_summary))
        elif args.command == "metrics-recompute":
            from app.metric_models import MetricResult
            from app.metrics import engine as metrics_engine
            from app.metrics import refresh

            metrics_engine.metric_modules()
            if args.metric != "all" and args.metric not in metrics_engine.REGISTRY:
                raise ValueError("invalid_metric")
            with SessionLocal.begin() as session:
                today = refresh.local_today(session)
                since, until = args.since or today - timedelta(days=83), args.until or today
                if since > until or until > today:
                    raise ValueError("invalid_date_window")
                if args.metric != "all":
                    wanted = {args.metric}
                    pending = [args.metric]
                    while pending:
                        for dependency in metrics_engine.REGISTRY[pending.pop()].depends_on:
                            if dependency not in wanted:
                                wanted.add(dependency)
                                pending.append(dependency)
                    session.info["metrics_filter"] = wanted
                for day_offset in range((until - since).days + 1):
                    refresh.ensure_windows(session, since + timedelta(days=day_offset))
                query = select(MetricResult)
                if args.metric != "all":
                    query = query.where(MetricResult.metric_id == args.metric)
                rows = list(session.scalars(query))
                versions = {metric.metric_id: metric.method_version for metric in metrics_engine.REGISTRY.values()}
                metric_summary = {
                    "metric": args.metric,
                    "since": str(since),
                    "until": str(until),
                    "subjects": len({(row.metric_id, row.subject_key) for row in rows}),
                    "results_current": sum(
                        row.is_current and versions.get(row.metric_id) == row.method_version for row in rows
                    ),
                    "history_rows": len(rows),
                }
            print(json.dumps(metric_summary))
        elif args.command == "metrics-assess-session":
            from app.calendar_models import SessionCompletion
            from app.metrics import engine as metrics_engine
            from app.metrics import intervals, planned_actual
            from app.metrics.refresh import assess_completion

            uid = args.session_uid
            session_key = str(uid)
            with SessionLocal() as session:
                completion = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == uid))
                if completion is None:
                    raise ValueError("completion_not_found")
                activity_key = str(completion.activity_id) if completion.activity_id is not None else None

                def snapshot(completion: SessionCompletion) -> dict[str, Any]:
                    interval = None
                    if activity_key is not None:
                        interval = metrics_engine.current_results(
                            session,
                            intervals.METRIC_ID,
                            [activity_key],
                        ).get(activity_key)
                    comparison = metrics_engine.current_results(
                        session,
                        planned_actual.METRIC_ID,
                        [session_key],
                    ).get(session_key)
                    comparison_snapshot = None
                    if comparison is not None:
                        assert comparison.value is not None
                        comparison_snapshot = {
                            "status": comparison.status,
                            "overall_status": comparison.value["overall_status"],
                            "components": comparison.value["components"],
                            "reason_codes": comparison.reason_codes,
                            "config_hash": comparison.config_hash,
                        }
                    return {
                        "completion_status": completion.status,
                        "completion_version": completion.version,
                        "interval": {
                            "status": interval.status,
                            "reason_codes": interval.reason_codes,
                            "quality_flags": interval.quality_flags,
                            "step_completion_ratio": (interval.value or {}).get("step_completion_ratio"),
                            "config_hash": interval.config_hash,
                        }
                        if interval is not None
                        else None,
                        "planned_actual": comparison_snapshot,
                    }

                before = snapshot(completion)
                assess_completion(session, uid)
                after = snapshot(completion)
                if args.apply:
                    session.commit()
                else:
                    session.rollback()
            print(
                json.dumps(
                    {
                        "session_uid": session_key,
                        "activity_id": activity_key,
                        "applied": args.apply,
                        "before": before,
                        "after": after,
                    },
                    sort_keys=True,
                    default=str,
                )
            )
        elif args.command == "fit-backfill":
            from app.adapters.garmin.personal import GarminPersonalSource
            from app.services.fit_ingest import backfill_fit

            if settings.app_mode != "real":
                raise ValueError("real_mode_required")
            if args.since > date.today():
                raise ValueError("invalid_date_window")
            key_file = Path(os.getenv("GARMIN_KEY_FILE", settings.private_dir / "garmin-key"))
            with GarminPersonalSource(key_file, settings.private_dir / "garmin-token.json") as source:
                print(json.dumps(backfill_fit(SessionLocal, source, settings.private_dir, args.since)))
        elif args.command == "fit-reprocess":
            from app.services.fit_ingest import reprocess_fits

            with SessionLocal() as session:
                summary = reprocess_fits(session, settings.private_dir, args.since, args.activity_id)
                if args.apply:
                    session.commit()
                else:
                    session.rollback()
            print(json.dumps({"mode": "apply" if args.apply else "dry_run", **summary}))
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
            from app.demo_seed import demo_totals, seed_demo

            with SessionLocal.begin() as session:
                _prepare_calendar_preview(session)
                today = date_in_zone(datetime.now(UTC), ZoneInfo(DEFAULT_TIMEZONE))
                seed_demo(session, settings.private_dir, today)
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
                    jobs += [
                        enqueue_sync(session, recovery_start, end, dataset)
                        for dataset in ("sleep", "hrv", "resting_hr")
                    ]
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
        return 0
    except (ValueError, BackupError) as exc:
        # Known safe codes only; never echo raw network exceptions or payloads.
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
