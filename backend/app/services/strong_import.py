"""Local Strong CSV preflight and transactional import.

The caller owns the database transaction. Preview never writes. Apply writes an
immutable private copy before creating DB references. No real import runs here.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.adapters.strong import ADAPTER_VERSION, StrongCSVError, scan_strong_csv
from app.config import settings
from app.db import SessionLocal, bump_data_revision
from app.models import ImportBatch, RawObject, SourceAccount, SourceRecord
from app.services.sync import ADVISORY_LOCK, GLOBAL_WRITE_LOCK
from app.strong_models import StrongWorkoutRow


def _store_csv(path: Path, private_dir: Path, digest: str, size: int) -> str:
    folder = private_dir / "raw" / "strong"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder.chmod(0o700)
    target = folder / f"{digest}.csv"
    if not target.exists():
        fd, temporary = tempfile.mkstemp(prefix="strong-", dir=folder)
        try:
            with os.fdopen(fd, "wb") as output, path.open("rb") as source:
                shutil.copyfileobj(source, output)
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
        raise StrongCSVError("csv_copy_mismatch")
    with target.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise StrongCSVError("csv_copy_mismatch")
    return str(target.relative_to(private_dir))


def import_strong_csv(session: Session, private_dir: Path, csv_path: Path, *, apply: bool = False) -> dict[str, object]:
    workouts, digest, size = scan_strong_csv(csv_path)
    if apply:
        session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': GLOBAL_WRITE_LOCK})
    accounts = session.scalars(select(SourceAccount).where(SourceAccount.provider == "strong")).all()
    if len(accounts) > 1 or (accounts and accounts[0].account_scope != "local-csv"):
        raise StrongCSVError("mixed_source_account")
    account = accounts[0] if accounts else None
    existing = {}
    if account:
        existing = {row.source_identity: row for row in session.scalars(
            select(StrongWorkoutRow).where(StrongWorkoutRow.source_account_id == account.id)).all()}
    new = sum(item.source_identity not in existing for item in workouts)
    unchanged = sum(item.source_identity in existing and existing[item.source_identity].payload_hash == item.payload_hash
                    for item in workouts)
    changed = len(workouts) - new - unchanged
    summary: dict[str, object] = {
        "status": "preflight_ok", "workouts": len(workouts), "set_rows": sum(x.row_count for x in workouts),
        "first_date": min(x.local_date for x in workouts), "last_date": max(x.local_date for x in workouts),
        "new": new, "unchanged": unchanged, "changed_revisions": changed,
        "unknowns": ["source_timezone", "weight_unit", "dumbbell_weight_convention_change_date"],
    }
    if not apply:
        return summary
    relative = _store_csv(csv_path, private_dir, digest, size)
    raw = session.scalar(select(RawObject).where(RawObject.sha256 == digest))
    if raw is None:
        raw = RawObject(sha256=digest, relative_path=relative, byte_size=size, media_type="text/csv")
        session.add(raw)
        session.flush()
    if account is None:
        account = SourceAccount(provider="strong", account_scope="local-csv")
        session.add(account)
        session.flush()
    batch = ImportBatch(source_kind="strong_csv", status="running", adapter_version=ADAPTER_VERSION)
    session.add(batch)
    session.flush()
    added = conflicts = 0
    for item in workouts:
        prior = existing.get(item.source_identity)
        source = session.scalar(select(SourceRecord).where(
            SourceRecord.source_account_id == account.id,
            SourceRecord.source_identity == item.source_identity,
            SourceRecord.payload_hash == item.payload_hash))
        if source is None:
            source = SourceRecord(source_account_id=account.id, import_batch_id=batch.id,
                                  raw_object_id=raw.id, source_identity=item.source_identity,
                                  payload_hash=item.payload_hash, fetched_at=datetime.now(UTC),
                                  parser_version=ADAPTER_VERSION, source_kind="strong_csv",
                                  fields={"local_start": item.local_start, "row_count": item.row_count,
                                          "timestamp_semantics": "source_local_timezone_unknown",
                                          "weight_unit": "unknown"})
            session.add(source)
            session.flush()
        if prior is None:
            session.add(StrongWorkoutRow(source_account_id=account.id, source_identity=item.source_identity,
                                         source_record_id=source.id, raw_object_id=raw.id, payload_hash=item.payload_hash,
                                         local_date=date.fromisoformat(item.local_date), local_start=item.local_start,
                                         workout_name=item.workout_name, duration_s=item.duration_s, sets=item.sets,
                                         row_count=item.row_count))
            added += 1
        elif prior.payload_hash != item.payload_hash:
            # A changed export has no reliable source modification time. Keep
            # canonical values; require explicit review before using either.
            if prior.resolution_state != "revision_conflict":
                prior.resolution_state = "revision_conflict"
                conflicts += 1
    if added or conflicts:
        bump_data_revision(session)
    batch.status = "partial" if changed else "complete"
    batch.finished_at = datetime.now(UTC)
    batch.counters = {"workouts": len(workouts), "set_rows": summary["set_rows"],
                      "new": added, "unchanged": unchanged, "changed_revisions": changed,
                      "revision_conflicts_new": conflicts, "csv_sha256": digest}
    summary.update(status=batch.status, added=added, revision_conflicts_new=conflicts)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or import a local Strong CSV")
    parser.add_argument("csv", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        with SessionLocal() as session:
            if args.apply:
                session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': ADVISORY_LOCK})
            result = import_strong_csv(session, settings.private_dir, args.csv, apply=args.apply)
            if args.apply:
                session.commit()
    except (StrongCSVError, OSError) as exc:
        # Never show private paths, rows, or exception text.
        code = str(exc) if isinstance(exc, StrongCSVError) else "csv_io_error"
        print({"status": "error", "code": code})
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
