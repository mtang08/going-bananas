"""Review new Garmin treadmill runs before writing their source records."""

from __future__ import annotations

import os
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.garmin.fit import MAX_FIT_BYTES, DecodedLap, FitDecodeError, decode_fit, extract_fit
from app.adapters.garmin.normalize import CanonicalActivity, parse_activity
from app.adapters.garmin.personal import GarminPersonalSource, GarminRemoteError
from app.db import global_write_lock
from app.domain.sports import RUN_SPORTS
from app.errors import fail
from app.logs import exception_summary, get
from app.models import Activity, CoverageInterval, ImportBatch, SourceAccount, SyncJob, SyncState
from app.services.fit_ingest import ingest_activity_fit_bytes
from app.services.sync import PARSER_VERSION, garmin_page_scope, import_activity_page, timezone_name
from app.services.treadmill_intervals import set_treadmill_interval_paces

METRES_PER_MILE = 1609.344
log = get("treadmill_review")


@dataclass(frozen=True)
class Preview:
    account_scope: str
    local_date: str
    record: dict[str, Any]
    canonical: CanonicalActivity
    zip_bytes: bytes | None
    fit_timer_s: float | None
    laps: tuple[DecodedLap, ...]


_previews: OrderedDict[str, Preview] = OrderedDict()
_preview_lock = Lock()


def _pending_jobs(session: Session, remote_id: str | None = None, *, lock: bool = False) -> list[SyncJob]:
    pending = SyncJob.checkpoint["pending_treadmill"]
    query = select(SyncJob).where(SyncJob.dataset == "activities")
    query = query.where(pending.has_key(remote_id) if remote_id is not None else pending != {})
    query = query.order_by(SyncJob.created_at, SyncJob.id)
    if lock:
        query = query.with_for_update()
    return list(session.scalars(query))


def pending_treadmill_runs(session: Session) -> list[dict[str, str]]:
    items = {}
    for job in _pending_jobs(session):
        for remote_id, entry in job.checkpoint["pending_treadmill"].items():
            items[remote_id] = {"id": remote_id, "local_date": entry["local_date"]}
    return sorted(items.values(), key=lambda item: (item["local_date"], item["id"]), reverse=True)


def _fetch_preview(private_dir: Path, remote_id: str, entry: dict[str, str], timezone: str) -> Preview:
    key_file = Path(os.getenv("GARMIN_KEY_FILE", private_dir / "garmin-key"))
    day = date.fromisoformat(entry["local_date"])
    with GarminPersonalSource(key_file, private_dir / "garmin-token.json") as source:
        # Search the same summary feed used by sync. The provider's date filter
        # can differ from the athlete's timezone near midnight.
        record = next(
            (
                item
                for _, page in source.pages(day - timedelta(days=1), day + timedelta(days=1))
                for item in page
                if str(item.get("activityId") or item.get("id")) == remote_id
            ),
            None,
        )
        if record is None:
            fail("treadmill_summary_unavailable", "Garmin did not return this treadmill run. Try again.", 502)
        garmin_page_scope([record], entry["account_scope"])
        canonical = parse_activity(record, timezone)
        if canonical.subtype != "treadmill_running":
            fail("treadmill_summary_changed", "Garmin no longer lists this activity as a treadmill run.", 409)
        try:
            zip_bytes = source.download_activity(remote_id)
        except GarminRemoteError as exc:
            if exc.status_code != 404:
                raise
            zip_bytes = None

    laps: tuple[DecodedLap, ...] = ()
    fit_timer_s = None
    if zip_bytes is not None:
        if len(zip_bytes) > MAX_FIT_BYTES:
            raise FitDecodeError("fit_archive_too_large")
        try:
            decoded = decode_fit(extract_fit(zip_bytes))
        except FitDecodeError as exc:
            log.info("FIT preview unavailable activity_id=%s code=%s", remote_id, exc.code)
        else:
            if decoded.session.start_at == canonical.start_at and decoded.session.sport in RUN_SPORTS:
                fit_timer_s = decoded.session.timer_s
                laps = tuple(sorted(decoded.laps, key=lambda lap: lap.lap_index))

    return Preview(entry["account_scope"], entry["local_date"], record, canonical, zip_bytes, fit_timer_s, laps)


def treadmill_preview(session: Session, private_dir: Path, remote_id: str) -> dict[str, Any]:
    jobs = _pending_jobs(session, remote_id)
    if not jobs:
        fail("treadmill_review_not_found", "This treadmill run is no longer pending.", 404)
    entry = jobs[-1].checkpoint["pending_treadmill"][remote_id]
    timezone = timezone_name(session)
    session.rollback()
    try:
        preview = _fetch_preview(private_dir, remote_id, entry, timezone)
    except (OSError, ValueError, RuntimeError) as exc:
        log.error("Garmin review fetch failed activity_id=%s %s", remote_id, exception_summary(exc))
        fail("treadmill_review_unavailable", "Could not load this treadmill run from Garmin. Try again.", 502)
    token = uuid.uuid4().hex
    with _preview_lock:
        _previews[token] = preview
        if len(_previews) > 4:
            _previews.popitem(last=False)
    title = preview.record.get("activityName")
    return {
        "id": remote_id,
        "preview_token": token,
        "local_date": preview.canonical.local_date,
        "title": title if isinstance(title, str) else None,
        "distance_m": preview.canonical.distance_m,
        "timer_s": preview.fit_timer_s,
        "intervals": [
            {
                "lap_index": lap.lap_index,
                "timer_s": lap.timer_s,
                "intensity": lap.intensity,
                "recorded_pace_seconds_per_mile": METRES_PER_MILE / lap.avg_speed_mps
                if lap.avg_speed_mps and lap.avg_speed_mps > 0
                else None,
            }
            for lap in preview.laps
        ],
    }


