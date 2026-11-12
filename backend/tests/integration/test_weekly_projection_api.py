"""Endpoint smoke test on the guarded synthetic calendar database."""
from __future__ import annotations

from datetime import date

from test_calendar_api import _bootstrap, calendar_fixture  # noqa: F401

from app.services import calendar


def test_weekly_projection_uses_accepted_head(calendar_fixture):  # noqa: F811
    client, _, _ = calendar_fixture
    response = client.get('/api/v1/calendar/weekly-projection')
    assert response.status_code == 200, response.text
    empty = response.json()['data']
    assert empty['week_start'] == '2026-11-16'
    assert empty['week_end'] == '2026-11-22'
    assert empty['plan_available'] is False
    assert empty['remaining_runs'] == 0

    _bootstrap(client)
    response = client.get('/api/v1/calendar/weekly-projection')
    assert response.status_code == 200, response.text
    result = response.json()['data']
    assert result['calendar_version'] == 1
    assert result['plan_available'] is True
    assert result['plan_through'] == '2026-11-28'
    assert result['remaining_runs'] == 4
    assert result['projected_distance_m'] == result['actual_distance_m'] + result['remaining_distance_m']


def test_sunday_week_boundary(calendar_fixture, monkeypatch):  # noqa: F811
    client, _, _ = calendar_fixture
    monkeypatch.setattr(calendar, '_today', lambda session, now=None: date(2026, 11, 22))
    response = client.get('/api/v1/calendar/weekly-projection')
    assert response.status_code == 200, response.text
    result = response.json()['data']
    assert result['today'] == '2026-11-22'
    assert result['week_start'] == '2026-11-16'
    assert result['week_end'] == '2026-11-22'


def test_projection_totals_and_missing_evidence(calendar_fixture, monkeypatch):  # noqa: F811
    import uuid
    from datetime import UTC, datetime

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
    from app.models import Activity, ActivityAnnotation, AppState, ManualSession

    client, connection, _ = calendar_fixture
    monkeypatch.setattr(calendar, '_today', lambda session, now=None: date(2030, 1, 9))
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        state = session.get(AppState, 1)
        state.calendar_head_version = 1
        session.add(CalendarVersion(number=1, kind='manual_edit', actor='user'))
        activities = {}
        for name, day, distance, timer, resolution in [
            ('prior', 5, 4000, 2000, 'resolved'),
            ('first', 7, 5000, 2500, 'resolved'),
            ('second', 9, 6000, 3000, 'resolved'),
            ('zero', 9, 0, 60, 'resolved'),
            ('excluded', 8, 9000, 3000, 'resolved'),
            ('unresolved', 8, 9000, 3000, 'unresolved'),
        ]:
            activity = Activity(start_at=datetime(2030, 1, day, 12, tzinfo=UTC),
                original_start=f'2030-01-{day:02d}T12:00:00Z', local_date=date(2030, 1, day),
                sport='running', distance_m=distance, timer_s=timer,
                resolution_state=resolution, field_provenance={})
            session.add(activity)
            session.flush()
            activities[name] = activity
        session.add(ActivityAnnotation(activity_id=activities['excluded'].id,
            version=1, excluded=True))
        ids = {}
        for name, day, distance, duration in [
            ('past', 7, 2000, None), ('today', 9, 6000, None),
            ('skip', 10, 1000, None), ('friday', 11, 3000, None),
            ('moved', 12, 2000, None), ('sunday', 13, None, 600),
        ]:
            uid = uuid.uuid4()
            ids[name] = uid
            session.add(CalendarSessionRevision(session_uid=uid, revision=1,
                calendar_version_number=1, deleted=False, local_date=date(2030, 1, day),
                slot=0, kind='run', custom=True, placeholder=False, locked=False,
                legacy_unstructured=False, intent=name, certainty='committed',
                planned_distance_m=distance, planned_duration_s=duration))
        session.add_all([
            SessionCompletion(session_uid=ids['today'], activity_id=activities['second'].id,
                status='completed_as_planned', match_method='explicit', updated_at=datetime.now(UTC)),
            SessionCompletion(session_uid=ids['skip'], status='skipped', match_method='user_marked',
                updated_at=datetime.now(UTC)),
            SessionCompletion(session_uid=ids['moved'], activity_id=activities['prior'].id,
                status='moved', match_method='confirmed_move', updated_at=datetime.now(UTC)),
            ManualSession(date=date(2030, 1, 8), kind='run', duration_s=1800),
            ManualSession(date=date(2030, 1, 9), kind='run', duration_s=3000,
                linked_activity_id=activities['second'].id),
        ])
        session.commit()
        before = session.scalar(select(AppState.data_revision).where(AppState.id == 1))
    response = client.get('/api/v1/calendar/weekly-projection')
    assert response.status_code == 200, response.text
    result = response.json()['data']
    assert result['week_start'] == '2030-01-07' and result['week_end'] == '2030-01-13'
    assert result['actual_distance_m'] == 11000
    assert result['remaining_distance_m'] == 4200
    assert result['projected_distance_m'] == 15200
    assert result['actual_runs'] == 4
    assert result['remaining_runs'] == 2
    assert result['estimated_runs'] == 1
    assert result['missing_actual_runs'] == 1
    assert result['missing_planned_runs'] == 0
    assert result['unrecorded_past_runs'] == 1
    assert result['pace_mps'] == 2
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        state = session.get(AppState, 1)
        assert state.calendar_head_version == 1 and state.data_revision == before
