"""Versioned calendar writes and reads. Callers own the transaction."""
from __future__ import annotations

import math
import statistics
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import desc, func, select, text, update
from sqlalchemy.orm import Session

from app.api.core import current_profile, fail
from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.coach_v2_models import CoachProposal
from app.config import settings
from app.domain.cycle import opportunities
from app.metrics.engine import load_runs
from app.models import Activity, AppState, ManualSession
from app.services.calendar_structure import StructureError, expand_structure
from app.services.strength_routine import routine_occurrences
from app.strong_models import StrongWorkoutRow

LOCK_ID = 71382413
WRITE_FIELDS = frozenset({'local_date', 'slot', 'kind', 'recipe_id', 'custom', 'placeholder',
    'intent', 'planned_duration_s', 'planned_distance_m', 'structure', 'strength_slot_id',
    'notes', 'locked'})
REVISION_FIELDS = (*WRITE_FIELDS, 'legacy_unstructured', 'legacy_payload')
SUBJECTS = {'activity_id': Activity, 'strong_workout_id': StrongWorkoutRow,
            'manual_session_id': ManualSession}


def _today(session: Session, now: datetime | None = None) -> date:
    profile = current_profile(session)
    timezone = ZoneInfo(profile.timezone if profile else 'America/New_York')
    return (now or datetime.now(UTC)).astimezone(timezone).date()


def _lock(session: Session, expected_head: int | None = None) -> AppState:
    session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': LOCK_ID})
    state = session.get(AppState, 1, with_for_update=True, populate_existing=True)
    if state is None or state.planning_authority != 'calendar':
        fail('planning_not_active', 'Calendar planning is not active', 409)
    if expected_head is not None and state.calendar_head_version != expected_head:
        fail('calendar_head_moved', 'Calendar changed; reload before editing', 409)
    return state


def _head(session: Session) -> int:
    state = session.get(AppState, 1)
    return state.calendar_head_version if state else 0


def _check_version(session: Session, version: int) -> None:
    if version < 0 or version > _head(session):
        fail('calendar_version_not_found', 'Calendar version not found', 404)
    if version and session.scalar(select(CalendarVersion.id).where(CalendarVersion.number == version)) is None:
        fail('calendar_version_not_found', 'Calendar version not found', 404)


def _latest(session: Session, version: int) -> dict[uuid.UUID, CalendarSessionRevision]:
    if version == 0:
        return {}
    rows = session.scalars(select(CalendarSessionRevision)
        .where(CalendarSessionRevision.calendar_version_number <= version)
        .order_by(CalendarSessionRevision.session_uid,
                  desc(CalendarSessionRevision.calendar_version_number),
                  desc(CalendarSessionRevision.revision))
        .distinct(CalendarSessionRevision.session_uid)).all()
    return {row.session_uid: row for row in rows}


def _fields(row: CalendarSessionRevision) -> dict:
    return {field: getattr(row, field) for field in REVISION_FIELDS}


def _row_data(row: CalendarSessionRevision, today: date | None = None) -> dict:
    result = {'id': row.id, 'session_uid': row.session_uid,
        'revision': row.revision, 'calendar_version_number': row.calendar_version_number,
        'deleted': row.deleted, **_fields(row), 'is_original': row.revision == 1,
        'changed_by_version': row.calendar_version_number}
    result['certainty'] = ('committed' if row.local_date <= today + timedelta(days=6)
                           else 'provisional') if today else row.certainty
    return result


def state_at(session: Session, version: int) -> list[dict]:
    _check_version(session, version)
    today = _today(session)
    return [_row_data(row, today) for row in sorted(_latest(session, version).values(),
        key=lambda row: (row.local_date, row.slot, str(row.session_uid))) if not row.deleted]


def _completion_date(session: Session, row: SessionCompletion, planned: dict[uuid.UUID, dict]) -> date | None:
    for field, model in SUBJECTS.items():
        subject_id = getattr(row, field)
        if subject_id:
            subject = session.get(model, subject_id)
            return getattr(subject, 'local_date', getattr(subject, 'date', None)) if subject else None
    session_row = planned.get(row.session_uid)
    return session_row['local_date'] if session_row else None