def _resolve_reviews(session: Session, jobs: list[SyncJob], remote_ids: set[str], *, confirmed: bool) -> None:
    state = session.get(SyncState, "activities")
    for job in jobs:
        checkpoint = dict(job.checkpoint)
        pending = dict(checkpoint.pop("pending_treadmill"))
        resolved = pending.keys() & remote_ids
        if not resolved:
            continue
        for remote_id in resolved:
            del pending[remote_id]
        if pending:
            checkpoint["pending_treadmill"] = pending
        elif coverage_id := checkpoint.pop("pending_coverage_id", None):
            coverage = session.get(CoverageInterval, uuid.UUID(coverage_id))
            if coverage is not None:
                coverage.status = "complete"
                coverage.reason = None
                coverage.completed_at = datetime.now(UTC)
            if (
                state is not None
                and state.reason == "treadmill_review_pending"
                and state.last_attempt_at is not None
                and job.finished_at is not None
                and state.last_attempt_at <= job.finished_at
            ):
                state.status = "complete"
                state.reason = None
                state.last_success_at = datetime.now(UTC)
        job.checkpoint = checkpoint
        if confirmed:
            job.counters = {
                **job.counters,
                "seen": job.counters.get("seen", 0) + len(resolved),
                "changed": job.counters.get("changed", 0) + len(resolved),
                "new_revisions": job.counters.get("new_revisions", 0) + len(resolved),
            }


def resolve_imported_reviews(session: Session, remote_ids: set[str]) -> None:
    """Clear reviews when a later sync imports their IDs, e.g. after reclassification."""
    if not remote_ids:
        return
    jobs = [job for job in _pending_jobs(session) if remote_ids.intersection(job.checkpoint["pending_treadmill"])]
    if not jobs:
        return
    imported = set(session.scalars(select(Activity.garmin_id).where(Activity.garmin_id.in_(remote_ids))))
    _resolve_reviews(session, jobs, remote_ids.intersection(imported), confirmed=False)


def confirm_treadmill(
    session: Session, private_dir: Path, remote_id: str, token: str, paces: dict[int, float]
) -> uuid.UUID:
    with _preview_lock:
        preview = _previews.get(token)
    if preview is None or preview.canonical.provider_id != remote_id:
        fail("treadmill_review_reload_required", "Reload the treadmill review before saving.", 409)
    global_write_lock(session)
    jobs = _pending_jobs(session, remote_id, lock=True)
    if not jobs:
        fail("treadmill_review_not_found", "This treadmill run is no longer pending.", 404)
    if jobs[-1].checkpoint["pending_treadmill"][remote_id] != {
        "account_scope": preview.account_scope,
        "local_date": preview.local_date,
    }:
        fail("treadmill_review_reload_required", "Reload the treadmill review before saving.", 409)
    if set(paces) - {lap.lap_index for lap in preview.laps}:
        fail("treadmill_lap_invalid", "One or more pace entries do not match the reviewed intervals.")
    batch = ImportBatch(source_kind="garmin_api", status="running", adapter_version=PARSER_VERSION)
    session.add(batch)
    session.flush()
    counts = import_activity_page(
        session, private_dir, [preview.record], account_scope=preview.account_scope, batch=batch
    )
    activity = session.scalar(
        select(Activity)
        .join(SourceAccount, Activity.source_account_id == SourceAccount.id)
        .where(SourceAccount.account_scope == preview.account_scope, Activity.garmin_id == remote_id)
    )
    if activity is None or activity.sport != "treadmill_running":
        fail("treadmill_import_failed", "The reviewed treadmill run could not be saved.", 409)
    if preview.zip_bytes is not None:
        fit_status = ingest_activity_fit_bytes(session, private_dir, activity, preview.zip_bytes)
        if paces and fit_status != "decoded":
            fail("treadmill_fit_changed", "Reload the treadmill review before saving.", 409)
    set_treadmill_interval_paces(session, activity.id, paces)
    batch.status = "complete"
    batch.counters = counts
    batch.finished_at = datetime.now(UTC)
    state = session.get(SyncState, "activities")
    if state is not None and (state.newest_observation_at is None or activity.start_at > state.newest_observation_at):
        state.newest_observation_at = activity.start_at
    _resolve_reviews(session, jobs, {remote_id}, confirmed=True)
    session.commit()
    with _preview_lock:
        _previews.pop(token, None)
    return activity.id
