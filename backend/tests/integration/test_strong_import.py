"""Synthetic Strong import behavior against migrated PostgreSQL test DB only."""

from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.metrics import srpe
from app.models import ManualSession, SourceRecord
from app.services.strong_import import import_strong_csv
from app.strong_models import StrongWorkoutRow

HEADER = "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"


def _row(stamp: str, duration: str, weight: str = "45.0") -> str:
    return f"{stamp},Synthetic Workout,{duration},Dumbbell Press,1,{weight},8,0,0,\n"


def test_strong_import_replay_revision_conflict_overlap_and_window(tmp_path):
    assert settings.app_mode == "test"
    assert (settings.database_url.rsplit("/", 1)[-1]).endswith("_test")
    csv_path = tmp_path / "synthetic.csv"
    original = (HEADER + _row("2025-05-09 12:00:00", "30m") +
                _row("2025-05-10 12:00:00", "120h 41m") +
                _row("2026-11-09 12:00:00", "45m")).encode()
    csv_path.write_bytes(original)
    with SessionLocal() as session:
        try:
            preview = import_strong_csv(session, tmp_path, csv_path)
            assert preview["new"] == 3
            assert session.scalar(select(func.count()).select_from(StrongWorkoutRow)) == 0
            assert not (tmp_path / "raw").exists()
            first = import_strong_csv(session, tmp_path, csv_path, apply=True)
            assert first["added"] == 3
            assert first["status"] == "complete"
            digest = hashlib.sha256(original).hexdigest()
            assert (tmp_path / "raw" / "strong" / f"{digest}.csv").read_bytes() == original
            assert session.scalar(select(func.count()).select_from(StrongWorkoutRow)) == 3
            assert session.scalar(select(func.count()).select_from(SourceRecord).where(
                SourceRecord.source_kind == "strong_csv")) == 3

            replay = import_strong_csv(session, tmp_path, csv_path, apply=True)
            assert replay["added"] == 0 and replay["unchanged"] == 3
            assert session.scalar(select(func.count()).select_from(SourceRecord).where(
                SourceRecord.source_kind == "strong_csv")) == 3
            session.add(ManualSession(date=date(2026, 11, 9), kind="strength", duration_s=1800))
            session.flush()
            strength = next(row for row in srpe.compute(session, "w7:2026-11-10")
                            if row.subject_key.endswith(":strength"))
            assert "STRENGTH_SOURCE_OVERLAP" in strength.quality_flags

            csv_path.write_text(HEADER + _row("2025-05-09 12:00:00", "30m") +
                                _row("2025-05-10 12:00:00", "120h 41m", "47.5") +
                                _row("2026-11-09 12:00:00", "45m"))
            changed = import_strong_csv(session, tmp_path, csv_path, apply=True)
            assert changed["changed_revisions"] == 1
            assert changed["revision_conflicts_new"] == 1
            canonical = session.scalar(select(StrongWorkoutRow).where(StrongWorkoutRow.local_date == date(2025, 5, 10)))
            assert canonical.sets[0]["Weight"] == "45.0"
            assert canonical.resolution_state == "revision_conflict"
            assert session.scalar(select(func.count()).select_from(SourceRecord).where(
                SourceRecord.source_kind == "strong_csv")) == 4
        finally:
            session.rollback()
