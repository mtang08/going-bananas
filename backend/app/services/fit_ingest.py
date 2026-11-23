"""Private ZIP storage and transaction-scoped, replay-safe FIT ingestion."""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol, TypedDict

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.adapters.garmin.fit import DECODER_VERSION, FitDecodeError, decode_fit, extract_fit
from app.checkin_models import SessionRpe
from app.db import bump_data_revision, global_write_lock
from app.domain.sports import RUN_SPORTS
from app.fit_models import ActivityLap, ActivityStream, ActivityWorkoutStep, FitFile
from app.logs import exception_summary, get
from app.models import Activity, ActivitySource, RawObject, SourceRecord
from app.services.timezone import athlete_tz

log = get("fit_ingest")


class FitSource(Protocol):
    def download_activity(self, activity_id: str) -> bytes: ...


class FitIngestError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _remote_id(session: Session, activity: Activity) -> str:
    identities = session.scalars(
        select(SourceRecord.source_identity)
        .join(ActivitySource, ActivitySource.source_record_id == SourceRecord.id)
        .where(ActivitySource.activity_id == activity.id, SourceRecord.rejected_reason.is_(None))
    ).all()
    ids = {
        identity[7:]
        for identity in identities
        if isinstance(identity, str) and identity.startswith("garmin:") and identity[7:]
    }
    if not ids:
        raise FitIngestError("fit_remote_id_missing")
    if len(ids) != 1:
        raise FitIngestError("fit_remote_id_ambiguous")
    return next(iter(ids))


def _zip_path(private_dir: Path, digest: str) -> Path:
    return private_dir / "raw" / "fit" / digest[:2] / f"{digest}.zip"


