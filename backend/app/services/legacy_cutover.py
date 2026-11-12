"""Transaction-owned import of legacy planning history into calendar authority."""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, NoReturn, TypedDict, cast

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.agent_models import CoachPlanRevision
from app.calendar_models import (
    CalendarSessionRevision,
    CalendarVersion,
    LegacyImportMap,
    LegacyImportRun,
    SessionCompletion,
)
from app.coaching_models import CoachOutcome, CoachOutcomeEvent, CoachRecommendation
from app.migrations_head import EXPECTED_HEAD
from app.models import (
    Activity,
    ActivitySource,
    AppState,
    Checkin,
    CheckinRevision,
    CompletionLink,
    ManualSession,
    PlannedSession,
    PlanVersion,
    ProfileVersion,
    RawObject,
    SourceRecord,
    WeeklySnapshot,
)
from app.strong_models import StrongWorkoutRow

LOCK_ID = 71382413


def planning_authority(session: Session) -> str:
    """Read authority without taking a row lock or changing state."""
    value = session.scalar(select(AppState.planning_authority).where(AppState.id == 1))
    return value or 'legacy'


def require_legacy_write(session: Session) -> None:
    """Serialize with calendar writers before an old route reads or writes data."""
    session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': LOCK_ID})
    if planning_authority(session) != 'legacy':
        raise HTTPException(409, detail={'code': 'legacy_write_disabled',
            'message': 'Legacy planning writes are disabled. Use the calendar workflow.'})

SOURCE_MODELS: tuple[Any, ...] = (
    PlanVersion, PlannedSession, CompletionLink, Checkin, CheckinRevision,
    WeeklySnapshot, CoachPlanRevision, CoachRecommendation, CoachOutcome,
    CoachOutcomeEvent, ProfileVersion, ManualSession, StrongWorkoutRow, Activity,
    ActivitySource, SourceRecord, RawObject,
)
KNOWN_KINDS = {'run', 'strength', 'cross', 'rest', 'mobility'}
MARKER_KEY = 'remaining_mvp_v1'


class MigrationReport(TypedDict):
    key: str
    already_imported: bool
    source_fingerprint: str
    counts: dict[str, int]
    calendar_head: int
    undo_available: bool
    errors: list[str]