def completion_data(session: Session, row: SessionCompletion, version: int | None = None) -> dict:
    planned = {item['session_uid']: item for item in state_at(session,
        _head(session) if version is None else version)}
    return {'id': row.id, 'session_uid': row.session_uid,
        'activity_id': row.activity_id, 'strong_workout_id': row.strong_workout_id,
        'manual_session_id': row.manual_session_id, 'status': row.status,
        'match_method': row.match_method, 'modification_reason': row.modification_reason,
        'reason_note': row.reason_note, 'version': row.version,
        'input_version': row.input_version, 'updated_at': row.updated_at,
        'local_date': _completion_date(session, row, planned)}


def _snapshot(row: CalendarSessionRevision | None) -> dict | None:
    if row is None or row.deleted:
        return None
    return _fields(row)


def _protected(session: Session, uid: uuid.UUID,
               current: CalendarSessionRevision | None,
               target: CalendarSessionRevision | None, today: date) -> bool:
    for row in (current, target):
        if row is not None and (row.local_date < today or row.locked):
            return True
    completion = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == uid))
    return bool(completion and (completion.status == 'skipped' or any(
        getattr(completion, key) is not None for key in SUBJECTS)))


def _inverse(session: Session, current_version: int, target_version: int) -> tuple[list[dict], list[uuid.UUID]]:
    current = _latest(session, current_version)
    target = _latest(session, target_version)
    today = _today(session)
    changes = []
    protected = []
    for uid in sorted(current.keys() | target.keys(), key=str):
        before, after = current.get(uid), target.get(uid)
        if _snapshot(before) == _snapshot(after):
            continue
        if _protected(session, uid, before, after, today):
            protected.append(uid)
        else:
            changes.append({'session_uid': uid, 'before': _row_data(before) if before and not before.deleted else None,
                'after': _row_data(after) if after and not after.deleted else None})
    return changes, protected


def calendar_diff(session: Session, from_version: int, to_version: int) -> dict:
    _check_version(session, from_version)
    _check_version(session, to_version)
    before, after = _latest(session, from_version), _latest(session, to_version)
    changes = []
    for uid in sorted(before.keys() | after.keys(), key=str):
        left, right = before.get(uid), after.get(uid)
        if _snapshot(left) != _snapshot(right):
            op = ('add' if left is None or left.deleted else
                  'delete' if right is None or right.deleted else
                  'move' if left.local_date != right.local_date else 'modify')
            changes.append({'session_uid': uid,
                'op': op,
                'before': _row_data(left) if left and not left.deleted else None,
                'after': _row_data(right) if right and not right.deleted else None})
    return {'changes': changes}


def calendar_view(session: Session, start: date, end: date, version: int | None = None) -> dict:
    if start > end:
        fail('invalid_date_window', 'Start must be on or before end')
    head = _head(session)
    requested = head if version is None else version
    _check_version(session, requested)
    all_head = state_at(session, head)
    selected = state_at(session, requested)
    in_range = [item for item in selected if start <= item['local_date'] <= end]
    planned = {item['session_uid']: item for item in selected}
    completions = []
    for row in session.scalars(select(SessionCompletion).order_by(SessionCompletion.updated_at, SessionCompletion.id)):
        local_date = _completion_date(session, row, planned)
        if local_date is not None and start <= local_date <= end:
            completions.append(completion_data(session, row, requested))
    undo = None
    if head:
        changed_number = session.scalar(select(func.max(CalendarSessionRevision.calendar_version_number))
            .where(CalendarSessionRevision.calendar_version_number <= head))
        latest_version = session.scalar(select(CalendarVersion).where(CalendarVersion.number == changed_number))
        if latest_version and latest_version.parent_number is not None and latest_version.kind != 'legacy_import':
            changes, protected = _inverse(session, head, latest_version.parent_number)
            if changes or protected:
                undo = {'target_version': latest_version.parent_number,
                        'eligible': bool(changes), 'protected_session_uids': protected}
    profile = current_profile(session)
    versions = session.scalars(select(CalendarVersion).where(CalendarVersion.number <= head)
        .order_by(desc(CalendarVersion.number)).limit(50)).all()
    return {'today': _today(session), 'timezone': profile.timezone if profile else 'America/New_York',
        'start': start, 'end': end, 'version': requested, 'head': head,
        'last_planned_date': max((item['local_date'] for item in all_head), default=None),
        'sessions': in_range, 'completions': completions,
        'versions': [{'number': row.number, 'kind': row.kind, 'actor': row.actor,
                      'created_at': row.created_at} for row in versions], 'undo': undo}


