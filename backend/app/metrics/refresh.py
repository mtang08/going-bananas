"""Metric recomputation: select subjects with `scope_targets` and refresh them with `refresh_targets`.
The commit-time pipeline that also re-matches and updates prompts is
`app.services.derived.refresh_scopes`. Snapshot, CLI, and demo seed call
`ensure_windows`, `ensure_nights`, and `assess_completion` directly. Work outside a commit runs
inside `refreshing(session)`, which takes the global write lock and caches computed subjects.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any, cast

from sqlalchemy import select, tuple_
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
from app.metrics.recovery import CONFIG as RECOVERY_CONFIG
from app.metrics.recovery import METRIC_ID as RECOVERY_METRIC
from app.metrics.recovery import WINDOW_DAYS as RECOVERY_WINDOWS
from app.metrics.spacing import METRIC_ID as SPACING_METRIC
from app.metrics.spacing import batch_calculator, plan_classes
from app.models import Activity
from app.read.calendar import head_version, latest_revision, latest_revisions, recent_revision_dates
from app.services.timezone import athlete_today, athlete_tz


def parse_scope(scope: str) -> tuple[str, Any]:
    """Split a refresh scope into `(kind, value)`, or raise `ValueError('invalid_scope')`.

    `activity:`, `checkin:`, `plan:`, `manual_completion:`, `strength:strong:` and `strength:manual:` carry a UUID.
    `date:`, `since:`, and `coverage_date:` carry an ISO date; `recovery_dates:` comma-separated ISO dates.
    `timezone` and `revision` carry nothing.
    """
    kind, _, raw = scope.partition(":")
    try:
        if scope in ("timezone", "revision"):
            return scope, None
        if kind in ("activity", "checkin", "plan", "manual_completion"):
            return kind, uuid.UUID(raw)
        if kind == "strength":
            prefix, _, raw_id = raw.partition(":")
            if prefix in ("strong", "manual"):
                return f"strength:{prefix}", uuid.UUID(raw_id)
        if kind in ("date", "since", "coverage_date"):
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


# Ordinary date changes refresh nearby spacing windows. Coverage can affect long runs farther away.
SPACING_REACH_DAYS = 14
LONG_RUN_COMPARATOR_DAYS = 30
RECOVERY_BASELINE_DAYS = cast(int, RECOVERY_CONFIG["baseline_days"])
(RECOVERY_WINDOW_DAYS,) = RECOVERY_WINDOWS

STANDARD_WINDOWS = (7, 14, 28, 56, 84)
WINDOW_DAYS_BY_METRIC = {
    "run_volume_frequency": STANDARD_WINDOWS,
    "long_run_exposure": STANDARD_WINDOWS,
    "session_rpe_load": STANDARD_WINDOWS,
    "intensity_time_distribution": STANDARD_WINDOWS,
    "symptom_response_timeline": (28,),
    RECOVERY_METRIC: RECOVERY_WINDOWS,
    "hard_session_spacing": (14,),
    "aerobic_efficiency": (28, 84),
}


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


def compute_subjects(
    session: Session,
    metric_id: str,
    subject_keys: Sequence[str],
    *,
    calculate: Callable[[str], list[MetricResultData]] | None = None,
) -> list[MetricResultData]:
    metric_modules()
    if metric_id not in REGISTRY:
        raise ValueError("unknown_metric")
    allowed = session.info.get("metrics_filter")
    if allowed is not None and metric_id not in allowed:
        return []
    registration = REGISTRY[metric_id]
    calculate = calculate or partial(registration.compute, session)
    cache = session.info.get("metrics_computed", set())
    results = []
    for key in dict.fromkeys(subject_keys):
        if (metric_id, key) in cache:
            continue
        calculated = [replace(row, calculated_at=clock(session)) for row in calculate(key)]
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
            RECOVERY_METRIC,
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
        ensure_nights(session, as_of - timedelta(days=RECOVERY_WINDOW_DAYS - 1), as_of)
        for metric_id, widths in WINDOW_DAYS_BY_METRIC.items():
            compute_subjects(session, metric_id, [f"w{width}:{as_of}" for width in widths])
        session.flush()


def has_training_windows(session: Session, as_of: date) -> bool:
    """A filtered recompute can leave a date with only some of its windows."""
    expected = {
        (metric_id, f"w{width}:{as_of}{suffix}")
        for metric_id, widths in WINDOW_DAYS_BY_METRIC.items()
        for width in widths
        for suffix in ((":run", ":strength") if metric_id == "session_rpe_load" else ("",))
    }
    stored = session.execute(
        select(MetricResultRow.metric_id, MetricResultRow.subject_key).where(
            current_result_filter(),
            MetricResultRow.subject_type == "window",
            tuple_(MetricResultRow.metric_id, MetricResultRow.subject_key).in_(sorted(expected)),
        )
    )
    return expected.issubset((metric_id, key) for metric_id, key in stored)


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
    coverage_dates: set[date] = field(default_factory=set)
    activity_ids: set[uuid.UUID] = field(default_factory=set)
    strength_keys: set[str] = field(default_factory=set)
    plan_uids: set[uuid.UUID] = field(default_factory=set)
    manual_completion_uids: set[uuid.UUID] = field(default_factory=set)
    broad: bool = False
    since: date | None = None

    @property
    def recovery_only(self) -> bool:
        return bool(self.recovery_dates) and not (
            self.dates
            or self.activity_ids
            or self.strength_keys
            or self.plan_uids
            or self.manual_completion_uids
            or self.broad
            or self.since
        )

    @property
    def manual_completion_only(self) -> bool:
        return bool(self.manual_completion_uids) and not (
            self.dates
            or self.activity_ids
            or self.strength_keys
            or self.plan_uids
            or self.recovery_dates
            or self.broad
            or self.since
        )

    def expand_manual_completions(self, session: Session) -> None:
        self.plan_uids.update(self.manual_completion_uids)
        for uid in self.manual_completion_uids:
            self.dates.update(recent_revision_dates(session, uid))


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
        elif kind == "coverage_date":
            assert isinstance(value, date)
            targets.coverage_dates.add(value)
            targets.dates.add(value)
        elif kind == "plan":
            assert isinstance(value, uuid.UUID)
            targets.plan_uids.add(value)
            targets.dates.update(recent_revision_dates(session, value))
        elif kind == "manual_completion":
            assert isinstance(value, uuid.UUID)
            targets.manual_completion_uids.add(value)
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


def _training_window_dates(
    session: Session, targets: Targets, today: date, *, has_activities: bool
) -> tuple[set[date], set[date]]:
    as_ofs = {today}
    coverage_spacing = set()
    current = session.execute(
        select(MetricResultRow.subject_key, MetricResultRow.metric_id).where(
            current_result_filter(), MetricResultRow.subject_type == "window"
        )
    )
    for key, metric_id in current:
        match = re.fullmatch(r"w(\d+):(\d{4}-\d{2}-\d{2})(?::(?:run|strength))?", key)
        if not match:
            continue
        end = date.fromisoformat(match[2])
        width = int(match[1]) * (2 if metric_id == "run_volume_frequency" else 1)
        if (
            targets.broad
            or (targets.since is not None and end >= targets.since)
            or any(end - timedelta(days=width - 1) <= day <= end for day in targets.dates)
            or (
                metric_id == "long_run_exposure"
                and any(
                    end - timedelta(days=width - 1 + LONG_RUN_COMPARATOR_DAYS) <= day <= end
                    for day in targets.coverage_dates
                )
            )
            or (
                metric_id == "hard_session_spacing"
                and any(abs((end - day).days) <= SPACING_REACH_DAYS for day in targets.dates)
            )
        ):
            as_ofs.add(end)
        elif metric_id == "hard_session_spacing" and targets.coverage_dates and has_activities:
            # Spacing uses neighboring long runs from all stored history.
            coverage_spacing.add(end)
    return as_ofs, coverage_spacing - as_ofs


def _refresh_recovery(session: Session, source_dates: set[date], today: date, full_as_ofs: set[date]) -> set[date]:
    if not source_dates:
        return set()
    keys = session.scalars(
        select(MetricResultRow.subject_key).where(
            current_result_filter(),
            MetricResultRow.metric_id == RECOVERY_METRIC,
            MetricResultRow.subject_type.in_(("night", "window")),
        )
    )
    night_ranges = _date_ranges(source_dates, before=0, after=RECOVERY_BASELINE_DAYS)
    nights = {
        start + timedelta(days=offset)
        for start, end in night_ranges
        for offset in range((min(end, today) - start).days + 1)
    }
    summary_ranges = _date_ranges(source_dates, before=0, after=RECOVERY_BASELINE_DAYS + RECOVERY_WINDOW_DAYS - 1)
    summaries = {today} if any(start <= today <= end for start, end in summary_ranges) else set()
    for key in keys:
        prefix, _, raw_date = key.partition(":")
        day = date.fromisoformat(raw_date)
        if prefix == "night" and any(start <= day <= end for start, end in night_ranges):
            nights.add(day)
        elif prefix == f"w{RECOVERY_WINDOW_DAYS}" and any(start <= day <= end for start, end in summary_ranges):
            summaries.add(day)
    nights.difference_update(
        as_of - timedelta(days=offset) for as_of in full_as_ofs for offset in range(RECOVERY_WINDOW_DAYS)
    )
    summaries.difference_update(full_as_ofs)
    compute_subjects(session, RECOVERY_METRIC, [f"night:{day}" for day in sorted(nights)])
    compute_subjects(session, RECOVERY_METRIC, [f"w{RECOVERY_WINDOW_DAYS}:{day}" for day in sorted(summaries)])
    return summaries


def _manual_completion_spacing(
    session: Session, uids: set[uuid.UUID], today: date, *, associations_changed: bool = False
) -> set[date]:
    if not uids:
        return set()
    if not associations_changed and not any(
        plan is not None and not plan.deleted and plan_classes(session, plan)
        for plan in (latest_revision(session, uid) for uid in uids)
    ):
        return set()
    # Spacing provenance includes every hard exposure, including exposures outside the display window.
    keys = set(
        session.scalars(
            select(MetricResultRow.subject_key).where(
                current_result_filter(),
                MetricResultRow.metric_id == SPACING_METRIC,
                MetricResultRow.subject_type == "window",
            )
        )
    )
    keys.add(f"w14:{today}")
    compute_subjects(session, SPACING_METRIC, sorted(keys), calculate=batch_calculator(session))
    return {date.fromisoformat(key.removeprefix("w14:")) for key in keys}


def refresh_targets(
    session: Session,
    targets: Targets,
    matched_plan_uids: Iterable[uuid.UUID],
    *,
    include_training_today: bool = False,
) -> dict[str, int]:
    """Recompute every subject `targets` reaches. Matching has already run; prompts run after.

    The log counts distinct as-of dates for windows and touched source dates for nights.
    """
    today = local_today(session)
    if targets.manual_completion_only:
        keys = sorted(map(str, targets.manual_completion_uids))
        compute_subjects(session, "planned_actual_session", keys)
        as_ofs = _manual_completion_spacing(session, targets.manual_completion_uids, today)
        return {"dates": 0, "activities": 0, "plans": len(keys), "windows": len(as_ofs), "nights": 0}
    if targets.recovery_only:
        matched = sorted(set(matched_plan_uids), key=str)
        if matched:
            refresh_plans(session, matched)
        as_ofs = set()
        if include_training_today:
            ensure_windows(session, today)
            as_ofs.add(today)
        as_ofs.update(_refresh_recovery(session, targets.recovery_dates, today, as_ofs))
        return {
            "dates": 0,
            "activities": 0,
            "plans": len(matched),
            "windows": len(as_ofs),
            "nights": len(targets.recovery_dates),
        }
    activity_ids = set(targets.activity_ids)
    for start, end in _date_ranges(targets.dates, before=2, after=LONG_RUN_COMPARATOR_DAYS):
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
    matched = list(matched_plan_uids)
    plan_uids = [*matched, *linked, *targets.plan_uids, *strength_links, *nearby_plans]
    refresh_plans(session, plan_uids)
    as_ofs, coverage_spacing = _training_window_dates(session, targets, today, has_activities=bool(activity_ids))
    for as_of in sorted(as_ofs):
        ensure_windows(session, as_of)
    if coverage_spacing:
        compute_subjects(session, SPACING_METRIC, [f"w14:{day}" for day in sorted(coverage_spacing)])
    manual_spacing = _manual_completion_spacing(
        session, targets.manual_completion_uids, today, associations_changed=bool(matched)
    )
    recovery_as_ofs = _refresh_recovery(session, targets.recovery_dates, today, as_ofs)
    return {
        "dates": len(targets.dates),
        "activities": len(activity_ids),
        "plans": len(set(plan_uids)),
        "windows": len(as_ofs | recovery_as_ofs | coverage_spacing | manual_spacing),
        "nights": len(targets.recovery_dates),
    }
