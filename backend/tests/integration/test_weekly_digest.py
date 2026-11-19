import json
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_calendar_api import calendar_fixture  # noqa: F401

from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.metric_models import MetricResult
from app.metrics import intervals, planned_actual
from app.models import Activity, ActivityAnnotation, AppState, ManualSession, RawObject, SourceAccount, SourceRecord
from app.services import calendar
from app.services.weekly_digest import load_week, weekly_digest
from app.strong_models import StrongWorkoutRow


def _activity(session, day, timer, distance, hour=12):
    start = datetime(2030, 1, day, hour, tzinfo=UTC)
    row = Activity(start_at=start, original_start=start.isoformat(), local_date=start.date(),
        sport='running', timer_s=timer, distance_m=distance, canonical_revision=1,
        resolution_state='resolved', field_provenance={})
    session.add(row)
    session.flush()
    return row


def _revision(session, uid, version, revision, day, kind, *, intent, recipe=None,
              duration=None, distance=None, deleted=False):
    session.add(CalendarSessionRevision(session_uid=uid, revision=revision, calendar_version_number=version,
        deleted=deleted, local_date=date(2030, 1, day), slot=0, kind=kind, recipe_id=recipe, custom=recipe is None,
        placeholder=False, locked=False, legacy_unstructured=False, intent=intent, certainty='committed',
        planned_duration_s=duration, planned_distance_m=distance))


def _strong(session, day, duration_s):
    tag = uuid.uuid4().hex
    account = SourceAccount(provider='strong', account_scope=tag)
    raw = RawObject(sha256=tag * 2, relative_path=tag, byte_size=1, media_type='text/csv')
    session.add_all([account, raw])
    session.flush()
    record = SourceRecord(source_account_id=account.id, raw_object_id=raw.id, source_identity=tag,
        payload_hash=tag * 2, fetched_at=datetime.now(UTC), parser_version='t', source_kind='strong_csv')
    session.add(record)
    session.flush()
    row = StrongWorkoutRow(source_account_id=account.id, source_identity=tag, source_record_id=record.id,
        raw_object_id=raw.id, payload_hash=tag * 2, local_date=date(2030, 1, day),
        local_start=f'2030-01-{day:02d}T12:00:00', workout_name='w', duration_s=duration_s, sets=[], row_count=0)
    session.add(row)
    session.flush()
    return row


def _metric(session, metric_id, version, subject_type, key, value):
    session.add(MetricResult(metric_id=metric_id, method_version=version, subject_type=subject_type, subject_key=key,
        status='available', value=value, reason_codes=[], quality_flags=[], source_refs={}, anchor_keys=[],
        config_hash='c' * 64, dependency_hash='d' * 64, calculated_at=datetime.now(UTC),
        timezone='America/New_York', is_current=True))


def _stored_counts(session):
    return (session.scalar(select(func.count()).select_from(SessionCompletion)),
            session.scalar(select(func.count()).select_from(MetricResult)),
            session.scalar(select(AppState.data_revision).where(AppState.id == 1)))


