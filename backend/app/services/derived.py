"""Keeps derived state current after source writes.

Session listeners record which source rows changed at each flush and turn them into refresh
scopes. At commit, in the same transaction, `_before_commit` bumps `data_revision` and runs the
refresh, so a failed refresh rolls the write back. `app.main` and `app.cli` call `install()`.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import event, func, inspect, select
from sqlalchemy.orm import Session

from app import logs
from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.db import bump_data_revision, global_write_lock
from app.domain.local_time import date_in_zone
from app.fit_models import FitFile
from app.metric_models import MetricResult as MetricResultRow
from app.metrics import refresh
from app.metrics.recovery import SIGNALS
from app.models import (
    Activity,
    ActivityAnnotation,
    ActivitySource,
    AppState,
    CoverageInterval,
    ProfileVersion,
    RecoveryObservation,
)
from app.read.calendar import latest_revision
from app.services.matching import rematch_dates
from app.services.prompts import generate_prompts
from app.services.timezone import athlete_tz

REFRESH_ENABLED = True
"""Test seam: suites that run matching or an assessor themselves set this False. Commits still bump `data_revision`."""


log = logs.get("metrics")


def refresh_scopes(session: Session, scopes: Iterable[str]) -> None:
    """Commit-time pipeline: scopes → re-match touched days → recompute metrics → prompts, then one log line."""
    started = time.perf_counter()
    scopes = list(scopes)
    targets = refresh.scope_targets(session, scopes)
    today = refresh.local_today(session)
    include_training_today = targets.recovery_only and not refresh.has_training_windows(session, today)
    matched = set()
    reconciled = set()
    if targets.manual_completion_only:
        reconciled = {
            plan.local_date
            for uid in targets.manual_completion_uids
            if (plan := latest_revision(session, uid)) is not None
        }
        matched = rematch_dates(session, reconciled)
    if matched or not targets.manual_completion_only:
        targets.expand_manual_completions(session)
        if not targets.recovery_only or include_training_today:
            remaining = (targets.dates | {today}) - reconciled
            if remaining:
                matched.update(rematch_dates(session, remaining))
    session.flush()
    counts = refresh.refresh_targets(session, targets, matched, include_training_today=include_training_today)
    generate_prompts(session, refresh.clock(session))
    session.flush()
    log.info(
        "refresh scopes=%d dates=%d activities=%d plans=%d windows=%d nights=%d broad=%s ms=%d",
        len(scopes),
        counts["dates"],
        counts["activities"],
        counts["plans"],
        counts["windows"],
        counts["nights"],
        targets.broad,
        round((time.perf_counter() - started) * 1000),
    )


def recompute(session: Session, scopes: Iterable[str]) -> None:
    """Run the pipeline outside a commit, under the global write lock (demo seed)."""
    with refresh.refreshing(session):
        refresh_scopes(session, scopes)


def _source_types() -> tuple[type, ...]:
    from app.calendar_models import CalendarVersion
    from app.checkin_models import Checkin, SessionRpe, SymptomReport
    from app.fit_models import ActivityLap, ActivityStream, ActivityWorkoutStep
    from app.models import ManualSession
    from app.planning_models import (
        Block,
        BlockDecision,
        BlockVersion,
        Event,
        Goal,
        IntensityAnchor,
        StrengthRoutineSlot,
    )
    from app.strong_models import StrongWorkoutRow
    from app.travel_models import GcalEvent, Trip, TripLeg

    return (
        Activity,
        ActivityAnnotation,
        ActivitySource,
        FitFile,
        ActivityLap,
        ActivityWorkoutStep,
        ActivityStream,
        SessionRpe,
        StrongWorkoutRow,
        ManualSession,
        Checkin,
        SymptomReport,
        CalendarVersion,
        CalendarSessionRevision,
        SessionCompletion,
        CoverageInterval,
        IntensityAnchor,
        RecoveryObservation,
        ProfileVersion,
        StrengthRoutineSlot,
        Goal,
        Event,
        Block,
        BlockVersion,
        BlockDecision,
        GcalEvent,
        Trip,
        TripLeg,
    )


def _timezone_changed(session: Session, row: ProfileVersion, old: dict) -> bool:
    """Whether this profile write can change the athlete timezone the metrics use."""
    if inspect(row).was_deleted:
        return True
    previous = (
        old.get("timezone")
        if old
        else session.scalar(
            select(ProfileVersion.timezone)
            .where(ProfileVersion.version < row.version)
            .order_by(ProfileVersion.version.desc())
            .limit(1)
        )
    )
    return previous != row.timezone


def _coverage_boundaries(session: Session) -> frozenset[int]:
    """Return the half-open boundaries of the effective activities coverage union."""
    intervals = session.execute(
        select(CoverageInterval.start_date, CoverageInterval.end_date)
        .where(
            CoverageInterval.dataset == "activities",
            CoverageInterval.status == "complete",
            CoverageInterval.fully_enumerated.is_(True),
        )
        .order_by(CoverageInterval.start_date)
    )
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        first, stop = start.toordinal(), end.toordinal() + 1
        if first >= stop:
            continue
        if merged and first <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(stop, merged[-1][1]))
        else:
            merged.append((first, stop))
    return frozenset(boundary for interval in merged for boundary in interval)


def _complete_activities(facts: dict) -> bool:
    return (
        facts.get("dataset") == "activities"
        and facts.get("status") == "complete"
        and facts.get("fully_enumerated") is True
    )


_COVERAGE_FIELDS = {"dataset", "status", "fully_enumerated", "start_date", "end_date"}


def _capture_coverage_before(session: Session, row: CoverageInterval, old: dict, changes: set[str]) -> None:
    deleting = row in session.deleted
    new = {} if deleting else {**old, **{key: getattr(row, key) for key in _COVERAGE_FIELDS & changes}}
    if _complete_activities(old) or _complete_activities(new):
        session.info["metrics_complete_coverage_touched"] = True
        if "metrics_coverage_before" not in session.info and (deleting or not changes.isdisjoint(_COVERAGE_FIELDS)):
            if not old:
                global_write_lock(session)
            session.info["metrics_coverage_before"] = _coverage_boundaries(session)


def _add_recovery_scopes(scopes: set[str], *facts: dict) -> None:
    days = {row["source_date"] for row in facts if row.get("metric") in SIGNALS and row.get("source_date") is not None}
    scopes.update(f"recovery_dates:{day}" for day in days)
    if not days:
        scopes.add("revision")


def _unlinked_self_report(facts: dict) -> bool:
    return (
        facts.get("match_method") == "user_marked"
        and facts.get("status") == "completed_as_planned"
        and not any(facts.get(key) for key in ("activity_id", "strong_workout_id", "manual_session_id"))
    )


def _before_flush(session: Session, _context, _instances) -> None:
    if session.info.get("metrics_running"):
        return
    rows = [row for row in (*session.new, *session.dirty, *session.deleted) if isinstance(row, _source_types())]
    if not rows:
        return
    pending = session.info.setdefault("metrics_pending_sources", [])
    for row in rows:
        state = inspect(row)
        changes = {attribute.key for attribute in state.attrs if attribute.history.has_changes()}
        if state.persistent and row not in session.deleted:
            if not changes:
                continue
            if (
                isinstance(row, SessionCompletion)
                and changes <= {"status", "version", "updated_at"}
                and ("status" not in changes or any((row.activity_id, row.strong_workout_id, row.manual_session_id)))
            ):
                continue
            # Retry diagnostics do not change the decoded FIT inputs.
            if isinstance(row, FitFile) and changes <= {"last_attempt_at", "last_error"}:
                continue
        if isinstance(row, (CoverageInterval, RecoveryObservation)) and state.identity is not None:
            # Read the facts used to select scopes while excluding other source writers.
            global_write_lock(session)
        old = {}
        if state.identity is not None:
            table = state.mapper.local_table
            predicate = [
                column == value for column, value in zip(state.mapper.primary_key, state.identity, strict=True)
            ]
            stored = session.connection().execute(select(table).where(*predicate)).mappings().first()
            old = dict(stored) if stored else {}
        if isinstance(row, CoverageInterval):
            _capture_coverage_before(session, row, old, changes)
            if "metrics_coverage_before" not in session.info:
                session.info.setdefault("metrics_scopes", set()).add("revision")
            continue
        if isinstance(row, RecoveryObservation):
            new = (
                {}
                if row in session.deleted
                else {
                    **old,
                    **{key: getattr(row, key) for key in {"metric", "source_date"} & changes},
                }
            )
            _add_recovery_scopes(session.info.setdefault("metrics_scopes", set()), old, new)
            continue
        pending.append((row, old))


def _after_flush(session: Session, _context) -> None:
    if session.info.get("metrics_running"):
        return
    from app.calendar_models import CalendarVersion
    from app.checkin_models import Checkin, SessionRpe, SymptomReport
    from app.models import ManualSession
    from app.planning_models import (
        Block,
        BlockDecision,
        BlockVersion,
        Event,
        Goal,
        IntensityAnchor,
        StrengthRoutineSlot,
    )
    from app.strong_models import StrongWorkoutRow
    from app.travel_models import GcalEvent, Trip, TripLeg

    pending = session.info.pop("metrics_pending_sources", [])
    if not pending:
        return
    zone = athlete_tz(session)
    scopes = session.info.setdefault("metrics_scopes", set())
    for row, old in pending:
        if isinstance(
            row, (CalendarVersion, Goal, Event, Block, BlockVersion, BlockDecision, GcalEvent, Trip, TripLeg)
        ):
            scopes.add("revision")
            continue
        if isinstance(row, ProfileVersion):
            scopes.add("timezone" if _timezone_changed(session, row, old) else "revision")
            continue
        if isinstance(row, StrengthRoutineSlot):
            scopes.add(f"since:{refresh.local_today(session)}")
            continue
        state = inspect(row)
        new = {column.key: getattr(row, column.key, None) for column in state.mapper.columns}
        if isinstance(row, SessionCompletion) and state.was_deleted:
            new = {}
        if (
            isinstance(row, SessionCompletion)
            and (old or new)
            and all(not facts or _unlinked_self_report(facts) for facts in (old, new))
        ):
            scopes.update(f"manual_completion:{facts['session_uid']}" for facts in (old, new) if facts)
            continue
        for facts in (old, new):
            uid = facts.get("id")
            for name in ("local_date", "date", "source_date", "valid_from"):
                value = facts.get(name)
                if isinstance(value, date) and not isinstance(value, datetime):
                    scopes.add(f"date:{value}")
            for name in ("start_at", "end_at", "observed_at"):
                value = facts.get(name)
                if isinstance(value, datetime):
                    scopes.add(f"date:{date_in_zone(value, zone)}")
            if isinstance(row, Activity) and uid:
                scopes.add(f"activity:{uid}")
            elif isinstance(row, Checkin) and uid:
                scopes.add(f"checkin:{uid}")
                observed = facts.get("observed_at")
                if isinstance(observed, datetime):
                    day = date_in_zone(observed, zone)
                    scopes.update(f"date:{day - timedelta(days=n)}" for n in range(3))
                    scopes.add(f"recovery_dates:{day}")
            elif isinstance(row, StrongWorkoutRow) and uid:
                scopes.add(f"strength:strong:{uid}")
            elif isinstance(row, ManualSession) and uid:
                scopes.add(f"strength:manual:{uid}")
            elif isinstance(row, IntensityAnchor) and facts.get("valid_from"):
                scopes.add(f"since:{facts['valid_from']}")
            elif isinstance(row, CalendarSessionRevision) and facts.get("session_uid"):
                scopes.add(f"plan:{facts['session_uid']}")
            if facts.get("activity_id"):
                scopes.add(f"activity:{facts['activity_id']}")
            if isinstance(row, SymptomReport) and facts.get("checkin_id"):
                scopes.add(f"checkin:{facts['checkin_id']}")
            if isinstance(row, (SessionRpe, SessionCompletion)):
                for column, kind in (("strong_workout_id", "strong"), ("manual_session_id", "manual")):
                    if facts.get(column):
                        scopes.add(f"strength:{kind}:{facts[column]}")
            if isinstance(row, SessionCompletion) and facts.get("session_uid"):
                # Old and new facts both pass here, so a relink refreshes both plans.
                scopes.add(f"plan:{facts['session_uid']}")


def _before_commit(session: Session) -> None:
    if session.info.get("metrics_running") or session.in_nested_transaction():
        return
    session.flush()
    scopes = set(session.info.get("metrics_scopes", ()))
    before = session.info.get("metrics_coverage_before")
    if before is not None:
        # A boundary in exactly one union toggles whether coverage differs.
        boundaries = iter(sorted(before ^ _coverage_boundaries(session)))
        for first, stop in zip(boundaries, boundaries, strict=True):
            scopes.update(f"coverage_date:{date.fromordinal(day)}" for day in range(first, stop))
        if not scopes:
            scopes.add("revision")
    if not scopes:
        return
    with refresh.refreshing(session):
        session.execute(select(AppState.id).where(AppState.id == 1).with_for_update())
        bump_data_revision(session)
        if REFRESH_ENABLED:
            if scopes != {"revision"}:
                refresh_scopes(session, scopes)
            elif session.info.get("metrics_complete_coverage_touched"):
                if refresh.has_training_windows(session, refresh.local_today(session)):
                    generate_prompts(session, refresh.clock(session))
                else:
                    refresh_scopes(session, scopes)
        session.flush()
    for key in (*_SCOPE_KEYS, "metrics_pending_sources"):
        session.info.pop(key, None)


_SCOPE_KEYS = ("metrics_scopes", "metrics_coverage_before", "metrics_complete_coverage_touched")


def _save_nested_scopes(session: Session, transaction) -> None:
    if transaction.nested:
        inherited = {key: session.info[key] for key in _SCOPE_KEYS if key in session.info}
        if "metrics_scopes" in inherited:
            inherited["metrics_scopes"] = inherited["metrics_scopes"].copy()
        transaction._metrics_inherited_scopes = inherited


def _restore_nested_scopes(session: Session, transaction) -> None:
    for key in _SCOPE_KEYS:
        session.info.pop(key, None)
    if transaction.nested:
        session.info.update(getattr(transaction, "_metrics_inherited_scopes", {}))
    session.info.pop("metrics_pending_sources", None)
    session.info.pop("metrics_computed", None)


def _clear_transaction_scopes(session: Session, transaction) -> None:
    if transaction.parent is None:
        for key in (*_SCOPE_KEYS, "metrics_pending_sources", "metrics_running", "metrics_computed", "metrics_depth"):
            session.info.pop(key, None)


def install() -> None:
    listeners = (
        ("before_flush", _before_flush),
        ("after_flush_postexec", _after_flush),
        ("before_commit", _before_commit),
        ("after_transaction_create", _save_nested_scopes),
        ("after_soft_rollback", _restore_nested_scopes),
        ("after_transaction_end", _clear_transaction_scopes),
    )
    for name, listener in listeners:
        if not event.contains(Session, name, listener):
            event.listen(Session, name, listener)


def refresh_today(session: Session) -> dict[str, Any]:
    """Startup pass: today's windows and the eager set behind them, then prompts. Returns a summary."""
    started = time.perf_counter()
    with refresh.refreshing(session):
        before = session.scalar(select(func.count()).select_from(MetricResultRow)) or 0
        as_of = refresh.local_today(session)
        refresh.ensure_windows(session, as_of)
        generate_prompts(session, refresh.clock(session))
        session.flush()
    new_results = (session.scalar(select(func.count()).select_from(MetricResultRow)) or 0) - before
    ms = round((time.perf_counter() - started) * 1000)
    log.info("startup refresh as_of=%s new_results=%d ms=%d", as_of, new_results, ms)
    return {"as_of": as_of.isoformat(), "new_results": new_results, "ms": ms}
