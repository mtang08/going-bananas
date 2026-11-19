"""Coverage interval query helper shared by services and routes."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CoverageInterval


def coverage(session: Session, start: date, end: date) -> list[dict]:
    rows = session.scalars(
        select(CoverageInterval)
        .where(CoverageInterval.end_date >= start, CoverageInterval.start_date <= end)
        .order_by(CoverageInterval.dataset, CoverageInterval.start_date)
    ).all()
    return [
        {
            "dataset": x.dataset,
            "start_date": x.start_date,
            "end_date": x.end_date,
            "status": x.status,
            "fully_enumerated": x.fully_enumerated,
            "completed_at": x.completed_at,
            "reason": x.reason,
        }
        for x in rows
    ]