def _validate_fields(fields: dict, *, existing: dict | None = None,
                     legacy_unstructured: bool = False) -> dict:
    if not isinstance(fields, dict) or set(fields) - WRITE_FIELDS:
        fail('invalid_session_fields', 'Unexpected session field')
    result = {**(existing or {'slot': 0, 'recipe_id': None, 'custom': False,
        'placeholder': False, 'planned_duration_s': None, 'planned_distance_m': None,
        'structure': None, 'strength_slot_id': None, 'notes': None, 'locked': False}), **fields}
    local_date = result.get('local_date')
    if isinstance(local_date, str):
        try:
            local_date = date.fromisoformat(local_date)
        except ValueError:
            fail('invalid_session_fields', 'Invalid local date')
        result['local_date'] = local_date
    if type(local_date) is not date or type(result.get('slot')) is not int or result['slot'] < 0:
        fail('invalid_session_fields', 'Invalid date or slot')
    if result.get('kind') not in {'run', 'strength', 'cross', 'rest', 'mobility'}:
        fail('invalid_session_fields', 'Invalid session kind')
    if not isinstance(result.get('intent'), str) or not result['intent'].strip() or len(result['intent']) > 200:
        fail('invalid_session_fields', 'Intent must be 1–200 characters')
    for field in ('custom', 'placeholder', 'locked'):
        if type(result[field]) is not bool:
            fail('invalid_session_fields', 'Invalid session flag')
    for field in ('planned_duration_s', 'planned_distance_m'):
        value = result.get(field)
        if value is not None and (type(value) is not int or value <= 0):
            fail('invalid_session_fields', 'Duration and distance must be positive integers')
    recipe = result.get('recipe_id')
    if recipe is not None and (not isinstance(recipe, str) or recipe not in
        {f'REC{index:03d}' for index in range(1, 11)}):
        fail('invalid_session_fields', 'Unknown recipe ID')
    if result.get('notes') is not None and not isinstance(result['notes'], str):
        fail('invalid_session_fields', 'Notes must be text')
    if result.get('kind') == 'run' and not (recipe or result['custom'] or result['placeholder'] or legacy_unstructured):
        fail('invalid_session_fields', 'Run needs a recipe, custom flag, or placeholder')
    if result['placeholder'] and (result.get('recipe_id') is not None or result['custom']):
        fail('invalid_session_fields', 'Placeholder cannot have a recipe or custom flag')
    structure = result.get('structure')
    if structure is not None:
        try:
            expand_structure(structure)
        except StructureError:
            fail('invalid_structure', 'Invalid session structure')
    slot_id = result.get('strength_slot_id')
    if isinstance(slot_id, str):
        try:
            result['strength_slot_id'] = uuid.UUID(slot_id)
        except ValueError:
            fail('invalid_session_fields', 'Invalid strength slot ID')
    return result


def _append(session: Session, *, uid: uuid.UUID, number: int, revision: int,
            fields: dict, deleted: bool = False, today: date | None = None) -> CalendarSessionRevision:
    row = CalendarSessionRevision(session_uid=uid, revision=revision, calendar_version_number=number,
        deleted=deleted, certainty='committed' if fields['local_date'] <= (today or _today(session)) + timedelta(days=6)
            else 'provisional', **fields)
    session.add(row)
    return row


def _version_row(session: Session, state: AppState, *, kind: str, actor: str,
                 reason: str | None = None, proposal_id: uuid.UUID | None = None,
                 block_version_id: uuid.UUID | None = None,
                 restored_from_number: int | None = None) -> CalendarVersion:
    head = state.calendar_head_version
    row = CalendarVersion(number=head + 1, parent_number=head if head else None,
        kind=kind, actor=actor, reason=reason, proposal_id=proposal_id,
        block_version_id=block_version_id, restored_from_number=restored_from_number)
    session.add(row)
    state.calendar_head_version = head + 1
    return row


