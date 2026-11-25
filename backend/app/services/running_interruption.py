"""Read-only preview of an interruption against the accepted calendar."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from enum import Enum
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.domain.athlete_facts import RunningRestriction, clinical_restriction, running_restriction
from app.domain.running_interruption import RunningInterruption, running_interruption
from app.domain.running_limits import restriction_conflict
from app.read.activities import eligible_runs
from app.read.calendar import latest_revisions
from app.services.profile import current_profile
from app.travel_models import Trip

_PREVIEW_DAYS = 28
_AFFECTED_LIMIT = 8
_EASY_RETURN = RunningRestriction(starts_on=date.min, no_quality=True, source="Return preview")


class _Blocked(Enum):
    DOSE = "Review the session and choose an easy return option for {day}."
    TRAVEL = "Review the reduced or unavailable travel day on {day} before keeping that run."
    UNKNOWN_TRAVEL = "Confirm running access and availability during the trip on {day} before keeping that run."
    RESTRICTION = "Review the run on {day} against the recorded running limits."
    MISSING_DOSE = "Confirm the planned duration, distance, or workout steps before keeping the run on {day}."


def _preview_end(start: date) -> date:
    return date.fromordinal(min(start.toordinal() + _PREVIEW_DAYS - 1, date.max.toordinal()))


def _row_view(row: CalendarSessionRevision) -> dict[str, Any]:
    return {
        "session_uid": row.session_uid,
        "local_date": row.local_date,
        "intent": row.intent,
        "recipe_id": row.recipe_id,
        "planned_duration_s": row.planned_duration_s,
        "planned_distance_m": row.planned_distance_m,
    }


def _trip_blocker(trip: Trip, day: date) -> _Blocked | None:
    if day < trip.start_date or (trip.end_date is not None and day > trip.end_date):
        return None
    day_status = next((item["availability"] for item in trip.day_availability if item["date"] == day.isoformat()), None)
    if trip.running_access in {"limited", "none"} or day_status in {"reduced", "unavailable"}:
        return _Blocked.TRAVEL
    if day_status != "normal":
        return _Blocked.UNKNOWN_TRAVEL
    return None


def _blocked(row: CalendarSessionRevision, limit: RunningRestriction | None, trips: Sequence[Trip]) -> _Blocked | None:
    prescription = {
        **_row_view(row),
        "kind": row.kind,
        "brief": row.brief,
        "structure": row.structure,
        "custom": row.custom,
        "placeholder": row.placeholder,
    }
    if restriction_conflict(limit, prescription):
        return _Blocked.RESTRICTION
    travel = {_trip_blocker(trip, row.local_date) for trip in trips}
    if _Blocked.TRAVEL in travel:
        return _Blocked.TRAVEL
    if _Blocked.UNKNOWN_TRAVEL in travel:
        return _Blocked.UNKNOWN_TRAVEL
    if row.recipe_id != "REC001" or restriction_conflict(_EASY_RETURN, prescription):
        return _Blocked.DOSE
    if not ((row.planned_duration_s or 0) > 0 or (row.planned_distance_m or 0) > 0 or row.structure):
        return _Blocked.MISSING_DOSE
    return None


def _first_run(
    rows: Sequence[CalendarSessionRevision],
    episode: RunningInterruption,
    today: date,
    facts: dict[str, Any],
    trips: Sequence[Trip],
) -> tuple[dict[str, Any] | None, str | None]:
    if episode.return_on is None:
        return (
            None,
            "Confirm the first available day before reviewing a return run. The review date keeps the pause in place.",
        )
    if clinical_restriction(facts):
        return None, "Review the existing running restriction before choosing a return run."
    start = max(today, episode.return_on)
    end = _preview_end(start)
    limit = running_restriction(facts)
    blockers: dict[_Blocked, date] = {}
    for row in rows:
        if start <= row.local_date <= end:
            reason = _blocked(row, limit, trips)
            if reason is None:
                return _row_view(row), _blocker_notes(blockers)
            blockers.setdefault(reason, row.local_date)
    return None, _blocker_notes(
        blockers
    ) or "There are no uncompleted, unlocked accepted runs to review in the next four weeks."


def _blocker_notes(blockers: dict[_Blocked, date]) -> str | None:
    return " ".join(reason.value.format(day=day.isoformat()) for reason, day in blockers.items()) or None


def _recorded_return(session: Session, episode: RunningInterruption, today: date) -> dict[str, Any] | None:
    if episode.return_on is None or today < episode.return_on:
        return None
    end = today + timedelta(days=1) if today.toordinal() < date.max.toordinal() - 1 else None
    matches = eligible_runs(session, episode.return_on, end)
    if not matches:
        return None
    run = matches[0]
    return {"activity_id": run.activity.id, "local_date": run.local_date}


def _bounded_affected(
    rows: Sequence[CalendarSessionRevision], episode: RunningInterruption, today: date
) -> tuple[list[dict[str, Any]], int]:
    affected = [row for row in rows if episode.unavailable_on(row.local_date)]
    upcoming = [row for row in affected if row.local_date >= today][:_AFFECTED_LIMIT]
    remaining = _AFFECTED_LIMIT - len(upcoming)
    past = [row for row in affected if row.local_date < today]
    visible = (past[-remaining:] if remaining else []) + upcoming
    return [_row_view(row) for row in visible], len(affected) - len(visible)


def _reviewable_runs(session: Session, start: date, end: date) -> list[CalendarSessionRevision]:
    rows = [
        row
        for row in latest_revisions(session).values()
        if not row.deleted and not row.locked and row.kind == "run" and start <= row.local_date <= end
    ]
    if not rows:
        return []
    protected = set(
        session.scalars(
            select(SessionCompletion.session_uid).where(
                SessionCompletion.session_uid.in_([row.session_uid for row in rows]),
                or_(
                    SessionCompletion.status != "unknown",
                    SessionCompletion.activity_id.is_not(None),
                    SessionCompletion.strong_workout_id.is_not(None),
                    SessionCompletion.manual_session_id.is_not(None),
                ),
            )
        )
    )
    return sorted(
        (row for row in rows if row.session_uid not in protected),
        key=lambda row: (row.local_date, row.slot, row.session_uid),
    )


def return_view(session: Session, today: date) -> dict[str, Any]:
    profile = current_profile(session)
    facts = (profile.facts or {}) if profile else {}
    episode = running_interruption(facts)
    view = {
        "today": today,
        "profile_version": profile.version if profile else 0,
        "interruption": episode.model_dump() if episode else None,
        "phase": episode.phase_on(today) if episode else None,
        "affected_runs": [],
        "affected_runs_omitted": 0,
        "first_run": None,
        "recorded_return": None,
        "review_reason": None,
    }
    if episode is None:
        return view
    start = max(today, episode.return_on or episode.starts_on)
    end = _preview_end(start)
    rows = _reviewable_runs(session, episode.starts_on, end)
    affected, omitted = _bounded_affected(rows, episode, today)
    view.update(affected_runs=affected, affected_runs_omitted=omitted)
    if recorded := _recorded_return(session, episode, today):
        view.update(
            recorded_return=recorded,
            review_reason="Review your response to the recorded return run and end the interruption when appropriate.",
        )
        return view
    trips = (
        list(
            session.scalars(
                select(Trip).where(
                    Trip.status == "confirmed",
                    Trip.start_date <= end,
                    or_(Trip.end_date.is_(None), Trip.end_date >= start),
                )
            )
        )
        if episode.return_on is not None
        else []
    )
    first_run, review_reason = _first_run(rows, episode, today, facts, trips)
    view.update(first_run=first_run, review_reason=review_reason)
    return view
