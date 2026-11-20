"""Event rank semantics: the goal race is the upcoming event of effective rank 1."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.planning_models import Event

UPCOMING_STATUSES = ("planned", "registered")
TargetStatus = Literal["current", "changed", "unset", "none"]


def ranked_upcoming(events: list[Any], today: date) -> list[tuple[int, Any]]:
    """Upcoming events as (effective rank 1..n, event), by stored rank (nulls last), date, id."""
    upcoming = [e for e in events if e.status in UPCOMING_STATUSES and e.event_date >= today]
    upcoming.sort(key=lambda e: (e.rank is None, e.rank or 0, e.event_date, e.id))
    return list(enumerate(upcoming, start=1))


def renumber(session: Session, today: date) -> list[tuple[int, Event]]:
    """Store ranks 1..n on the upcoming events and clear every other rank. The caller commits.

    Does not bump `version`: renumbering must not invalidate other clients' expected versions.
    """
    session.flush()  # the app session has autoflush=False; include rows the caller just added
    events = list(session.scalars(select(Event)))
    ranked = ranked_upcoming(events, today)
    keep = {event.id for _, event in ranked}
    for rank, event in ranked:
        if event.rank != rank:
            event.rank = rank
    for event in events:
        if event.id not in keep and event.rank is not None:
            event.rank = None
    session.flush()
    return ranked


def target_status(block_target_id: uuid.UUID | None, top_id: uuid.UUID | None) -> TargetStatus:
    """How a block's target relates to the current goal race (`top_id`, None when no upcoming event)."""
    if block_target_id is not None:
        return "current" if block_target_id == top_id else "changed"
    return "unset" if top_id is not None else "none"


def goal_pace_s_per_km(distance_m: int | None, goal_time_s: int | None) -> int | None:
    if not distance_m or not goal_time_s:
        return None
    return int(goal_time_s * 1000 / distance_m + 0.5)