def _keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def test_load_week_reads_stored_rows_without_writes(calendar_fixture, monkeypatch):  # noqa: F811
    _, connection, _ = calendar_fixture
    week_start, today = date(2030, 1, 7), date(2030, 1, 9)
    monkeypatch.setattr(calendar, 'calendar_today', lambda session, now=None: today)
    uid = {name: uuid.uuid4() for name in 'ABCDEKRMH'}
    component = {'name': 'duration_ratio', 'value': 0.8, 'status': 'partially_met'}
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        state = session.get(AppState, 1)
        assert state is not None
        state.calendar_head_version = 2
        session.add_all([CalendarVersion(number=1, kind='manual_edit', actor='user'),
                         CalendarVersion(number=2, kind='manual_edit', actor='user', parent_number=1)])
        session.flush()
        run_a = _activity(session, 7, 1800, 3600)
        run_b = _activity(session, 8, 2400, 4800)
        unlinked = _activity(session, 7, 600, 1200, hour=20)
        before = _activity(session, 6, 1500, 3000)
        excluded = _activity(session, 8, 900, 5000, hour=18)
        session.add(ActivityAnnotation(activity_id=excluded.id, version=1, excluded=True))
        _revision(session, uid['A'], 1, 1, 7, 'run', intent='Long run', recipe='REC002', duration=1800)
        _revision(session, uid['B'], 1, 1, 8, 'run', intent='Intervals', recipe='REC003', duration=3000)
        _revision(session, uid['B'], 2, 2, 8, 'run', intent='Intervals', recipe='REC003', duration=3000, distance=8000)
        _revision(session, uid['C'], 1, 1, 8, 'strength', intent='Strength')
        _revision(session, uid['D'], 1, 1, 9, 'run', intent='Long run', duration=5400)
        _revision(session, uid['E'], 1, 1, 12, 'run', intent='Easy run', duration=3600)
        _revision(session, uid['K'], 1, 1, 11, 'run', intent='Easy run', duration=1500)
        _revision(session, uid['R'], 1, 1, 7, 'rest', intent='Rest')
        _revision(session, uid['M'], 1, 1, 7, 'mobility', intent='Mobility')
        _revision(session, uid['H'], 1, 1, 10, 'run', intent='Easy run')
        _revision(session, uid['H'], 2, 2, 10, 'run', intent='Easy run', deleted=True)
        lift = _strong(session, 8, 3000)
        cross = ManualSession(date=date(2030, 1, 8), kind='cross', duration_s=1200)
        updated = datetime.now(UTC)
        session.add_all([
            SessionCompletion(session_uid=uid['A'], activity_id=run_a.id, status='completed_as_planned',
                match_method='explicit', updated_at=updated),
            SessionCompletion(session_uid=uid['B'], activity_id=run_b.id, status='completed_modified',
                match_method='explicit', reason_note='private completion', updated_at=updated),
            SessionCompletion(session_uid=uid['C'], strong_workout_id=lift.id, status='completed_as_planned',
                match_method='explicit', updated_at=updated),
            SessionCompletion(session_uid=uid['K'], activity_id=before.id, status='moved',
                match_method='confirmed_move', updated_at=updated),
            ManualSession(date=week_start, kind='run', duration_s=1700, linked_activity_id=run_a.id, note='private manual'),
            cross,
        ])
        _metric(session, planned_actual.METRIC_ID, planned_actual.METHOD_VERSION, 'session', str(uid['B']),
                {'components': [component]})
        _metric(session, intervals.METRIC_ID, intervals.METHOD_VERSION, 'activity', str(run_b.id),
                {'n_planned': 6, 'n_completed': 4, 'reps': []})
        session.flush()
        unplanned_ids = {str(unlinked.id), str(cross.id)}
        session.commit()
        counts = _stored_counts(session)

    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        week = load_week(session, week_start, today=today)
        assert weekly_digest(session, None) == week
        assert _stored_counts(session) == counts

    assert week['plan_available'] is True
    assert week['calendar_version'] == 2
    assert week['days_elapsed'] == 3
    assert week['timezone'] == 'America/New_York'
    rows = {row['session_uid']: row for row in week['sessions']}
    assert {key: row['outcome'] for key, row in rows.items()} == {str(uid[name]): outcome for name, outcome in {
        'A': 'completed', 'M': 'not_recorded', 'B': 'modified', 'C': 'completed', 'D': 'planned',
        'K': 'moved', 'E': 'planned'}.items()}
    dates = [row['local_date'] for row in week['sessions']]
    assert dates == sorted(dates)
    assert rows[str(uid['B'])]['changed'] is True
    assert rows[str(uid['A'])]['changed'] is False

    totals = week['totals']
    assert {k: v for k, v in totals['sessions'].items() if k != 'by_outcome'} == {
        'planned': 6, 'planned_to_date': 4, 'done': 4, 'removed': 1, 'unplanned': 2}
    assert {k: v for k, v in totals['sessions']['by_outcome'].items() if v} == {
        'completed': 2, 'modified': 1, 'moved': 1, 'planned': 2}
    assert totals['by_kind'] == {
        'run': {'planned': 5, 'planned_to_date': 3, 'done': 3},
        'strength': {'planned': 1, 'planned_to_date': 1, 'done': 1},
        'cross': {'planned': 0, 'planned_to_date': 0, 'done': 0},
        'mobility': {'planned': 1, 'planned_to_date': 1, 'done': 0},
    }
    assert totals['time'] == {'planned_s': 15300.0, 'planned_to_date_s': 10200.0, 'planned_unknown': 1,
        'actual_s': 9000.0, 'actual_unknown': 0, 'unplanned_s': 1800.0}
    assert totals['run_distance'] == {'planned_m': 32600.0, 'planned_to_date_m': 22400.0, 'planned_estimated': 4,
        'planned_unknown': 0, 'actual_m': 9600.0, 'actual_unknown': 0}
    assert {k: v for k, v in totals['key_sessions'].items() if k != 'by_outcome'} == {
        'planned': 3, 'planned_to_date': 3, 'done': 2}
    execution_a = rows[str(uid['A'])]['execution']
    assert execution_a['assessment_status'] is None
    assert execution_a['reason_codes'] == ['ASSESSMENT_MISSING']
    assert rows[str(uid['B'])]['execution'] == {'assessment_status': 'available', 'reason_codes': [],
        'quality_flags': [], 'components': [component], 'reps_planned': 6, 'reps_completed': 4}
    assert rows[str(uid['D'])]['execution'] is None
    moved = rows[str(uid['K'])]['actual']
    assert moved['local_date'] == '2030-01-06'
    assert moved['subject'] == 'activity'
    assert {row['id'] for row in week['unplanned']} == unplanned_ids
    assert 'private' not in json.dumps(week, default=str)
    forbidden = ('note', 'stream', 'gps', 'latitude', 'longitude', 'coordinate', 'vo2max', 'readiness')
    assert not any(term in key for key in _keys(week) for term in forbidden)
