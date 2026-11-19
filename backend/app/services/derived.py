"""Keeps derived state current after source writes.

Session listeners record which source rows changed at each flush and turn them into refresh
scopes. At commit, in the same transaction, `_before_commit` bumps `data_revision` and runs the
refresh, so a failed refresh rolls the write back. `app.main` and `app.cli` call `install()`.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.db import bump_data_revision
from app.fit_models import FitFile
from app.metrics import refresh
from app.models import Activity, ActivityAnnotation, ActivitySource, AppState, CoverageInterval, ProfileVersion
from app.services.timezone import athlete_tz

REFRESH_ENABLED = True
"""Test seam: suites that run matching or an assessor themselves set this False. Commits still bump `data_revision`."""


def enqueue(session: Session, scopes: Iterable[str]) -> None:
    values = list(scopes)
    for scope in values:
        refresh.parse_scope(scope)
    session.info.setdefault('metrics_scopes', set()).update(values)


def _source_types() -> tuple[type, ...]:
    from app.calendar_models import CalendarVersion
    from app.checkin_models import Checkin, SessionRpe, SymptomReport
    from app.fit_models import ActivityLap, ActivityStream, ActivityWorkoutStep
    from app.models import ManualSession, RecoveryObservation
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
    return (Activity, ActivityAnnotation, ActivitySource, FitFile, ActivityLap, ActivityWorkoutStep, ActivityStream,
            SessionRpe, StrongWorkoutRow, ManualSession, Checkin, SymptomReport, CalendarVersion,
            CalendarSessionRevision, SessionCompletion, CoverageInterval, IntensityAnchor,
            RecoveryObservation, ProfileVersion, StrengthRoutineSlot, Goal, Event, Block, BlockVersion, BlockDecision)


def _before_flush(session: Session, _context, _instances) -> None:
    if session.info.get('metrics_running'):
        return
    rows = [row for row in (*session.new, *session.dirty, *session.deleted) if isinstance(row, _source_types())]
    if not rows:
        return
    pending = session.info.setdefault('metrics_pending_sources', [])
    for row in rows:
        state = inspect(row)
        changes = {attribute.key for attribute in state.attrs if attribute.history.has_changes()}
        if isinstance(row, SessionCompletion) and state.persistent and changes <= {'status', 'version', 'updated_at'}:
            continue
        if state.persistent and row not in session.deleted:
            if not changes:
                continue
            # Retry diagnostics do not change the decoded FIT inputs.
            if isinstance(row, FitFile) and changes <= {'last_attempt_at', 'last_error'}:
                continue
        old = {}
        if state.identity is not None:
            table = state.mapper.local_table
            predicate = [column == value for column, value in zip(state.mapper.primary_key, state.identity, strict=True)]
            stored = session.connection().execute(select(table).where(*predicate)).mappings().first()
            old = dict(stored) if stored else {}
        pending.append((row, old))


def _after_flush(session: Session, _context) -> None:
    if session.info.get('metrics_running'):
        return
    from app.calendar_models import CalendarVersion
    from app.checkin_models import Checkin, SessionRpe, SymptomReport
    from app.models import ManualSession, RecoveryObservation
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
    pending = session.info.pop('metrics_pending_sources', [])
    if not pending:
        return
    zone = athlete_tz(session)
    scopes = session.info.setdefault('metrics_scopes', set())
    dates = session.info.setdefault('metrics_dates', set())
    for row, old in pending:
        new = {column.key: getattr(row, column.key, None) for column in inspect(row).mapper.columns}
        for facts in (old, new):
            uid = facts.get('id')
            for name in ('local_date', 'date', 'source_date', 'valid_from'):
                value = facts.get(name)
                if isinstance(value, date) and not isinstance(value, datetime):
                    dates.add(value)
            for name in ('start_at', 'end_at', 'observed_at'):
                value = facts.get(name)
                if isinstance(value, datetime):
                    dates.add(value.astimezone(zone).date())
            if isinstance(row, Activity) and uid:
                scopes.add(f'activity:{uid}')
            elif isinstance(row, Checkin) and uid:
                scopes.add(f'checkin:{uid}')
                observed = facts.get('observed_at')
                if isinstance(observed, datetime):
                    day = observed.astimezone(zone).date()
                    dates.update(day - timedelta(days=n) for n in range(3))
                    scopes.add(f'recovery_dates:{day}')
            elif isinstance(row, StrongWorkoutRow) and uid:
                scopes.add(f'strength:strong:{uid}')
            elif isinstance(row, ManualSession) and uid:
                scopes.add(f'strength:manual:{uid}')
            elif isinstance(row, RecoveryObservation) and facts.get('source_date'):
                scopes.add(f"recovery_dates:{facts['source_date']}")
            elif isinstance(row, IntensityAnchor) and facts.get('valid_from'):
                scopes.add(f"anchors:{facts['valid_from']}")
            elif isinstance(row, ProfileVersion):
                scopes.add('timezone')
            elif isinstance(row, (CalendarVersion, CalendarSessionRevision, StrengthRoutineSlot, Goal, Event, Block, BlockVersion, BlockDecision)):
                scopes.add('calendar')
                if isinstance(row, CalendarSessionRevision):
                    session.info.setdefault('metrics_plan_uids', set()).add(facts.get('session_uid'))
            elif isinstance(row, CoverageInterval) and facts.get('dataset') == 'activities':
                scopes.add(f"all:{facts['start_date']}")
            if facts.get('activity_id'):
                scopes.add(f"activity:{facts['activity_id']}")
            if isinstance(row, SymptomReport) and facts.get('checkin_id'):
                scopes.add(f"checkin:{facts['checkin_id']}")
            if isinstance(row, (SessionRpe, SessionCompletion)):
                for column, kind in (('strong_workout_id', 'strong'), ('manual_session_id', 'manual')):
                    if facts.get(column):
                        scopes.add(f"strength:{kind}:{facts[column]}")
            if isinstance(row, SessionCompletion):
                # Capture both old and new subject linkage before identity changes.
                session.info.setdefault('metrics_plan_uids', set()).add(facts.get('session_uid'))
                if not any(facts.get(key) for key in ('activity_id', 'strong_workout_id', 'manual_session_id')):
                    scopes.add('calendar')


def _before_commit(session: Session) -> None:
    if session.info.get('metrics_running') or session.in_nested_transaction():
        return
    session.flush()
    scopes = set(session.info.get('metrics_scopes', ()))
    if not scopes:
        return
    with refresh.refreshing(session):
        session.execute(select(AppState.id).where(AppState.id == 1).with_for_update())
        bump_data_revision(session)
        if REFRESH_ENABLED:
            refresh.refresh_scopes(session, scopes)
        session.flush()
    for key in ('metrics_scopes', 'metrics_dates', 'metrics_plan_uids', 'metrics_pending_sources'):
        session.info.pop(key, None)


_SCOPE_KEYS = ('metrics_scopes', 'metrics_dates', 'metrics_plan_uids')


def _save_nested_scopes(session: Session, transaction) -> None:
    if transaction.nested:
        transaction._metrics_inherited_scopes = {key: set(session.info.get(key, ())) for key in _SCOPE_KEYS}


def _restore_nested_scopes(session: Session, transaction) -> None:
    if transaction.nested:
        for key, value in getattr(transaction, '_metrics_inherited_scopes', {}).items():
            session.info[key] = value
    else:
        for key in _SCOPE_KEYS:
            session.info.pop(key, None)
    session.info.pop('metrics_pending_sources', None)
    session.info.pop('metrics_computed', None)


def _clear_transaction_scopes(session: Session, transaction) -> None:
    if transaction.parent is None:
        for key in (*_SCOPE_KEYS, 'metrics_pending_sources', 'metrics_running', 'metrics_computed', 'metrics_depth'):
            session.info.pop(key, None)


def install() -> None:
    listeners = (('before_flush', _before_flush), ('after_flush_postexec', _after_flush),
                 ('before_commit', _before_commit), ('after_transaction_create', _save_nested_scopes),
                 ('after_soft_rollback', _restore_nested_scopes), ('after_transaction_end', _clear_transaction_scopes))
    for name, listener in listeners:
        if not event.contains(Session, name, listener):
            event.listen(Session, name, listener)
