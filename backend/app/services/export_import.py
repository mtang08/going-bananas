"""Preflight and optional import of a local Garmin account export."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.garmin.export import ExportError, scan_activities
from app.adapters.garmin.export_recovery import scan_recovery
from app.adapters.garmin.normalize import parse_activity
from app.models import Activity, CoverageInterval, ImportBatch, RawObject, SourceAccount
from app.services.sync import athlete_tz, import_activity_page, import_recovery_page, store_raw


def _store_archive(path: Path, private_dir: Path, digest: str, size: int) -> str:
    target_dir = private_dir / "raw" / "archives"
    target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    target_dir.chmod(0o700)
    target = target_dir / f"{digest}.zip"
    if not target.exists():
        fd, temporary = tempfile.mkstemp(prefix="archive-", dir=target_dir)
        try:
            with os.fdopen(fd, "wb") as output, path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
        finally:
            Path(temporary).unlink(missing_ok=True)
    if target.stat().st_size != size:
        raise ExportError("archive_copy_mismatch")
    with target.open("rb") as stored:
        actual = hashlib.file_digest(stored, "sha256").hexdigest()
    if actual != digest:
        raise ExportError("archive_copy_mismatch")
    return str(target.relative_to(private_dir))


def _raw_object(session: Session, digest: str, relative: str, size: int, media: str) -> None:
    if session.scalar(select(RawObject).where(RawObject.sha256 == digest)) is None:
        session.add(RawObject(sha256=digest, relative_path=relative, byte_size=size, media_type=media))
        session.flush()


def _preflight(session: Session, activities: tuple, scope: str) -> dict[str, int]:
    accounts = session.scalars(select(SourceAccount).where(SourceAccount.provider == "garmin")).all()
    if accounts and any(account.account_scope != scope for account in accounts):
        raise ExportError("mixed_source_account")
    ids = [str(item.normalized["activityId"]) for item in activities]
    existing = session.scalars(select(Activity).where(Activity.garmin_id.in_(ids))).all()
    by_id = {activity.garmin_id: activity for activity in existing}
    overlap = 0
    comparable_fields = 0
    differing_fields = 0
    for item in activities:
        prior = by_id.get(str(item.normalized["activityId"]))
        if prior is None:
            continue
        if accounts and prior.source_account_id != accounts[0].id:
            raise ExportError("mixed_source_account")
        overlap += 1
        start = datetime.fromisoformat(item.normalized["startTimeGMT"])
        comparable_fields += 1
        if abs((start - prior.start_at).total_seconds()) > 1:
            differing_fields += 1
        for source_field, canonical_field in (
            ("distance", "distance_m"),
            ("elapsedDuration", "elapsed_s"),
            ("movingDuration", "moving_s"),
            ("averageHR", "avg_hr_bpm"),
        ):
            new = item.normalized.get(source_field)
            old = getattr(prior, canonical_field)
            if new is not None and old is not None:
                comparable_fields += 1
                if abs(new - old) > max(0.05, abs(old) * 0.001):
                    differing_fields += 1
    return {"existing_activity_overlap": overlap, "new_activity_candidates": len(activities) - overlap,
            "overlap_comparable_fields": comparable_fields, "overlap_differing_fields": differing_fields}


def _coverage(session: Session, dataset: str, dates: list, now: datetime) -> dict[str, object] | None:
    if not dates:
        return None
    start, end = min(dates), max(dates)
    existing = session.scalar(select(CoverageInterval).where(
        CoverageInterval.dataset == dataset, CoverageInterval.start_date == start,
        CoverageInterval.end_date == end, CoverageInterval.reason == "export_snapshot_observed",
    ))
    if existing is None:
        session.add(CoverageInterval(dataset=dataset, start_date=start, end_date=end,
                                     observed_start=start, observed_end=end, status="partial",
                                     completed_at=now, reason="export_snapshot_observed",
                                     fully_enumerated=False))
    return {"first_date": start.isoformat(), "last_date": end.isoformat(), "count": len(dates),
            "fully_enumerated": False}


def import_export(session: Session, private_dir: Path, archive_path: Path, *, apply: bool = False,
                  timezone: str | None = None) -> dict[str, object]:
    """Inspect all input first; with apply=True, persist immutable bytes and revisions.

    The caller owns the transaction. Dry run performs no database or private-file writes.
    """
    if timezone is None:
        timezone = athlete_tz(session)
    try:
        with archive_path.open("rb") as stream:
            archive_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        archive_size = archive_path.stat().st_size
        with ZipFile(archive_path) as archive:
            scan = scan_activities(archive)
            if archive.testzip() is not None:
                raise ExportError("archive_crc_mismatch")
            if not scan.activities:
                raise ExportError("empty_activity_export")
            scope = "garmin-owner:" + scan.activities[0].owner
            recovery_scan = scan_recovery(archive)
            if any(item.account_owner != scan.activities[0].owner for item in recovery_scan.observations):
                raise ExportError("mixed_source_account")
            counts = _preflight(session, scan.activities, scope)
            recovery_counts = Counter(item.metric for item in recovery_scan.observations)
            dataset_dates = {"activities": [date.fromisoformat(parse_activity(item.normalized, timezone).local_date)
                                            for item in scan.activities]}
            dataset_dates.update({metric: [item.source_date for item in recovery_scan.observations
                                           if item.metric == metric] for metric in ("sleep", "hrv", "resting_hr")})
            datasets = {key: {"first_date": min(dates).isoformat(), "last_date": max(dates).isoformat(),
                              "count": len(dates), "fully_enumerated": False}
                        for key, dates in dataset_dates.items() if dates}
            summary: dict[str, object] = {
                "status": "preflight_ok" if not apply else "complete",
                "entries": scan.member_count,
                "activities": len(scan.activities),
                "recovery": dict(recovery_counts),
                "datasets": datasets,
                "preserved_only": recovery_scan.skipped,
                **counts,
            }
            if not apply:
                return summary
            relative = _store_archive(archive_path, private_dir, archive_sha, archive_size)
            _raw_object(session, archive_sha, relative, archive_size, "application/zip")
            activity_member = scan.activities[0].member_name
            member_bytes = archive.read(activity_member)
            member_sha, member_relative = store_raw(private_dir, member_bytes)
            _raw_object(session, member_sha, member_relative, len(member_bytes), "application/json")
            batch = ImportBatch(source_kind="garmin_export", status="running", adapter_version="garmin-export-v1")
            session.add(batch)
            session.flush()
            normalized = [item.normalized for item in scan.activities]
            originals = [item.original for item in scan.activities]
            metadata = [{"archive_sha256": archive_sha, "member_sha256": item.member_sha256,
                         "row_index": item.row_index,
                         "field_paths": {"start_at": "startTimeGmt", "original_start": "startTimeGmt",
                                         "local_date": "startTimeGmt", "sport": "activityType",
                                         "subtype": "activityType", "distance_m": "distance",
                                         "elapsed_s": "elapsedDuration", "moving_s": "movingDuration",
                                         "avg_hr_bpm": "avgHr"},
                         "unit_conversions": {"distance_m": "centimeters_to_meters",
                                              "elapsed_s": "milliseconds_to_seconds",
                                              "moving_s": "milliseconds_to_seconds"},
                         "original_start": str(item.original["startTimeGmt"]),
                         "source_timezone": "garmin_export_GMT_epoch_ms"}
                        for item in scan.activities]
            activity_counts = import_activity_page(
                session, private_dir, normalized, account_scope=scope, source_kind="garmin_export",
                timezone=timezone, batch=batch, raw_records=originals, source_metadata=metadata)
            recovery_results = {}
            recovery_member_hashes: dict[str, str] = {}
            for dataset in ("sleep", "hrv", "resting_hr"):
                observations = [item for item in recovery_scan.observations if item.metric == dataset]
                if not observations:
                    continue
                for member_name in {item.member_name for item in observations}:
                    if member_name in recovery_member_hashes:
                        continue
                    raw_member = archive.read(member_name)
                    digest, member_relative = store_raw(private_dir, raw_member)
                    _raw_object(session, digest, member_relative, len(raw_member), "application/json")
                    recovery_member_hashes[member_name] = digest
                field = {"sleep": "sleepTimeSeconds", "hrv": "lastNightAvg",
                         "resting_hr": "restingHeartRate"}[dataset]
                normalized_recovery = [{"userProfilePK": int(item.account_owner),
                                        "calendarDate": item.source_date.isoformat(), field: item.value}
                                       for item in observations]
                recovery_metadata = [{"archive_sha256": archive_sha,
                                      "member_sha256": recovery_member_hashes[item.member_name],
                                      "source_field": item.source_field,
                                      "source_record_identity": item.source_record_identity}
                                     for item in observations]
                recovery_results[dataset] = import_recovery_page(
                    session, private_dir, dataset, normalized_recovery, batch=batch,
                    source_kind="garmin_export", raw_records=[item.payload for item in observations],
                    source_metadata=recovery_metadata)
            invalid_skipped = sum(count for code, count in recovery_scan.skipped.items()
                                  if not code.endswith("_unsupported"))
            batch.status = ("complete" if activity_counts["rejected"] == 0 and invalid_skipped == 0 and
                            all(row["rejected"] == 0 for row in recovery_results.values()) else "partial")
            batch.finished_at = datetime.now(UTC)
            for dataset, dates in dataset_dates.items():
                _coverage(session, dataset, dates, batch.finished_at)
            batch.counters = {"archive_sha256": archive_sha, "activities": activity_counts,
                              "recovery": recovery_results, "datasets": datasets,
                              "preserved_only": recovery_scan.skipped}
            summary["activity_counts"] = activity_counts
            summary["recovery_counts"] = recovery_results
            summary["replayed"] = (activity_counts["new_revisions"] == 0 and
                                   all(row["new_revisions"] == 0 for row in recovery_results.values()))
            summary["status"] = batch.status
            return summary
    except (OSError, BadZipFile) as exc:
        raise ExportError("invalid_export_archive") from exc