def _canonical(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('cutover_validation_failed')
        return value.astimezone(UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('cutover_validation_failed')
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _json(value: Any) -> str:
    return json.dumps(_canonical(value), sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def source_snapshot(session: Session) -> tuple[dict[str, int], dict[str, str], dict[str, list[tuple[uuid.UUID, dict, str]]]]:
    """Hash every persisted column of every named source row, including archives."""
    counts: dict[str, int] = {}
    hashes: dict[str, str] = {}
    rows: dict[str, list[tuple[uuid.UUID, dict, str]]] = {}
    for model in SOURCE_MODELS:
        table = model.__table__.name
        entries = []
        row: Any
        for row in session.scalars(select(model)).all():
            payload = {column.name: _canonical(getattr(row, column.name))
                       for column in sorted(model.__table__.columns, key=lambda col: col.name)}
            entries.append((row.id, payload, _sha(payload)))
        entries.sort(key=lambda entry: str(entry[0]))
        rows[table] = entries
        counts[table] = len(entries)
        hashes[table] = _sha([[str(uid), digest] for uid, _, digest in entries])
    return counts, hashes, rows


def _fail(code: str, message: str, status: int = 422) -> NoReturn:
    raise HTTPException(status, detail={'code': code, 'message': message})


def _si(value: Any, multiplier: int) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        scaled = Decimal(str(value)) * multiplier
    except Exception:
        return None
    if not scaled.is_finite() or scaled != scaled.to_integral_value() or scaled <= 0:
        return None
    return int(scaled)


def _session_fields(row: PlannedSession, *, slot: int, today: date) -> dict[str, Any]:
    if row.kind not in KNOWN_KINDS:
        _fail('unsupported_legacy_kind', 'A legacy session kind cannot be imported')
    target = row.target or {}
    if not isinstance(target, dict):
        _fail('cutover_validation_failed', 'Legacy session target is invalid')
    original_intent = target.get('intent') or target.get('purpose') or row.kind
    if not isinstance(original_intent, str):
        original_intent = row.kind
    prose = [str(target[key]) for key in ('purpose', 'prescription', 'intensity', 'reason', 'notes')
             if target.get(key) is not None]
    if isinstance(target.get('steps'), list):
        prose.extend(str(step) for step in target['steps'])
    if len(original_intent) > 200:
        prose.insert(0, original_intent)
    return {'local_date': row.date, 'slot': slot, 'kind': row.kind,
            'recipe_id': None, 'custom': False, 'locked': bool(target.get('locked', False)),
            'legacy_unstructured': row.kind == 'run', 'legacy_payload': target,
            'placeholder': False, 'intent': original_intent[:200],
            'certainty': 'committed' if row.date <= today + timedelta(days=6) else 'provisional',
            'planned_duration_s': _si(target.get('duration_minutes'), 60),
            'planned_distance_m': _si(target.get('distance_km'), 1000),
            'structure': None, 'strength_slot_id': None,
            'notes': '\n'.join(prose) or None}


def _membership(session: Session, planned: dict[uuid.UUID, PlannedSession]) -> set[uuid.UUID]:
    from app.api.core import plan_data
    from app.services.agent_plans import latest
    current = latest(session)
    if current is not None and isinstance(current.payload.get('active_session_ids'), list):
        try:
            ids = {uuid.UUID(str(raw)) for raw in current.payload['active_session_ids']}
        except (TypeError, ValueError):
            _fail('cutover_validation_failed', 'Legacy active membership is invalid')
        if not ids <= planned.keys():
            _fail('cutover_validation_failed', 'Legacy active membership references a missing session')
        return ids
    accepted = session.scalars(select(PlanVersion).where(PlanVersion.status == 'accepted')).all()
    return {item['id'] for plan in accepted for item in plan_data(session, plan)['sessions']}


def _import(session: Session, state: AppState, *, dry_run: bool) -> MigrationReport:
    from app.metrics.engine import recompute
    from app.services.agent_plans import latest, revertible
    from app.services.calendar import _today
    if session.scalar(text('SELECT version_num FROM alembic_version')) != EXPECTED_HEAD:
        _fail('schema_not_ready', 'Schema head is not ready for cutover', 409)
    prior = session.scalar(select(LegacyImportRun).where(LegacyImportRun.key == MARKER_KEY))
    if prior:
        if state.planning_authority != 'calendar':
            _fail('cutover_inconsistent', 'Import marker and planning authority disagree', 409)
        return cast(MigrationReport, {**prior.report, 'already_imported': True})
    if state.planning_authority != 'legacy':
        _fail('cutover_inconsistent', 'Calendar authority has no import marker', 409)
    if (state.calendar_head_version != 0 or
            any(session.scalar(select(func.count()).select_from(model))
                for model in (CalendarVersion, CalendarSessionRevision, SessionCompletion, LegacyImportMap))):
        _fail('cutover_target_not_empty', 'Calendar already contains versions', 409)
    counts_before, hashes_before, archive = source_snapshot(session)
    fingerprint = _sha({name: {'count': counts_before[name], 'sha256': hashes_before[name]}
                        for name in sorted(counts_before)})
    planned_rows = {row.id: row for row in session.scalars(select(PlannedSession)).all()}
    current_ids = _membership(session, planned_rows)
    links = session.scalars(select(CompletionLink)).all()
    linked_ids = {link.planned_session_id for link in links}
    if not linked_ids <= planned_rows.keys():
        _fail('cutover_validation_failed', 'Legacy completion references a missing session')
    imported_ids = current_ids | linked_ids
    for row in planned_rows.values():
        if row.kind not in KNOWN_KINDS:
            _fail('unsupported_legacy_kind', 'A legacy session kind cannot be imported')
    now = datetime.now(UTC)
    marker = LegacyImportRun(key=MARKER_KEY, source_fingerprint=fingerprint, imported_at=now,
        report={}, undo_payload=None)
    session.add(marker)
    session.flush()
    version = CalendarVersion(number=1, parent_number=None, kind='legacy_import', actor='system',
                              reason='Imported source-faithful legacy planning state', created_at=now)
    session.add(version)
    session.flush()
    for table, entries in archive.items():
        for uid, payload, digest in entries:
            session.add(LegacyImportMap(import_id=marker.id, source_table=table, source_id=uid,
                                        target_kind='archive', target_id=None, payload=payload,
                                        payload_sha256=digest))
    today = _today(session)
    ordered = sorted((planned_rows[uid] for uid in imported_ids), key=lambda row: (row.date, row.kind, str(row.id)))
    slot_by_id: dict[uuid.UUID, int] = {}
    for _, same_rows in itertools.groupby(ordered, key=lambda row: (row.date, row.kind)):
        for slot, row in enumerate(same_rows):
            slot_by_id[row.id] = slot
    for row in ordered:
        fields = _session_fields(row, slot=slot_by_id[row.id], today=today)
        # Historical linked sessions stay visible; current membership remains exact.
        if row.id not in current_ids:
            fields['certainty'] = 'committed'
        revision = CalendarSessionRevision(session_uid=row.id, revision=1,
            calendar_version_number=1, deleted=row.id not in current_ids, **fields)
        session.add(revision)
        session.flush()
        source_payload, source_digest = next((payload, digest) for uid, payload, digest
                                             in archive['planned_sessions'] if uid == row.id)
        session.add(LegacyImportMap(import_id=marker.id, source_table='planned_sessions',
            source_id=row.id, target_kind='calendar_session', target_id=revision.id,
            payload=source_payload, payload_sha256=source_digest))
    for link in links:
        if (link.activity_id is None) == (link.manual_session_id is None):
            _fail('cutover_validation_failed', 'Legacy completion has an invalid subject')
        completion = SessionCompletion(session_uid=link.planned_session_id,
            activity_id=link.activity_id, manual_session_id=link.manual_session_id,
            strong_workout_id=None, status='unknown', match_method='explicit',
            updated_at=link.confirmed_at or now)
        session.add(completion)
        session.flush()
        payload = next(payload for uid, payload, _ in archive['completion_links'] if uid == link.id)
        digest = next(digest for uid, _, digest in archive['completion_links'] if uid == link.id)
        session.add(LegacyImportMap(import_id=marker.id, source_table='completion_links',
            source_id=link.id, target_kind='completion', target_id=completion.id,
            payload=payload, payload_sha256=digest))
    undo = revertible(session, latest(session))
    marker.undo_payload = {'revision_id': str(undo.id), 'before': _canonical(undo.payload.get('before', [])),
                           'after': _canonical(undo.payload.get('after', []))} if undo else None
    counts_after, hashes_after, _ = source_snapshot(session)
    if counts_before != counts_after or hashes_before != hashes_after:
        _fail('cutover_validation_failed', 'Legacy source rows changed during import')
    state.calendar_head_version = 1
    state.planning_authority = 'calendar'
    session.flush()
    recompute(session, 'calendar')
    session.flush()
    counts_after, hashes_after, _ = source_snapshot(session)
    if counts_before != counts_after or hashes_before != hashes_after:
        _fail('cutover_validation_failed', 'Legacy source rows changed during recompute')
    report: MigrationReport = {'key': MARKER_KEY, 'already_imported': False,
        'source_fingerprint': fingerprint,
        'counts': {**counts_before, 'calendar_sessions': len(imported_ids),
                   'completion_links_imported': len(links)},
        'calendar_head': state.calendar_head_version, 'undo_available': False,
        'errors': []}
    marker.report = dict(report)
    session.flush()
    return report


def migrate_legacy_state(session: Session, *, dry_run: bool) -> MigrationReport:
    """Import once, atomically; dry-run rolls back its savepoint and caller transaction."""
    session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': LOCK_ID})
    state = session.get(AppState, 1, with_for_update=True, populate_existing=True)
    if state is None:
        _fail('schema_not_ready', 'App state is missing', 409)
    savepoint = session.begin_nested()
    try:
        report = _import(session, state, dry_run=dry_run)
        if dry_run:
            savepoint.rollback()
        else:
            savepoint.commit()
        return report
    except Exception:
        savepoint.rollback()
        raise
