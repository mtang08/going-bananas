"""Descriptive Strong history and bounded coaching context selection."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Activity, ImportBatch, ManualSession
from app.strong_models import StrongWorkoutRow


def subtract_calendar_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 - months
    year, month_zero = divmod(index, 12)
    month = month_zero + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def strong_history(session: Session, start: date, end: date) -> dict[str, Any]:
    """Inclusive local-date window; unresolved source revisions are excluded.

    This is Strong-only. Consumers must reconcile same-day Garmin/manual strength
    candidates before combining session counts across sources.
    """
    if start > end or (end - start).days > 3660:
        raise ValueError("invalid_date_window")
    rows = session.scalars(select(StrongWorkoutRow).where(
        StrongWorkoutRow.local_date >= start, StrongWorkoutRow.local_date <= end,
        StrongWorkoutRow.resolution_state == "resolved").order_by(StrongWorkoutRow.local_date,
                                                                    StrongWorkoutRow.local_start)).all()
    manual_dates = set(session.scalars(select(ManualSession.date).where(
        ManualSession.kind == "strength", ManualSession.date >= start, ManualSession.date <= end)).all())
    garmin_dates = set(session.scalars(select(Activity.local_date).where(
        Activity.sport == "strength", Activity.local_date >= start, Activity.local_date <= end,
        Activity.resolution_state == "resolved")).all())
    overlap_dates = manual_dates | garmin_dates
    counted = [row for row in rows if row.local_date not in overlap_dates]
    ambiguous = [row for row in rows if row.local_date in overlap_dates]
    all_dates = session.scalars(select(StrongWorkoutRow.local_date).order_by(StrongWorkoutRow.local_date.desc()).limit(1)).all()
    latest_batch = session.scalar(select(ImportBatch).where(ImportBatch.source_kind == "strong_csv")
                                  .order_by(ImportBatch.finished_at.desc()).limit(1))
    return {
        "source": "strong_csv", "start_date": start.isoformat(), "end_date": end.isoformat(),
        "session_count": len(counted),
        "known_duration_s": sum(row.duration_s for row in counted if row.duration_s is not None),
        "unknown_duration_count": sum(row.duration_s is None for row in counted),
        "dates": [row.local_date.isoformat() for row in counted],
        "latest_imported_workout_date": all_dates[0].isoformat() if all_dates else None,
        "imported_at": latest_batch.finished_at.isoformat() if latest_batch and latest_batch.finished_at else None,
        "coverage": "export_snapshot_observed_only",
        "ambiguous_overlap_count": len(ambiguous),
        "ambiguous_overlap_dates": sorted({row.local_date.isoformat() for row in ambiguous}),
        "sessions": [{"id": str(row.id), "date": row.local_date.isoformat(),
                      "local_start": row.local_start, "duration_s": row.duration_s,
                      "exercise_count": len({item["Exercise Name"] for item in row.sets})} for row in counted],
        "cross_source_reconciliation": "same_day_candidates_withheld",
        "weight_unit": "unknown", "weight_comparisons_supported": False,
    }


def recent_strong_context(session: Session, as_of: date) -> dict[str, Any]:
    """Only the past 18 calendar months enter running coaching context."""
    return strong_history(session, subtract_calendar_months(as_of, 18), as_of)


def strong_workout_detail(session: Session, workout_id: UUID) -> dict[str, Any] | None:
    """Source-faithful drilldown; no load, PR, or tonnage calculation."""
    row = session.get(StrongWorkoutRow, workout_id)
    if row is None:
        return None
    return {"id": str(row.id), "date": row.local_date.isoformat(), "local_start": row.local_start,
            "workout_name": row.workout_name, "duration_s": row.duration_s, "sets": row.sets,
            "resolution_state": row.resolution_state, "weight_unit": "unknown",
            "distance_unit": "unknown", "weight_comparisons_supported": False}


def strong_yearly_summary(session: Session) -> dict[str, Any]:
    """All-year session counts; no load, PR, or cross-regime weight totals."""
    rows = session.scalars(select(StrongWorkoutRow).where(
        StrongWorkoutRow.resolution_state == "resolved").order_by(StrongWorkoutRow.local_date)).all()
    if not rows:
        return {"years": [], "coverage": "export_snapshot_observed_only", "weight_unit": "unknown"}
    start, end = rows[0].local_date, rows[-1].local_date
    manual_dates = set(session.scalars(select(ManualSession.date).where(
        ManualSession.kind == "strength", ManualSession.date >= start, ManualSession.date <= end)).all())
    garmin_dates = set(session.scalars(select(Activity.local_date).where(
        Activity.sport == "strength", Activity.local_date >= start, Activity.local_date <= end,
        Activity.resolution_state == "resolved")).all())
    overlaps = manual_dates | garmin_dates
    years: dict[int, dict[str, Any]] = {}
    for row in rows:
        item = years.setdefault(row.local_date.year, {"year": row.local_date.year, "session_count": 0,
                                                       "known_duration_s": 0, "unknown_duration_count": 0,
                                                       "ambiguous_overlap_count": 0})
        if row.local_date in overlaps:
            item["ambiguous_overlap_count"] += 1
            continue
        item["session_count"] += 1
        if row.duration_s is None:
            item["unknown_duration_count"] += 1
        else:
            item["known_duration_s"] += row.duration_s
    return {"years": list(years.values()), "coverage": "export_snapshot_observed_only",
            "weight_unit": "unknown", "weight_comparisons_supported": False,
            "missing_recordings_do_not_mean_missed_lifting": True}