def _stale_proposals(session: Session) -> list[uuid.UUID]:
    ids = session.scalars(select(CoachProposal.id).where(CoachProposal.status == 'pending')
        .order_by(CoachProposal.id)).all()
    if ids:
        session.execute(update(CoachProposal).where(CoachProposal.id.in_(ids)).values(status='stale'))
    return list(ids)


def apply_edits(session: Session, expected_head: int, edits: list[dict], reason: str | None,
                *, kind: str = 'manual_edit', actor: str = 'user',
                proposal_id: uuid.UUID | None = None,
                block_version_id: uuid.UUID | None = None) -> dict:
    state = _lock(session, expected_head)
    if not isinstance(edits, list) or not edits:
        fail('edit_no_change', 'No calendar changes supplied')
    current = _latest(session, expected_head)
    today = _today(session)
    prepared = []
    seen = set()
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) - {'op', 'session_uid', 'fields'}:
            fail('invalid_calendar_edit', 'Invalid calendar edit')
        op = edit.get('op')
        uid = edit.get('session_uid')
        if op == 'add':
            if uid is not None:
                fail('invalid_calendar_edit', 'New session UID is server assigned')
            uid = uuid.uuid4()
            previous = None
        else:
            try:
                uid = uuid.UUID(str(uid))
            except (ValueError, TypeError):
                fail('invalid_calendar_edit', 'Invalid session UID')
            previous = current.get(uid)
            if previous is None or previous.deleted:
                fail('session_not_found', 'Session not found', 404)
        if uid in seen:
            fail('duplicate_session_edit', 'Session edited more than once')
        seen.add(uid)
        if op != 'add' and _protected(session, uid, previous, None, today):
            fail('protected_session', 'Historical, locked, or completed session cannot change')
        if op == 'delete':
            if edit.get('fields') not in (None, {}):
                fail('invalid_calendar_edit', 'Delete cannot contain fields')
            assert previous is not None
            fields = _fields(previous)
            deleted = True
        elif op in {'add', 'modify', 'move'}:
            supplied = edit.get('fields')
            if not isinstance(supplied, dict):
                fail('invalid_calendar_edit', 'Fields required')
            if op == 'move' and 'local_date' not in supplied:
                fail('invalid_calendar_edit', 'Move requires local date')
            base = _fields(previous) if previous else None
            if base:
                base = {key: base[key] for key in WRITE_FIELDS}
            fields = _validate_fields(supplied, existing=base,
                legacy_unstructured=bool(previous and previous.legacy_unstructured))
            if previous and fields == base:
                fail('edit_no_change', 'Session is unchanged')
            deleted = False
            if fields['local_date'] < today:
                fail('protected_session', 'Historical session cannot change')
        else:
            fail('invalid_calendar_edit', 'Unknown calendar edit')
        if previous:
            fields['legacy_unstructured'] = previous.legacy_unstructured
            fields['legacy_payload'] = previous.legacy_payload
        else:
            fields['legacy_unstructured'] = False
            fields['legacy_payload'] = None
        prepared.append((uid, previous.revision + 1 if previous else 1, fields, deleted))
    version = _version_row(session, state, kind=kind, actor=actor, reason=reason,
        proposal_id=proposal_id, block_version_id=block_version_id)
    session.flush()
    for uid, revision, fields, deleted in prepared:
        _append(session, uid=uid, number=version.number, revision=revision,
                fields=fields, deleted=deleted, today=today)
    stale = _stale_proposals(session)
    session.flush()
    return {'version': version.number, 'kind': kind, 'stale_proposals': stale,
            'preserved_session_uids': []}


