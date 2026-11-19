"""Calendar head and latest-revision reads."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision
from app.models import AppState


def head_version(session: Session, *, populate_existing: bool = False) -> int:
    state = session.get(AppState, 1, populate_existing=populate_existing)
    return state.calendar_head_version if state else 0


def latest_revisions(session: Session, version: int | None = None) -> dict[uuid.UUID, CalendarSessionRevision]:
    """Newest revision of every session at `version` (default: head). Deleted revisions are included."""
    at = head_version(session) if version is None else version
    if at <= 0:
        return {}
    rows = session.scalars(
        select(CalendarSessionRevision)
        .where(CalendarSessionRevision.calendar_version_number <= at)
        .order_by(
            CalendarSessionRevision.session_uid,
            desc(CalendarSessionRevision.calendar_version_number),
            desc(CalendarSessionRevision.revision),
        )
        .distinct(CalendarSessionRevision.session_uid)
    ).all()
    return {row.session_uid: row for row in rows}


def latest_revision(
    session: Session, session_uid: uuid.UUID, version: int | None = None
) -> CalendarSessionRevision | None:
    """Newest revision of one session at `version` (default: head), deleted or not; None if it never existed."""
    at = head_version(session) if version is None else version
    if at <= 0:
        return None
    return session.scalar(
        select(CalendarSessionRevision)
        .where(
            CalendarSessionRevision.session_uid == session_uid, CalendarSessionRevision.calendar_version_number <= at
        )
        .order_by(desc(CalendarSessionRevision.calendar_version_number), desc(CalendarSessionRevision.revision))
        .limit(1)
    )


def recent_revision_dates(session: Session, session_uid: uuid.UUID) -> set[date]:
    """The days of a session's two latest revisions: where it is now and where it was before this change."""
    return set(
        session.scalars(
            select(CalendarSessionRevision.local_date)
            .where(CalendarSessionRevision.session_uid == session_uid)
            .order_by(CalendarSessionRevision.calendar_version_number.desc(), CalendarSessionRevision.revision.desc())
            .limit(2)
        )
    )
