"""Synthetic Strong import behavior against migrated PostgreSQL test DB only."""

from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import ManualSession, SourceRecord
from app.services.strength_history import recent_strong_context, strong_history, strong_yearly_summary
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
            recent = recent_strong_context(session, date(2026, 11, 10))
            assert recent["start_date"] == "2025-05-10"
            assert recent["session_count"] == 2
            assert recent["unknown_duration_count"] == 1
            assert recent["known_duration_s"] == 2700
            assert strong_history(session, date(2025, 1, 1), date(2025, 12, 31))["session_count"] == 2

            session.add(ManualSession(date=date(2026, 11, 9), kind="strength", duration_s=1800))
            session.flush()
            overlapped = recent_strong_context(session, date(2026, 11, 10))
            assert overlapped["session_count"] == 1
            assert overlapped["ambiguous_overlap_count"] == 1
            assert overlapped["ambiguous_overlap_dates"] == ["2026-11-09"]

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
            assert recent_strong_context(session, date(2026, 11, 10))["session_count"] == 0
            yearly = strong_yearly_summary(session)
            assert yearly["weight_unit"] == "unknown"
            assert yearly["weight_comparisons_supported"] is False
        finally:
            session.rollback()