def rollback_calendar(session: Session, expected_head: int, to_version: int,
                      reason: str | None) -> dict:
    state = _lock(session, expected_head)
    _check_version(session, to_version)
    if to_version >= expected_head:
        fail('rollback_no_change', 'No earlier version to restore')
    changes, protected = _inverse(session, expected_head, to_version)
    if not changes:
        fail('rollback_no_change', 'No eligible calendar change to restore')
    if protected and not reason:
        fail('rollback_reason_required', 'Reason required when preserving protected sessions')
    current, target = _latest(session, expected_head), _latest(session, to_version)
    version = _version_row(session, state, kind='rollback', actor='user', reason=reason,
        restored_from_number=to_version)
    session.flush()
    for item in changes:
        uid = item['session_uid']
        source = target.get(uid)
        existing = current.get(uid)
        if source is not None:
            fields = _fields(source)
        elif existing is not None:
            fields = _fields(existing)
        else:
            continue
        _append(session, uid=uid, number=version.number,
            revision=existing.revision + 1 if existing else 1,
            fields=fields, deleted=(source is None or source.deleted))
    stale = _stale_proposals(session)
    session.flush()
    return {'version': version.number, 'kind': 'rollback', 'stale_proposals': stale,
            'preserved_session_uids': protected}


def _rounded_nearest_300(value: float) -> int:
    return max(300, int(math.floor(value / 300 + .5) * 300))


