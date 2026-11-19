"""Metric recomputation: select subjects with `scope_targets` and refresh them with `refresh_targets`.
The commit-time pipeline that also re-matches and updates prompts is
`app.services.derived.refresh_scopes`. Snapshot, CLI, and demo seed call
`ensure_windows`, `ensure_nights`, and `assess_completion` directly. Work outside a commit runs
inside `refreshing(session)`, which takes the global write lock and caches computed subjects.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.db import bump_data_revision, global_write_lock
from app.domain.local_time import date_in_zone
from app.metric_models import MetricResult as MetricResultRow
from app.metrics.contract import MetricResultData
from app.metrics.engine import (
    REGISTRY,
    current_result_filter,
    ensure_configs,
    metric_modules,
    ordered_registry,
    upsert_results,
)
from app.models import Activity
from app.read.calendar import head_version, latest_revisions, recent_revision_dates
from app.services.timezone import athlete_today, athlete_tz


def parse_scope(scope: str) -> tuple[str, Any]:
    """Split a refresh scope into `(kind, value)`, or raise `ValueError('invalid_scope')`.

    `activity:`, `checkin:`, `plan:` carry a UUID; `strength:strong:` and `strength:manual:` a UUID; `date:` and
    `since:` an ISO date; `recovery_dates:` comma-separated ISO dates. `timezone` and `revision` carry nothing.
    """
    kind, _, raw = scope.partition(":")
    try:
        if scope in ("timezone", "revision"):
            return scope, None
        if kind in ("activity", "checkin", "plan"):
            return kind, uuid.UUID(raw)
        if kind == "strength":
            prefix, _, raw_id = raw.partition(":")
            if prefix in ("strong", "manual"):
                return f"strength:{prefix}", uuid.UUID(raw_id)
        if kind in ("date", "since"):
            value = date.fromisoformat(raw)
            if value.isoformat() == raw:
                return kind, value
        if kind == "recovery_dates":
            parts = raw.split(",")
            values = tuple(date.fromisoformat(part) for part in parts)
            if all(value.isoformat() == part for value, part in zip(values, parts, strict=True)):
                return kind, values
    except ValueError:
        pass
    raise ValueError("invalid_scope")


# A stored hard_session_spacing window refreshes only when a changed date is within this distance of its as-of date.
SPACING_REACH_DAYS = 14


def clock(session: Session) -> datetime:
    return session.info.get("metrics_now") or datetime.now(UTC)


def local_today(session: Session) -> date:
    return athlete_today(session, clock(session))


@contextmanager
def refreshing(session: Session):
    depth = session.info.get("metrics_depth", 0)
    old_running = session.info.get("metrics_running", False)
    session.info["metrics_running"] = True
    session.info["metrics_depth"] = depth + 1
    try:
        if depth == 0:
            global_write_lock(session)
            session.info["metrics_computed"] = set()
            ensure_configs(session)
        yield
    finally:
        session.info["metrics_depth"] = depth
        session.info["metrics_running"] = old_running
        if depth == 0:
            session.info.pop("metrics_computed", None)
            session.info.pop("metrics_depth", None)


def compute_subjects(session: Session, metric_id: str, subject_keys: Sequence[str]) -> list[MetricResultData]:
    metric_modules()
    if metric_id not in REGISTRY:
        raise ValueError("unknown_metric")
    allowed = session.info.get("metrics_filter")
    if allowed is not None and metric_id not in allowed:
        return []
    registration = REGISTRY[metric_id]
    cache = session.info.get("metrics_computed", set())
    results = []
    for key in dict.fromkeys(subject_keys):
        if (metric_id, key) in cache:
            continue
        calculated = [replace(row, calculated_at=clock(session)) for row in registration.compute(session, key)]
        if not calculated:
            session.query(MetricResultRow).filter(
                MetricResultRow.metric_id == metric_id,
                MetricResultRow.method_version == registration.method_version,
                MetricResultRow.subject_key == key,
                MetricResultRow.is_current.is_(True),
            ).update({"is_current": False}, synchronize_session="fetch")
        upsert_results(session, calculated)
        cache.add((metric_id, key))
        results.extend(calculated)
    return results


def activities_between(session: Session, start: date, end: date) -> list[uuid.UUID]:
    zone = athlete_tz(session)
    rows = session.execute(
        select(Activity.id, Activity.start_at)
        .where(
            Activity.start_at >= datetime.combine(start - timedelta(days=1), datetime.min.time(), tzinfo=zone),
            Activity.start_at < datetime.combine(end + timedelta(days=2), datetime.min.time(), tzinfo=zone),
        )
        .order_by(Activity.start_at, Activity.id)
    ).all()
    return [uid for uid, stamp in rows if start <= date_in_zone(stamp, zone) <= end]


def refresh_runs(session: Session, activity_ids: Iterable[uuid.UUID]) -> list[MetricResultData]:
    keys = [str(uid) for uid in dict.fromkeys(activity_ids)]
    run_metrics = {
        "symptom_response_timeline",
        "session_rpe_load",
        "long_run_exposure",
        "intensity_time_distribution",
        "work_interval_execution",
        "aerobic_efficiency",
    }
    results = []
    for item in ordered_registry():
        if item.metric_id in run_metrics:
            results.extend(compute_subjects(session, item.metric_id, keys))
    return results


def _refresh_strength(session: Session, start: date, end: date) -> list[MetricResultData]:
    from app.models import ManualSession
    from app.strong_models import StrongWorkoutRow

    keys = [
        f"strong:{uid}"
        for uid in session.scalars(
            select(StrongWorkoutRow.id)
            .where(StrongWorkoutRow.local_date >= start, StrongWorkoutRow.local_date <= end)
            .order_by(StrongWorkoutRow.id)
        )
    ]
    keys += [
        f"manual:{uid}"
        for uid in session.scalars(
            select(ManualSession.id)
            .where(ManualSession.date >= start, ManualSession.date <= end)
            .order_by(ManualSession.id)
        )
    ]
    return compute_subjects(session, "session_rpe_load", keys)


def _plan_uids(
    session: Session, start: date | None = None, end: date | None = None, *, days: set[date] | None = None
) -> list[uuid.UUID]:
    head = head_version(session, populate_existing=True)
    rows = sorted(
        (row for row in latest_revisions(session, head).values() if not row.deleted),
        key=lambda row: (row.local_date, row.slot, str(row.session_uid)),
    )
    return [
        row.session_uid
        for row in rows
        if (start is None or row.local_date >= start)
        and (end is None or row.local_date <= end)
        and (days is None or row.local_date in days)
    ]


def refresh_plans(session: Session, uids: Iterable[uuid.UUID]) -> list[MetricResultData]:
    keys = list(dict.fromkeys(str(uid) for uid in uids))
    linked = list(
        session.scalars(
            select(SessionCompletion.activity_id).where(
                SessionCompletion.session_uid.in_([uuid.UUID(key) for key in keys]),
                SessionCompletion.activity_id.is_not(None),
            )
        )
    )
    refresh_runs(session, [uid for uid in linked if uid is not None])
    from app.metrics.planned_actual import write_completion_status

    results = compute_subjects(session, "planned_actual_session", keys)
    now = clock(session)
    changed = False
    for result in results:
        if write_completion_status(session, result, now):
            changed = True
    if changed:
        bump_data_revision(session)
    return results


def assess_completion(session: Session, session_uid: uuid.UUID) -> None:
    with refreshing(session):
        refresh_plans(session, [session_uid])
        session.flush()


def ensure_nights(session: Session, start: date, end: date) -> None:
    if start > end:
        raise ValueError("invalid_date_window")
    with refreshing(session):
        compute_subjects(
            session,
            "recovery_multisignal_summary",
            [f"night:{start + timedelta(days=n)}" for n in range((end - start).days + 1)],
        )


def ensure_windows(session: Session, as_of: date) -> None:
    with refreshing(session):
        start = as_of - timedelta(days=83)
        activity_ids = activities_between(session, start, as_of)
        refresh_runs(session, activity_ids)
        _refresh_strength(session, start, as_of)
        linked = session.scalars(
            select(SessionCompletion.session_uid).where(SessionCompletion.activity_id.in_(activity_ids))
        )
        refresh_plans(session, [*_plan_uids(session, as_of - timedelta(days=13), as_of + timedelta(days=13)), *linked])
        ensure_nights(session, as_of - timedelta(days=6), as_of)
        for metric_id in (
            "run_volume_frequency",
            "long_run_exposure",
            "session_rpe_load",
            "intensity_time_distribution",
        ):
            compute_subjects(session, metric_id, [f"w{n}:{as_of}" for n in (7, 14, 28, 56, 84)])
        compute_subjects(session, "symptom_response_timeline", [f"w28:{as_of}"])
        compute_subjects(session, "recovery_multisignal_summary", [f"w7:{as_of}"])
        compute_subjects(session, "hard_session_spacing", [f"w14:{as_of}"])
        compute_subjects(session, "aerobic_efficiency", [f"w{n}:{as_of}" for n in (28, 84)])
        session.flush()


def _all_dates(session: Session) -> set[date]:
    from app.models import ManualSession, RecoveryObservation
    from app.strong_models import StrongWorkoutRow

    zone = athlete_tz(session)
    dates = {date_in_zone(stamp, zone) for stamp in session.scalars(select(Activity.start_at))}
    dates.update(session.scalars(select(ManualSession.date)))
    dates.update(session.scalars(select(StrongWorkoutRow.local_date)))
    dates.update(session.scalars(select(RecoveryObservation.source_date)))
    dates.update(session.scalars(select(CalendarSessionRevision.local_date)))
    return dates


@dataclass
class Targets:
    """What a set of refresh scopes reaches, before re-matching and expansion to subjects."""

    dates: set[date] = field(default_factory=set)
    recovery_dates: set[date] = field(default_factory=set)
    activity_ids: set[uuid.UUID] = field(default_factory=set)
    strength_keys: set[str] = field(default_factory=set)
    plan_uids: set[uuid.UUID] = field(default_factory=set)
    broad: bool = False
    since: date | None = None


def scope_targets(session: Session, scopes: Iterable[str]) -> Targets:
    from app.checkin_models import Checkin
    from app.models import ManualSession
    from app.strong_models import StrongWorkoutRow

    zone = athlete_tz(session)
    targets = Targets()
    for scope in scopes:
        kind, value = parse_scope(scope)
        if kind == "revision":
            continue
        if kind == "timezone":
            targets.broad = True
        elif kind == "since":
            assert isinstance(value, date)
            targets.since = min(targets.since, value) if targets.since else value
        elif kind == "date":
            assert isinstance(value, date)
            targets.dates.add(value)
        elif kind == "plan":
            assert isinstance(value, uuid.UUID)
            targets.plan_uids.add(value)
            targets.dates.update(recent_revision_dates(session, value))
        elif kind == "activity":
            assert isinstance(value, uuid.UUID)
            targets.activity_ids.add(value)
            row = session.get(Activity, value)
            if row:
                targets.dates.add(date_in_zone(row.start_at, zone))
        elif kind == "checkin":
            checkin = session.get(Checkin, value)
            if checkin:
                day = date_in_zone(checkin.observed_at, zone)
                targets.dates.update(day - timedelta(days=n) for n in range(3))
                targets.recovery_dates.add(day)
                if checkin.activity_id:
                    targets.activity_ids.add(checkin.activity_id)
        elif kind.startswith("strength:"):
            prefix = kind.split(":")[1]
            targets.strength_keys.add(f"{prefix}:{value}")
            subject: Any = session.get(StrongWorkoutRow if prefix == "strong" else ManualSession, value)
            if subject:
                targets.dates.add(subject.local_date if prefix == "strong" else subject.date)
        elif kind == "recovery_dates":
            assert isinstance(value, tuple)
            targets.recovery_dates.update(value)
            targets.dates.update(value)
    if targets.broad:
        targets.dates.update(_all_dates(session))
        targets.recovery_dates.update(targets.dates)
    elif targets.since is not None:
        targets.dates.update(day for day in _all_dates(session) if day >= targets.since)
    return targets


def _date_ranges(days: Iterable[date], before: int, after: int) -> list[tuple[date, date]]:
    """Merge the inclusive ranges [day - before, day + after] into disjoint inclusive ranges."""
    ranges: list[tuple[date, date]] = []
    for day in sorted(set(days)):
        start, end = day - timedelta(days=before), day + timedelta(days=after)
        if ranges and start <= ranges[-1][1] + timedelta(days=1):
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    return ranges


def refresh_targets(session: Session, targets: Targets, matched_plan_uids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Recompute every subject `targets` reaches. Matching has already run; prompts run after.

    Returns the counts for the refresh log line.
    """
    today = local_today(session)
    activity_ids = set(targets.activity_ids)
    for start, end in _date_ranges(targets.dates, before=2, after=30):
        activity_ids.update(activities_between(session, start, end))
    if targets.broad:
        activity_ids.update(session.scalars(select(Activity.id)))
    refresh_runs(session, sorted(activity_ids, key=str))
    compute_subjects(session, "session_rpe_load", sorted(targets.strength_keys))
    linked = session.scalars(
        select(SessionCompletion.session_uid).where(SessionCompletion.activity_id.in_(activity_ids))
    )
    strength_links: list[uuid.UUID] = []
    for key in targets.strength_keys:
        kind, raw_id = key.split(":", 1)
        column = SessionCompletion.strong_workout_id if kind == "strong" else SessionCompletion.manual_session_id
        strength_links.extend(session.scalars(select(SessionCompletion.session_uid).where(column == uuid.UUID(raw_id))))
    # Unlinked plans can gain or lose a move candidate without a completion change.
    matching_days = {day + timedelta(days=offset) for day in targets.dates for offset in (-1, 0, 1)}
    if targets.broad:
        nearby_plans = _plan_uids(session)
    else:
        nearby_plans = []
        if targets.since is not None:
            nearby_plans = _plan_uids(session, targets.since)
            matching_days = {day for day in matching_days if day < targets.since}
        if matching_days:
            nearby_plans.extend(_plan_uids(session, days=matching_days))
    plan_uids = [*matched_plan_uids, *linked, *targets.plan_uids, *strength_links, *nearby_plans]
    refresh_plans(session, plan_uids)
    as_ofs = {today}
    current = session.execute(
        select(MetricResultRow.subject_key, MetricResultRow.metric_id).where(
            current_result_filter(), MetricResultRow.subject_type.in_(("window", "night"))
        )
    ).all()
    stored_nights = set()
    for key, metric_id in current:
        match = re.fullmatch(r"w(\d+):(\d{4}-\d{2}-\d{2})(?::(?:run|strength))?", key)
        if match:
            end = date.fromisoformat(match[2])
            width = int(match[1]) * (2 if metric_id == "run_volume_frequency" else 1)
            if (
                targets.broad
                or (targets.since is not None and end >= targets.since)
                or any(end - timedelta(days=width - 1) <= day <= end for day in targets.dates)
                or (
                    metric_id == "hard_session_spacing"
                    and any(abs((end - day).days) <= SPACING_REACH_DAYS for day in targets.dates)
                )
            ):
                as_ofs.add(end)
        elif key.startswith("night:"):
            stored_nights.add(date.fromisoformat(key[6:]))
    for day in targets.recovery_dates:
        end = min(day + timedelta(days=60), today)
        if day <= end:
            ensure_nights(session, day, end)
        for stored in stored_nights:
            if day <= stored <= day + timedelta(days=60):
                ensure_nights(session, stored, stored)
        for key, metric_id in current:
            if metric_id == "recovery_multisignal_summary" and key.startswith("w7:"):
                end = date.fromisoformat(key[3:])
                if day <= end <= day + timedelta(days=66):
                    as_ofs.add(end)
    for as_of in sorted(as_ofs):
        ensure_windows(session, as_of)
    return {
        "dates": len(targets.dates),
        "activities": len(activity_ids),
        "plans": len(set(plan_uids)),
        "windows": len(as_ofs),
        "nights": len(targets.recovery_dates),
    }