def store_fit_zip(private_dir: Path, payload: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(payload).hexdigest()
    path = _zip_path(private_dir, digest)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    for directory in (path.parent, path.parent.parent, path.parent.parent.parent):
        directory.chmod(0o700)
    if not path.exists():
        fd, temporary = tempfile.mkstemp(prefix="fit-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            Path(temporary).unlink(missing_ok=True)
    if path.stat().st_mode & 0o077 or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise FitIngestError("fit_raw_hash_mismatch")
    return digest, str(path.relative_to(private_dir))


def _raw_object(session: Session, digest: str, relative: str, size: int) -> RawObject:
    obj = session.scalar(select(RawObject).where(RawObject.sha256 == digest))
    if obj is None:
        obj = RawObject(sha256=digest, relative_path=relative, byte_size=size, media_type="application/zip")
        session.add(obj)
        session.flush()
    return obj


def _set_error(
    activity: Activity,
    fit: FitFile | None,
    code: str,
    now: datetime,
    raw: RawObject | None = None,
    zip_sha: str | None = None,
    extracted_sha: str | None = None,
) -> str:
    if fit is not None:
        fit.last_attempt_at = now
        fit.last_error = code
        if fit.decoded_at is None:
            fit.decode_error = code
            if raw is not None and zip_sha is not None:
                fit.raw_object_id = raw.id
                fit.zip_sha256 = zip_sha
            fit.fit_sha256 = extracted_sha
    if fit is None or fit.decoded_at is None:
        activity.fit_status = "unavailable" if code == "fit_http_404" else "decode_error"
    return activity.fit_status


def _locked_rows(session: Session, activity_id: uuid.UUID) -> tuple[Activity, FitFile | None]:
    global_write_lock(session)
    activity = session.get(Activity, activity_id, with_for_update=True, populate_existing=True)
    if activity is None:
        raise FitIngestError("activity_not_found")
    fit = session.scalar(
        select(FitFile)
        .where(FitFile.activity_id == activity_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return activity, fit


def ingest_activity_fit(session: Session, source: FitSource, private_dir: Path, activity: Activity) -> str:
    """Ingest one run without committing; the caller owns the transaction."""
    now = datetime.now(UTC)
    try:
        remote_id = _remote_id(session, activity)
    except FitIngestError as exc:
        locked, fit = _locked_rows(session, activity.id)
        return _set_error(locked, fit, exc.code, now)
    try:
        zip_bytes = source.download_activity(remote_id)
    except Exception as exc:
        log.error("download_activity failed activity_id=%s %s", activity.id, exception_summary(exc))
        code = "fit_http_404" if getattr(exc, "status_code", None) == 404 else "fit_download_error"
        locked, fit = _locked_rows(session, activity.id)
        return _set_error(locked, fit, code, now)
    if not isinstance(zip_bytes, bytes):
        locked, fit = _locked_rows(session, activity.id)
        return _set_error(locked, fit, "invalid_fit_download_shape", now)
    return ingest_activity_fit_bytes(session, private_dir, activity, zip_bytes)


def ingest_activity_fit_bytes(session: Session, private_dir: Path, activity: Activity, zip_bytes: bytes) -> str:
    """Persist and decode the same FIT ZIP that was previewed before confirmation."""
    now = datetime.now(UTC)
    digest, relative = store_fit_zip(private_dir, zip_bytes)
    locked, fit = _locked_rows(session, activity.id)
    raw = _raw_object(session, digest, relative, len(zip_bytes))
    if fit is None:
        fit = FitFile(raw_object_id=raw.id, activity_id=activity.id, zip_sha256=digest, message_inventory={}, device={})
        session.add(fit)
        session.flush()
    try:
        fit_bytes = extract_fit(zip_bytes)
    except FitDecodeError as exc:
        return _set_error(locked, fit, exc.code, now, raw, digest)
    extracted_sha = hashlib.sha256(fit_bytes).hexdigest()
    if fit.fit_sha256 == extracted_sha and fit.decoded_at is not None:
        fit.last_attempt_at = now
        fit.last_error = None
        return locked.fit_status
    status, _ = _apply_fit(session, locked, fit, raw, digest, fit_bytes, extracted_sha, now)
    return status


def _apply_fit(
    session: Session,
    locked: Activity,
    fit: FitFile,
    raw: RawObject,
    digest: str,
    fit_bytes: bytes,
    extracted_sha: str,
    now: datetime,
) -> tuple[str, str | None]:
    try:
        decoded = decode_fit(fit_bytes)
    except FitDecodeError as exc:
        return _set_error(locked, fit, exc.code, now, raw, digest, extracted_sha), exc.code
    if decoded.session.start_at != locked.start_at:
        return _set_error(locked, fit, "FIT_START_MISMATCH", now, raw, digest, extracted_sha), "FIT_START_MISMATCH"
    if decoded.session.sport not in RUN_SPORTS:
        return _set_error(locked, fit, "fit_not_run", now, raw, digest, extracted_sha), "fit_not_run"
    session.execute(delete(ActivityLap).where(ActivityLap.activity_id == locked.id))
    session.execute(delete(ActivityWorkoutStep).where(ActivityWorkoutStep.activity_id == locked.id))
    session.execute(delete(ActivityStream).where(ActivityStream.activity_id == locked.id))
    session.add_all(
        [
            ActivityLap(
                activity_id=locked.id,
                lap_index=lap.lap_index,
                start_at=lap.start_at,
                timer_s=lap.timer_s,
                elapsed_s=lap.elapsed_s,
                distance_m=lap.distance_m,
                avg_speed_mps=lap.avg_speed_mps,
                avg_hr_bpm=lap.avg_hr_bpm,
                max_hr_bpm=lap.max_hr_bpm,
                lap_trigger=lap.lap_trigger,
                wkt_step_index=lap.wkt_step_index,
                intensity=lap.intensity,
                end_at=lap.end_at,
            )
            for lap in decoded.laps
        ]
    )
    session.add_all(
        [
            ActivityWorkoutStep(
                activity_id=locked.id,
                message_index=step.message_index,
                step_name=step.step_name,
                intensity=step.intensity,
                duration_type=step.duration_type,
                duration_value=step.duration_value,
                target_type=step.target_type,
                target_low=step.target_low,
                target_high=step.target_high,
                repeat_from=step.repeat_from,
                repeat_count=step.repeat_count,
            )
            for step in decoded.steps
        ]
    )
    stream = decoded.stream
    session.add(
        ActivityStream(
            activity_id=locked.id,
            t_s=list(stream.t_s),
            hr_bpm=list(stream.hr_bpm),
            speed_mps=list(stream.speed_mps),
            distance_m=list(stream.distance_m),
            altitude_m=list(stream.altitude_m),
            cadence=list(stream.cadence),
            timer_on=[list(pair) for pair in stream.timer_on],
            sample_count=stream.sample_count,
            max_gap_s=stream.max_gap_s,
            quality_flags=list(stream.quality_flags),
        )
    )
    end_at = (
        locked.start_at + timedelta(seconds=decoded.session.elapsed_s)
        if decoded.session.elapsed_s is not None
        else None
    )
    locked.timer_s = decoded.session.timer_s
    locked.end_at = end_at
    locked.workout_rpe = decoded.session.workout_rpe
    locked.workout_feel = decoded.session.workout_feel
    locked.fit_status = "decoded"
    locked.fit_file_id = fit.id
    provenance = dict(locked.field_provenance or {})
    for field in ("timer_s", "end_at", "workout_rpe", "workout_feel"):
        provenance[field] = {"source_kind": "garmin_fit", "fit_sha256": extracted_sha}
    locked.field_provenance = provenance
    fit.raw_object_id = raw.id
    fit.zip_sha256 = digest
    fit.fit_sha256 = extracted_sha
    fit.profile_version = decoded.profile_version
    fit.sdk_version = decoded.sdk_version
    fit.decoded_at = now
    fit.decoder_version = DECODER_VERSION
    fit.decode_error = None
    fit.last_attempt_at = now
    fit.last_error = None
    fit.message_inventory = decoded.message_inventory
    fit.device = decoded.device
    rpe = session.scalar(
        select(SessionRpe).where(SessionRpe.activity_id == locked.id, SessionRpe.source == "garmin_fit")
    )
    if decoded.session.workout_rpe is None or end_at is None:
        if rpe is not None:
            session.delete(rpe)
    elif rpe is None:
        session.add(
            SessionRpe(activity_id=locked.id, rpe=decoded.session.workout_rpe, source="garmin_fit", collected_at=end_at)
        )
    else:
        rpe.rpe = decoded.session.workout_rpe
        rpe.collected_at = end_at
    locked.canonical_revision += 1
    bump_data_revision(session)
    session.flush()
    return "decoded", None


def reprocess_fit(session: Session, private_dir: Path, activity: Activity) -> tuple[str, str | None]:
    """Decode one retained FIT archive without changing its source or committing."""
    try:
        locked, fit = _locked_rows(session, activity.id)
    except FitIngestError as exc:
        if exc.code != "activity_not_found":
            raise
        return "unchanged", None
    if (
        locked.fit_status != "decoded"
        or fit is None
        or fit.raw_object_id is None
        or (fit.decoder_version is not None and fit.decoder_version >= DECODER_VERSION)
    ):
        return "unchanged", None

    now = datetime.now(UTC)
    raw = session.get(RawObject, fit.raw_object_id)
    try:
        if raw is None:
            raise FitIngestError("raw_missing")
        root = private_dir.resolve()
        path = (root / raw.relative_path).resolve()
        if not path.is_relative_to(root):
            raise FitIngestError("fit_raw_hash_mismatch")
        zip_bytes = path.read_bytes()
        digest = hashlib.sha256(zip_bytes).hexdigest()
        if digest != raw.sha256 or digest != fit.zip_sha256:
            raise FitIngestError("fit_raw_hash_mismatch")
        fit_bytes = extract_fit(zip_bytes)
    except (FileNotFoundError, NotADirectoryError):
        _set_error(locked, fit, "raw_missing", now)
        return "error", "raw_missing"
    except (FitIngestError, FitDecodeError) as exc:
        _set_error(locked, fit, exc.code, now)
        return "error", exc.code
    extracted_sha = hashlib.sha256(fit_bytes).hexdigest()
    _, code = _apply_fit(session, locked, fit, raw, digest, fit_bytes, extracted_sha, now)
    return ("error", code) if code is not None else ("reprocessed", None)


class ReprocessSummary(TypedDict):
    selected: int
    reprocessed: int
    unchanged: int
    errors: dict[str, int]


def reprocess_fits(session: Session, private_dir: Path, since: date, activity_id: uuid.UUID | None) -> ReprocessSummary:
    query = (
        select(Activity)
        .join(FitFile, FitFile.activity_id == Activity.id)
        .where(
            Activity.fit_status == "decoded",
            or_(FitFile.decoder_version.is_(None), FitFile.decoder_version < DECODER_VERSION),
        )
    )
    if activity_id is None:
        start = datetime.combine(since, datetime.min.time(), athlete_tz(session))
        query = query.where(Activity.start_at >= start)
    else:
        query = query.where(Activity.id == activity_id)
    activities = session.scalars(query.order_by(Activity.start_at, Activity.id)).all()
    summary: ReprocessSummary = {"selected": len(activities), "reprocessed": 0, "unchanged": 0, "errors": {}}
    for activity in activities:
        outcome, code = reprocess_fit(session, private_dir, activity)
        if code is not None:
            summary["errors"][code] = summary["errors"].get(code, 0) + 1
        elif outcome == "reprocessed":
            summary["reprocessed"] += 1
        else:
            summary["unchanged"] += 1
    return summary


def backfill_fit(session_factory, source: FitSource, private_dir: Path, since: date) -> dict[str, int]:
    counts = {"attempted": 0, "decoded": 0, "unavailable": 0, "failed": 0}
    with session_factory() as session:
        ids = list(
            session.scalars(
                select(Activity.id)
                .where(
                    Activity.local_date >= since,
                    Activity.sport.in_(tuple(RUN_SPORTS)),
                    Activity.fit_status.in_(("not_fetched", "decode_error")),
                )
                .order_by(Activity.start_at, Activity.id)
            )
        )
    for activity_id in ids:
        counts["attempted"] += 1
        with session_factory() as session:
            try:
                activity = session.get(Activity, activity_id)
                if activity is None:
                    counts["failed"] += 1
                    continue
                outcome = ingest_activity_fit(session, source, private_dir, activity)
                session.commit()
            except Exception as exc:
                log.error("backfill_fit failed activity_id=%s %s", activity_id, exception_summary(exc))
                session.rollback()
                outcome = "failed"
        if outcome in counts:
            counts[outcome] += 1
        else:
            counts["failed"] += 1
    return counts