def bootstrap_plan(anchor_date: date, start_date: date, today: date,
                   run_history: list[dict], strength_occurrences: list[dict]) -> list[dict]:
    end = start_date + timedelta(days=13)
    history = []
    for ordinal, row in enumerate(run_history):
        timer = row.get('timer_s')
        local_date = row.get('local_date') or row.get('date')
        if isinstance(local_date, str):
            try:
                local_date = date.fromisoformat(local_date)
            except ValueError:
                continue
        if (not isinstance(local_date, date) or not isinstance(timer, (int, float))
            or isinstance(timer, bool) or not math.isfinite(timer) or timer <= 0
            or not today - timedelta(days=56) <= local_date < today
            or row.get('resolution_state', 'resolved') != 'resolved'
            or row.get('excluded', False)):
            continue
        start_at = row.get('start_at')
        history.append((local_date, float(timer), start_at if isinstance(start_at, datetime) else None, ordinal))
    history.sort(key=lambda item: (item[0], item[2] or datetime.min.replace(tzinfo=UTC), item[3]))
    classified: list[tuple[float, bool]] = []
    for index, (candidate_day, timer, _, _) in enumerate(history):
        prior = [value for prior_day, value, _, _ in history[:index]
                 if candidate_day - timedelta(days=28) <= prior_day <= candidate_day]
        is_long = len(prior) >= 4 and timer >= 1.33 * statistics.median(prior)
        classified.append((timer, is_long))
    recent = [(timer, is_long) for (local_date, _, _, _), (timer, is_long) in zip(history, classified)
              if local_date >= today - timedelta(days=28)]
    easy_samples = [timer for timer, is_long in recent if not is_long]
    easy = _rounded_nearest_300(statistics.median(easy_samples)) if len(easy_samples) >= 3 else 1800
    long_samples = [timer for timer, is_long in recent if is_long]
    long_duration = max(300, int(max(long_samples) // 300 * 300)) if long_samples else _rounded_nearest_300(1.33 * easy)
    runs = [date.fromisoformat(item['date']) for item in opportunities(start_date, end, anchor_date)]
    weeks: dict[date, list[date]] = defaultdict(list)
    for run_day in runs:
        weeks[run_day - timedelta(days=run_day.weekday())].append(run_day)
    long_days = set()
    quality_days = set()
    for days in weeks.values():
        weekend = [day for day in days if day.weekday() >= 5]
        long_day = max(weekend or days)
        long_days.add(long_day)
        quality = [day for day in days if day <= long_day - timedelta(days=2)]
        if quality:
            quality_days.add(min(quality))
    planned = []
    for run_day in runs:
        is_quality = run_day in quality_days
        is_long = run_day in long_days
        planned.append({'local_date': run_day, 'slot': 0, 'kind': 'run',
            'recipe_id': None if is_quality else ('REC002' if is_long else 'REC001'),
            'custom': False, 'placeholder': is_quality,
            'intent': ('Quality slot — selected at first review' if is_quality else
                       'Long aerobic run' if is_long else 'Easy run'),
            'planned_duration_s': easy if is_quality or not is_long else long_duration,
            'planned_distance_m': None, 'structure': None, 'strength_slot_id': None,
            'notes': None, 'locked': False, 'legacy_unstructured': False,
            'legacy_payload': None})
    for occurrence in strength_occurrences:
        occurrence_day = occurrence.get('date')
        if isinstance(occurrence_day, str):
            occurrence_day = date.fromisoformat(occurrence_day)
        if not isinstance(occurrence_day, date) or not start_date <= occurrence_day <= end:
            continue
        kind = occurrence.get('kind')
        if kind not in {'strength', 'mobility'}:
            continue
        slot_id = occurrence.get('strength_slot_id') if kind == 'strength' else None
        planned.append({'local_date': occurrence_day, 'slot': 1 if kind == 'strength' else 2,
            'kind': kind, 'recipe_id': None, 'custom': False, 'placeholder': False,
            'intent': occurrence.get('label') or ('Strength' if kind == 'strength' else 'Mobility'),
            'planned_duration_s': None, 'planned_distance_m': None, 'structure': None,
            'strength_slot_id': slot_id, 'notes': None, 'locked': False,
            'legacy_unstructured': False,
            'legacy_payload': {'optional': True} if occurrence.get('optional') else None})
    return sorted(planned, key=lambda item: (item['local_date'], item['slot'], item['kind']))


def _bootstrap_locked(session: Session, state: AppState, *, anchor_date: date,
                      start_date: date, today: date) -> dict:
    if state.calendar_head_version:
        fail('calendar_exists', 'Calendar already has a version', 409)
    profile = current_profile(session)
    if (profile is None or not profile.anchor_confirmed or profile.cycle_anchor != anchor_date
        or not profile.strength_days_confirmed):
        fail('bootstrap_profile_unconfirmed', 'Confirmed anchor and strength schedule required')
    history = [{'local_date': row.local_date, 'timer_s': row.timer_s, 'start_at': row.start_at}
               for row in load_runs(session, today - timedelta(days=56), today)]
    recurrence = routine_occurrences(session, start_date, start_date + timedelta(days=13))
    planned = bootstrap_plan(anchor_date, start_date, today, history, recurrence)
    version = _version_row(session, state, kind='bootstrap', actor='system')
    session.flush()
    for fields in planned:
        _append(session, uid=uuid.uuid4(), number=version.number,
            revision=1, fields=fields, today=today)
    stale = _stale_proposals(session)
    session.flush()
    return {'version': version.number, 'kind': 'bootstrap',
            'stale_proposals': stale, 'preserved_session_uids': []}


def write_bootstrap(session: Session, anchor_date: date, start_date: date) -> dict:
    state = _lock(session)
    if start_date < _today(session):
        fail('protected_session', 'Ordinary bootstrap cannot create historical sessions')
    return _bootstrap_locked(session, state, anchor_date=anchor_date,
        start_date=start_date, today=_today(session))


def seed_demo_calendar(session: Session, *, anchor_date: date, start_date: date,
                       now: datetime, history_edits: list[dict]) -> dict:
    if settings.app_mode not in {'demo', 'test'}:
        fail('demo_seed_forbidden', 'Demo seeding is unavailable', 403)
    state = _lock(session)
    if state.calendar_head_version:
        fail('calendar_exists', 'Calendar already has a version', 409)
    seen = set()
    prepared = []
    for edit in history_edits:
        if not isinstance(edit, dict) or set(edit) != {'op', 'session_uid', 'fields'} or edit['op'] != 'add':
            fail('invalid_demo_history', 'Demo history permits explicit add only')
        try:
            uid = uuid.UUID(str(edit['session_uid']))
        except (ValueError, TypeError):
            fail('invalid_demo_history', 'Invalid demo session UID')
        if uid.int == 0 or uid in seen:
            fail('invalid_demo_history', 'Demo session UID must be unique and nonzero')
        seen.add(uid)
        prepared.append((uid, _validate_fields(edit['fields'])))
    result = _bootstrap_locked(session, state, anchor_date=anchor_date,
        start_date=start_date, today=_today(session, now))
    if not prepared:
        return result
    existing = _latest(session, state.calendar_head_version)
    if seen & existing.keys():
        fail('invalid_demo_history', 'Demo session UID already exists')
    version = _version_row(session, state, kind='manual_edit', actor='system',
        reason='synthetic history fixture')
    session.flush()
    for uid, fields in prepared:
        _append(session, uid=uid, number=version.number, revision=1,
            fields={**fields, 'legacy_unstructured': False, 'legacy_payload': None},
            today=_today(session, now))
    session.flush()
    return {'version': version.number, 'kind': 'manual_edit',
            'stale_proposals': result['stale_proposals'], 'preserved_session_uids': []}


def put_completion(session: Session, session_uid: uuid.UUID, body: dict,
                   *, assess: Callable[[Session, uuid.UUID], None]) -> SessionCompletion:
    if not callable(assess):
        raise RuntimeError('completion_assessor_missing')
    _lock(session)
    if not isinstance(body, dict) or set(body) - {'expected_version', 'activity_id',
        'strong_workout_id', 'manual_session_id', 'status', 'modification_reason', 'reason_note'}:
        fail('invalid_completion', 'Invalid completion fields')
    subjects = {}
    for key in SUBJECTS:
        value = body.get(key)
        if value is not None:
            try:
                value = uuid.UUID(str(value))
            except (TypeError, ValueError):
                fail('invalid_completion', 'Invalid completion subject')
        subjects[key] = value
    count = sum(value is not None for value in subjects.values())
    if count > 1:
        fail('invalid_completion', 'At most one subject is allowed')
    if count and 'status' in body:
        fail('invalid_completion', 'Linked completion status is assessed')
    if not count and body.get('status') not in {'skipped', 'unknown'}:
        fail('invalid_completion', 'Unlinked completion must be skipped or unknown')
    if body.get('modification_reason') not in {None, 'symptom_onset', 'fatigue', 'illness',
        'schedule', 'weather', 'equipment', 'other'}:
        fail('invalid_completion', 'Invalid modification reason')
    if body.get('reason_note') is not None and not isinstance(body['reason_note'], str):
        fail('invalid_completion', 'Invalid reason note')
    existing = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == session_uid))
    expected = body.get('expected_version', 0)
    if existing is None and expected not in (None, 0):
        fail('version_conflict', 'Completion changed; reload before editing', 409)
    if existing is not None and expected != existing.version:
        fail('version_conflict', 'Completion changed; reload before editing', 409)
    for field, value in subjects.items():
        if value is None:
            continue
        if session.get(SUBJECTS[field], value) is None:
            fail('completion_subject_not_found', 'Completion subject not found', 404)
        used = session.scalar(select(SessionCompletion.id).where(getattr(SessionCompletion, field) == value))
        if used is not None and (existing is None or used != existing.id):
            fail('subject_already_linked', 'Subject already linked', 409)
    now = datetime.now(UTC)
    planned = _latest(session, _head(session)).get(session_uid)
    actual_date = None
    for field, value in subjects.items():
        if value is not None:
            subject = session.get(SUBJECTS[field], value)
            actual_date = getattr(subject, 'local_date', getattr(subject, 'date', None))
    moved = bool(planned and actual_date and planned.local_date != actual_date)
    method = ('confirmed_move' if moved else 'explicit') if count else 'user_marked'
    status = 'moved' if moved else ('unknown' if count else body['status'])
    association = (subjects, body.get('modification_reason'), body.get('reason_note'))
    if existing is None:
        row = SessionCompletion(session_uid=session_uid, **subjects, status=status,
            match_method=method, modification_reason=body.get('modification_reason'),
            reason_note=body.get('reason_note'), version=1, input_version=1, updated_at=now)
        session.add(row)
    else:
        row = existing
        old = ({key: getattr(row, key) for key in SUBJECTS}, row.modification_reason, row.reason_note)
        if old != association or row.match_method != method or (not count and row.status != status):
            row.input_version += 1
            row.version += 1
        for key, value in subjects.items():
            setattr(row, key, value)
        unchanged_input = old == association and row.match_method == method
        row.status, row.match_method = (row.status if unchanged_input and count else status), method
        row.modification_reason = body.get('modification_reason')
        row.reason_note = body.get('reason_note')
        row.updated_at = now
    session.flush()
    if count:
        assess(session, session_uid)
        session.flush()
        if moved:
            row.status = 'moved'
    session.flush()
    return row
