"""Transactional, replay-safe activity import and bounded local sync jobs."""

from __future__ import annotations

import hashlib
import json
import os
import random
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.adapters.garmin.normalize import InvalidRecord, parse_activity
from app.adapters.garmin.personal import GarminPersonalSource
from app.db import SessionLocal, bump_data_revision, engine
from app.models import (
    Activity,
    ActivitySource,
    Conflict,
    CoverageInterval,
    ImportBatch,
    ManualSession,
    RawObject,
    RecoveryObservation,
    SourceAccount,
    SourceRecord,
    SyncJob,
    SyncState,
)

PARSER_VERSION = "garmin-personal-v1"
ADVISORY_LOCK = 837150921


def _required[T](value: T | None) -> T:
    if value is None:
        raise RuntimeError("sync_state_missing")
    return value


def private_raw_path(private_dir: Path, digest: str) -> Path:
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("invalid_digest")
    return private_dir / "raw" / digest[:2] / f"{digest}.json"


def store_raw(private_dir: Path, payload: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(payload).hexdigest()
    path = private_raw_path(private_dir, digest)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    if not path.exists():
        fd, temp_name = tempfile.mkstemp(prefix="raw-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temp_name, 0o600)
            try:
                os.link(temp_name, path)
            except FileExistsError:
                pass
        finally:
            Path(temp_name).unlink(missing_ok=True)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise RuntimeError("raw_hash_mismatch")
    return digest, str(path.relative_to(private_dir))


def _payload(record: dict[str, Any]) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _account(session: Session, provider: str, scope: str) -> SourceAccount:
    existing = session.scalars(select(SourceAccount).where(SourceAccount.provider == provider)).all()
    if existing and any(item.account_scope != scope for item in existing):
        raise ValueError("mixed_source_account")
    if existing:
        return existing[0]
    account = SourceAccount(provider=provider, account_scope=scope)
    session.add(account)
    session.flush()
    return account


def _rank(source: SourceRecord) -> tuple[datetime, int, datetime, str]:
    # Trust source-modified time when present. Then prefer API summary over
    # export. The first persisted observation time remains stable on replay.
    return (source.source_modified_at or datetime.min.replace(tzinfo=UTC),
            2 if source.source_kind == "garmin_api" else 1,
            source.fetched_at, source.payload_hash)


CANONICAL_FIELDS = (
    "start_at", "original_start", "source_timezone", "local_date", "sport",
    "subtype", "distance_m", "elapsed_s", "moving_s", "avg_hr_bpm",
    "cadence_spm", "source_workout_label",
)


def detect_import_conflicts_for_manual(session: Session, manual: ManualSession) -> None:
    """Queue explicit review for same-date imported strength and manual strength."""
    if manual.kind != "strength" or manual.linked_activity_id is not None:
        return
    candidates = session.scalars(select(Activity).where(
        Activity.local_date == manual.date, Activity.sport == "strength",
        Activity.resolution_state.notin_(("merged", "excluded")))).all()
    for activity in candidates:
        existing = session.scalars(select(Conflict).where(
            Conflict.manual_session_id == manual.id,
            Conflict.kind == "manual_import_overlap")).all()
        if any(str(activity.id) in row.activity_ids for row in existing):
            continue
        session.add(Conflict(kind="manual_import_overlap", status="open",
            activity_ids=[str(activity.id)], manual_session_id=manual.id,
            details={"reason": "same_date_strength"}))
        activity.resolution_state = "pending"
        bump_data_revision(session)


def detect_manual_conflicts(session: Session, activity: Activity) -> None:
    if activity.sport != "strength":
        return
    manuals = session.scalars(select(ManualSession).where(
        ManualSession.date == activity.local_date, ManualSession.kind == "strength",
        ManualSession.linked_activity_id.is_(None))).all()
    for manual in manuals:
        detect_import_conflicts_for_manual(session, manual)


def _detect_activity_overlap(session: Session, activity: Activity) -> None:
    if activity.garmin_id is not None:
        return
    others = session.scalars(select(Activity).where(
        Activity.id != activity.id, Activity.local_date == activity.local_date,
        Activity.sport == activity.sport,
        Activity.resolution_state.notin_(("merged", "excluded")))).all()
    for other in others:
        if abs((activity.start_at - other.start_at).total_seconds()) > 300:
            continue
        if activity.distance_m is not None and other.distance_m is not None:
            if abs(activity.distance_m - other.distance_m) > max(50, other.distance_m * 0.02):
                continue
        ids = sorted((str(activity.id), str(other.id)))
        conflicts = session.scalars(select(Conflict).where(Conflict.kind == "activity_overlap")).all()
        if any(sorted(row.activity_ids) == ids for row in conflicts):
            continue
        session.add(Conflict(kind="activity_overlap", status="open", activity_ids=ids,
            details={"reason": "close_time_and_distance", "withheld_count": 1}))
        activity.resolution_state = "pending"
        if other.resolution_state == "pending":
            other.resolution_state = "pending"
        bump_data_revision(session)


def _reconcile(session: Session, account: SourceAccount, identity: str, garmin_id: str | None) -> bool:
    records = list(session.scalars(select(SourceRecord).where(
        SourceRecord.source_account_id == account.id,
        SourceRecord.source_identity == identity,
        SourceRecord.rejected_reason.is_(None),
    )).all())
    if not records:
        return False
    records.sort(key=_rank, reverse=True)
    selected: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    selected_by_record: dict[str, list[str]] = {}
    for field in CANONICAL_FIELDS:
        for source in records:
            value = (source.fields or {}).get(field)
            if value is not None:
                selected[field] = value
                provenance[field] = {"source_record_id": str(source.id), "source_kind": source.source_kind,
                                     "source_field": (source.fields or {}).get("field_paths", {}).get(field)}
                selected_by_record.setdefault(str(source.id), []).append(field)
                break
    if "start_at" not in selected or "sport" not in selected:
        return False
    activity = session.scalar(select(Activity).where(
        Activity.source_account_id == account.id,
        Activity.garmin_id == garmin_id,
    )) if garmin_id else session.scalar(select(Activity).where(
        Activity.source_account_id == account.id, Activity.source_identity == identity,
    ))
    selected["start_at"] = datetime.fromisoformat(selected["start_at"])
    selected["local_date"] = date.fromisoformat(selected["local_date"])
    semantic = {**selected, "field_provenance": provenance}
    changed = activity is None
    if activity is None:
        activity = Activity(source_account_id=account.id, garmin_id=garmin_id,
                            source_identity=identity, **semantic)
        session.add(activity)
        session.flush()
    else:
        for key, value in semantic.items():
            if getattr(activity, key) != value:
                setattr(activity, key, value)
                changed = True
        if changed:
            activity.canonical_revision += 1
    for source in records:
        link = session.scalar(select(ActivitySource).where(
            ActivitySource.activity_id == activity.id,
            ActivitySource.source_record_id == source.id,
        ))
        chosen = selected_by_record.get(str(source.id), [])
        if link is None:
            session.add(ActivitySource(activity_id=activity.id, source_record_id=source.id,
                                       selected_fields=chosen))
        elif link.selected_fields != chosen:
            link.selected_fields = chosen
    if changed:
        bump_data_revision(session)
        _detect_activity_overlap(session, activity)
        detect_manual_conflicts(session, activity)
    return changed


def import_activity_page(session: Session, private_dir: Path, records: list[dict[str, Any]],
                         *, account_scope: str, source_kind: str = "garmin_api",
                         timezone: str = "America/New_York",
                         fetched_at: datetime | None = None,
                         batch: ImportBatch | None = None) -> dict[str, int]:
    """Import one page. Caller commits page, coverage and checkpoint together."""
    if not account_scope or len(account_scope) > 256:
        raise ValueError("invalid_account_scope")
    if not records:
        return {"seen": 0, "new_revisions": 0, "changed": 0, "rejected": 0}
    if source_kind == "garmin_api" and records:
        owners = {str(item.get("ownerId")) for item in records if item.get("ownerId") is not None}
        if len(owners) != 1 or any(item.get("ownerId") is None for item in records):
            raise ValueError("missing_or_mixed_garmin_owner")
        verified_scope = "garmin-owner:" + next(iter(owners))
        if account_scope != "auto" and account_scope != verified_scope:
            raise ValueError("mixed_source_account")
        account_scope = verified_scope
    account = _account(session, "garmin" if source_kind.startswith("garmin") else source_kind, account_scope)
    now = fetched_at or datetime.now(UTC)
    counts = {"seen": 0, "new_revisions": 0, "changed": 0, "rejected": 0}
    for item in records:
        counts["seen"] += 1
        try:
            raw = _payload(item)
        except (TypeError, ValueError):
            counts["rejected"] += 1
            continue
        digest, relative = store_raw(private_dir, raw)
        raw_obj = session.scalar(select(RawObject).where(RawObject.sha256 == digest))
        if raw_obj is None:
            raw_obj = RawObject(sha256=digest, relative_path=relative,
                                byte_size=len(raw), media_type="application/json")
            session.add(raw_obj)
            session.flush()
        try:
            canonical = parse_activity(item, timezone)
            rejected_reason = None
        except InvalidRecord as exc:
            canonical = None
            rejected_reason = exc.code
            counts["rejected"] += 1
        source_identity = f"garmin:{canonical.provider_id}" if canonical and canonical.provider_id else f"hash:{digest}"
        source = session.scalar(select(SourceRecord).where(
            SourceRecord.source_account_id == account.id,
            SourceRecord.source_identity == source_identity,
            SourceRecord.payload_hash == digest,
        ))
        if source is not None:
            continue
        fields: dict[str, Any] = {}
        if canonical:
            fields = {
                "start_at": canonical.start_at.isoformat(), "original_start": canonical.source_time,
                "source_timezone": canonical.timezone_assumption,
                "local_date": canonical.local_date, "sport": canonical.sport,
                "subtype": canonical.subtype, "distance_m": canonical.distance_m,
                "elapsed_s": canonical.elapsed_s, "moving_s": canonical.moving_s,
                "avg_hr_bpm": canonical.average_hr, "cadence_spm": canonical.average_cadence,
                "source_workout_label": canonical.workout_label,
                "field_paths": canonical.field_paths,
            }
        source = SourceRecord(source_account_id=account.id, import_batch_id=batch.id if batch else None,
                              raw_object_id=raw_obj.id, source_identity=source_identity,
                              payload_hash=digest, fetched_at=now, parser_version=PARSER_VERSION,
                              source_kind=source_kind, fields=fields, rejected_reason=rejected_reason)
        session.add(source)
        session.flush()
        counts["new_revisions"] += 1
        if canonical and _reconcile(session, account, source_identity, canonical.provider_id):
            counts["changed"] += 1
    return counts


def import_recovery_page(session: Session, private_dir: Path, dataset: str,
                         records: list[dict[str, Any]], *,
                         batch: ImportBatch | None = None,
                         fetched_at: datetime | None = None) -> dict[str, int]:
    """Store observed daily values; empty days remain absent, never zero."""
    if dataset not in {"sleep", "hrv", "resting_hr"}:
        raise ValueError("unsupported_dataset")
    counts = {"seen": 0, "new_revisions": 0, "changed": 0, "rejected": 0}
    owners = {item.get("userProfilePK", item.get("userProfilePk")) for item in records
              if isinstance(item, dict) and type(item.get("userProfilePK", item.get("userProfilePk"))) is int}
    if len(owners) > 1:
        raise ValueError("mixed_source_account")
    page_owner = next(iter(owners)) if owners else None
    for item in records:
        counts["seen"] += 1
        try:
            if not isinstance(item, dict):
                raise ValueError("invalid_recovery_shape")
            account_id = item.get("userProfilePK", item.get("userProfilePk"))
            missing_owner = isinstance(account_id, bool) or not isinstance(account_id, int)
            if missing_owner:
                account_id = page_owner
            if account_id is None:
                raise ValueError("missing_recovery_owner")
            source_date = date.fromisoformat(item["calendarDate"])
            field, unit, statistic, semantics = {
                "sleep": ("sleepTimeSeconds", "s", "main_sleep_duration", "garmin_sleep_calendar_date"),
                "hrv": ("lastNightAvg", "ms", "last_night_average", "garmin_hrv_calendar_date"),
                "resting_hr": ("restingHeartRate", "bpm", "daily_resting", "garmin_heart_rate_calendar_date"),
            }[dataset]
            value = item.get(field)
            if value is not None:
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not (0 <= float(value) < float("inf"))):
                    raise ValueError("invalid_recovery_value")
            raw = _payload(item)
        except (TypeError, KeyError, ValueError):
            counts["rejected"] += 1
            continue
        account = _account(session, "garmin", f"garmin-owner:{account_id}")
        digest, relative = store_raw(private_dir, raw)
        raw_obj = session.scalar(select(RawObject).where(RawObject.sha256 == digest))
        if raw_obj is None:
            raw_obj = RawObject(sha256=digest, relative_path=relative,
                                byte_size=len(raw), media_type="application/json")
            session.add(raw_obj)
            session.flush()
        identity = f"{dataset}:{source_date.isoformat()}:{statistic}"
        source = session.scalar(select(SourceRecord).where(
            SourceRecord.source_account_id == account.id,
            SourceRecord.source_identity == identity,
            SourceRecord.payload_hash == digest))
        if source is None:
            source = SourceRecord(source_account_id=account.id,
                import_batch_id=batch.id if batch else None, raw_object_id=raw_obj.id,
                source_identity=identity, payload_hash=digest,
                fetched_at=fetched_at or datetime.now(UTC), parser_version=PARSER_VERSION,
                source_kind="garmin_api", fields={"metric": dataset, "source_date": source_date.isoformat(),
                    "value": value, "unit": unit, "statistic": statistic, "source_field": field},
                rejected_reason="missing_recovery_owner" if missing_owner else None)
            session.add(source)
            session.flush()
            counts["new_revisions"] += 1
        if missing_owner:
            counts["rejected"] += 1
            continue
        if value is None:
            continue
        observation = session.scalar(select(RecoveryObservation).where(
            RecoveryObservation.source_account_id == account.id,
            RecoveryObservation.metric == dataset,
            RecoveryObservation.source_date == source_date,
            RecoveryObservation.statistic == statistic))
        if observation is None:
            session.add(RecoveryObservation(source_account_id=account.id, source_record_id=source.id,
                metric=dataset, source_date=source_date, time_semantics=semantics,
                value=float(value), unit=unit, statistic=statistic, source_revision=digest))
            bump_data_revision(session)
            counts["changed"] += 1
        elif observation.source_revision != digest and observation.value != float(value):
            observation.value = float(value)
            observation.source_revision = digest
            observation.source_record_id = source.id
            bump_data_revision(session)
            counts["changed"] += 1
    return counts


def enqueue_sync(session: Session, first: date, last: date, dataset: str = "activities") -> SyncJob:
    if first > last or (last - first).days > 366:
        raise ValueError("invalid_sync_range")
    # Serializes concurrent web/startup/scheduled requests until commit.
    session.execute(text(f"SELECT pg_advisory_xact_lock({ADVISORY_LOCK + 1})"))
    active = session.scalar(select(SyncJob).where(SyncJob.dataset == dataset,
        SyncJob.status.in_(("queued", "running", "retry_wait"))).order_by(SyncJob.created_at))
    if active:
        return active
    job = SyncJob(dataset=dataset, start_date=first, end_date=last, status="queued",
                  checkpoint={"offset": 0}, counters={"seen": 0, "changed": 0, "rejected": 0})
    session.add(job)
    session.flush()
    return job


def catchup_window(today: date, latest_complete_end: date | None, overlap_days: int) -> tuple[date, date]:
    start = today - timedelta(days=overlap_days - 1)
    if latest_complete_end is not None:
        start = min(start, latest_complete_end - timedelta(days=overlap_days - 1))
    return start, min(today, start + timedelta(days=365))


def enqueue_catchup(session: Session, today: date) -> list[SyncJob]:
    """Queue one bounded overlap window for every dataset stale today."""
    jobs: list[SyncJob] = []
    for dataset in ("activities", "sleep", "hrv", "resting_hr"):
        state = session.get(SyncState, dataset)
        if (state and state.last_attempt_at and state.last_attempt_at.date() >= today
                and state.status in {"partial", "failed", "retry_wait", "running"}):
            continue
        latest = session.scalar(select(CoverageInterval).where(
            CoverageInterval.dataset == dataset,
            CoverageInterval.status == "complete").order_by(CoverageInterval.end_date.desc()))
        if latest and latest.end_date >= today:
            continue
        days = 14 if dataset == "activities" else 7
        start, end = catchup_window(today, latest.end_date if latest else None, days)
        jobs.append(enqueue_sync(session, start, end, dataset))
    return jobs


def retry_delay(exc: Exception, attempt: int, now: datetime | None = None) -> float | None:
    status = getattr(exc, "status_code", None)
    if (status not in {429, 500, 502, 503, 504}
            and exc.__class__.__name__ not in {"Timeout", "ConnectTimeout", "ConnectionError"}):
        return None
    headers = getattr(exc, "response", None)
    retry_after = getattr(headers, "headers", {}).get("Retry-After") if headers else None
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            from email.utils import parsedate_to_datetime
            try:
                target = parsedate_to_datetime(retry_after)
                return max(0.0, (target - (now or datetime.now(UTC))).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    return min(300.0, 2 ** attempt + random.uniform(0, 1))


def _run_recovery_job(source: GarminPersonalSource, job: SyncJob, private_dir: Path) -> str:
    first = _required(job.start_date)
    last = _required(job.end_date)
    cursor = date.fromisoformat(job.checkpoint["next_date"]) if job.checkpoint.get("next_date") else first
    while cursor <= last:
        end = min(cursor + timedelta(days=6), last)
        attempts = int(job.checkpoint.get("attempts", 0))
        while True:
            try:
                records = source.fetch_recovery(job.dataset, cursor, end)
                break
            except Exception as exc:
                attempts += 1
                delay = retry_delay(exc, attempts)
                if delay is None or attempts >= 4:
                    raise
                if delay > 30:
                    with SessionLocal() as save:
                        current = _required(save.get(SyncJob, job.id, with_for_update=True))
                        current.status = "retry_wait"
                        current.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
                        current.error_code = "remote_retry"
                        current.checkpoint = {**current.checkpoint, "attempts": attempts}
                        save.commit()
                    return "retry_wait"
                time.sleep(delay)
        with SessionLocal() as page_session:
            current = _required(page_session.get(SyncJob, job.id, with_for_update=True))
            batch = ImportBatch(source_kind="garmin_api", status="running", adapter_version=PARSER_VERSION)
            page_session.add(batch)
            page_session.flush()
            counts = import_recovery_page(page_session, private_dir, job.dataset, records, batch=batch)
            batch.status = "complete"
            batch.finished_at = datetime.now(UTC)
            batch.counters = counts
            current.counters = {key: current.counters.get(key, 0) + counts.get(key, 0)
                                for key in set(current.counters) | set(counts)}
            current.checkpoint = {"next_date": (end + timedelta(days=1)).isoformat(), "attempts": 0}
            current.heartbeat_at = datetime.now(UTC)
            state = _required(page_session.get(SyncState, job.dataset))
            observed = []
            for item in records:
                try:
                    observed.append(date.fromisoformat(item["calendarDate"]))
                except (KeyError, TypeError, ValueError):
                    continue
            if observed:
                newest = datetime.combine(max(observed), datetime.min.time(), UTC)
                if state.newest_observation_at is None or newest > state.newest_observation_at:
                    state.newest_observation_at = newest
            page_session.commit()
        cursor = end + timedelta(days=1)
    with SessionLocal() as final:
        current = _required(final.get(SyncJob, job.id, with_for_update=True))
        partial = current.counters.get("rejected", 0) > 0
        current.status = "partial" if partial else "complete"
        current.finished_at = datetime.now(UTC)
        current.error_code = "rejected_records" if partial else None
        state = _required(final.get(SyncState, job.dataset))
        state.status = "partial" if partial else "complete"
        state.reason = "rejected_records" if partial else None
        if not partial:
            state.last_success_at = datetime.now(UTC)
        state.fully_enumerated = True
        final.add(CoverageInterval(dataset=job.dataset, start_date=first,
            end_date=last, status="partial" if partial else "complete", completed_at=datetime.now(UTC),
            reason="rejected_records" if partial else None,
            fully_enumerated=True))
        final.commit()
    return "partial" if partial else "complete"


def run_one_job(private_dir: Path, key_file: Path, account_scope: str) -> str | None:
    """Drain one queued/retry job; return status, or None if lock/job unavailable."""
    # Session remains bound to a dedicated connection across commits. PostgreSQL
    # session advisory locks belong to that connection, not a pooled Session.
    with engine.connect() as lock_connection, Session(bind=lock_connection, expire_on_commit=False) as session:
        locked = session.scalar(text(f"SELECT pg_try_advisory_lock({ADVISORY_LOCK})"))
        if not locked:
            return None
        try:
            job = session.scalar(select(SyncJob).where(SyncJob.status.in_(("queued", "running", "retry_wait")),
                (SyncJob.next_attempt_at.is_(None)) | (SyncJob.next_attempt_at <= datetime.now(UTC)))
                .order_by(SyncJob.created_at).with_for_update(skip_locked=True))
            if job is None:
                return None
            first = _required(job.start_date)
            last = _required(job.end_date)
            job.status = "running"
            job.heartbeat_at = datetime.now(UTC)
            state = session.get(SyncState, job.dataset)
            if state is None:
                state = SyncState(dataset=job.dataset)
                session.add(state)
            state.last_attempt_at = datetime.now(UTC)
            state.status = "running"
            state.requested_start = job.start_date
            state.requested_end = job.end_date
            session.commit()
            job_id = job.id
            with GarminPersonalSource(key_file, private_dir / "garmin-token.json") as source:
                if job.dataset in {"sleep", "hrv", "resting_hr"}:
                    return _run_recovery_job(source, job, private_dir)
                if job.dataset != "activities":
                    raise ValueError("unsupported_dataset")
                offset = int(job.checkpoint.get("offset", 0))
                seen_pages: set[tuple[str, ...]] = set()
                for _ in range(200):
                    attempts = int(job.checkpoint.get("attempts", 0))
                    while True:
                        try:
                            page = source.search_page(offset, 50, first, last)
                            break
                        except Exception as exc:
                            attempts += 1
                            delay = retry_delay(exc, attempts)
                            if delay is None or attempts >= 4:
                                raise
                            if delay > 30:
                                with SessionLocal() as save:
                                    current = _required(save.get(SyncJob, job_id))
                                    current.status = "retry_wait"
                                    current.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
                                    current.error_code = "remote_retry"
                                    current.checkpoint = {**current.checkpoint, "attempts": attempts}
                                    save.commit()
                                return "retry_wait"
                            time.sleep(delay)
                    signature = tuple(str(x.get("activityId")) for x in page)
                    if page and signature in seen_pages:
                        raise ValueError("repeated_activity_page")
                    seen_pages.add(signature)
                    with SessionLocal() as page_session:
                        current = _required(page_session.get(SyncJob, job_id, with_for_update=True))
                        batch = ImportBatch(source_kind="garmin_api", status="running",
                                            adapter_version=PARSER_VERSION)
                        page_session.add(batch)
                        page_session.flush()
                        counts = import_activity_page(page_session, private_dir, page,
                                                      account_scope=account_scope, batch=batch)
                        batch.status = "complete"
                        batch.finished_at = datetime.now(UTC)
                        batch.counters = counts
                        current.counters = {key: current.counters.get(key, 0) + counts.get(key, 0)
                                            for key in set(current.counters) | set(counts)}
                        offset += len(page)
                        current.checkpoint = {"offset": offset, "attempts": 0}
                        current.heartbeat_at = datetime.now(UTC)
                        state = _required(page_session.get(SyncState, "activities"))
                        observed = []
                        for item in page:
                            try:
                                observed.append(parse_activity(item).start_at)
                            except InvalidRecord:
                                continue
                        if observed:
                            newest = max(observed)
                            if state.newest_observation_at is None or newest > state.newest_observation_at:
                                state.newest_observation_at = newest
                        page_session.commit()
                    if len(page) < 50:
                        with SessionLocal() as final:
                            current = _required(final.get(SyncJob, job_id, with_for_update=True))
                            partial = current.counters.get("rejected", 0) > 0
                            current.status = "partial" if partial else "complete"
                            current.finished_at = datetime.now(UTC)
                            current.error_code = "rejected_records" if partial else None
                            state = _required(final.get(SyncState, "activities"))
                            state.status = "partial" if partial else "complete"
                            state.reason = "rejected_records" if partial else None
                            if not partial:
                                state.last_success_at = datetime.now(UTC)
                            state.fully_enumerated = True
                            final.add(CoverageInterval(dataset="activities", start_date=first,
                                end_date=last, status="partial" if partial else "complete",
                                reason="rejected_records" if partial else None,
                                completed_at=datetime.now(UTC),
                                fully_enumerated=True))
                            final.commit()
                        return "partial" if partial else "complete"
                raise ValueError("activity_page_limit")
        except Exception as exc:
            safe = "credential_attention" if getattr(exc, "status_code", None) in {401, 403} else (
                str(exc) if isinstance(exc, ValueError) and str(exc) in {
                    "unsupported_dataset", "repeated_activity_page", "activity_page_limit",
                    "mixed_source_account"} else "remote_or_import_error")
            with SessionLocal() as failed:
                current = _required(failed.get(SyncJob, job_id, with_for_update=True))
                current.status = "failed"
                current.error_code = safe
                current.finished_at = datetime.now(UTC)
                state = _required(failed.get(SyncState, current.dataset))
                state.status = "failed"
                state.reason = safe
                state.fully_enumerated = False
                failed.add(CoverageInterval(dataset=current.dataset,
                    start_date=_required(current.start_date), end_date=_required(current.end_date),
                    status="failed", reason=safe, fully_enumerated=False))
                failed.commit()
            return "failed"
        finally:
            session.execute(text(f"SELECT pg_advisory_unlock({ADVISORY_LOCK})"))
            session.commit()
