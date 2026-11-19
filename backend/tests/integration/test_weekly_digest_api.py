"""Weekly digest endpoint checks on the guarded synthetic calendar database."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_calendar_api import _bootstrap, calendar_fixture  # noqa: F401

from app.calendar_models import SessionCompletion
from app.metric_models import MetricResult
from app.models import AppState

ROUTE = '/api/v1/calendar/weekly-digest'


def test_digest_defaults_to_current_week_with_envelope(calendar_fixture):  # noqa: F811
    client, _, _ = calendar_fixture
    response = client.get(ROUTE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert {'schema_version', 'data_revision', 'mode', 'data'} <= body.keys()
    week = body['data']
    assert week['schema'] == 'weekly_digest.v1'
    assert week['week_start'] == '2026-11-16'
    assert week['week_end'] == '2026-11-22'
    assert week['plan_available'] is False
    assert week['sessions'] == []
    assert week['days_elapsed'] == 1


def test_digest_reports_planned_sessions_after_bootstrap(calendar_fixture):  # noqa: F811
    client, _, _ = calendar_fixture
    _bootstrap(client)

    response = client.get(ROUTE)
    assert response.status_code == 200, response.text
    week = response.json()['data']
    assert week['plan_available'] is True
    assert week['calendar_version'] == 1
    totals = week['totals']['sessions']
    headline = [row for row in week['sessions'] if row['kind'] in ('run', 'strength', 'cross')]
    assert totals['planned'] == len(headline) > 0
    assert sum(totals['by_outcome'].values()) == totals['planned']
    outcomes = {'completed', 'modified', 'partial', 'moved', 'missed', 'recorded', 'not_recorded', 'planned'}
    assert {row['outcome'] for row in week['sessions']} <= outcomes

    future = client.get(ROUTE, params={'week_start': '2026-11-23'})
    assert future.status_code == 200, future.text
    assert future.json()['data']['days_elapsed'] == 0

    past = client.get(ROUTE, params={'week_start': '2026-11-09'})
    assert past.status_code == 200, past.text
    assert past.json()['data']['days_elapsed'] == 7
    assert past.json()['data']['week_end'] == '2026-11-15'


def test_digest_rejects_non_monday_and_bad_dates(calendar_fixture):  # noqa: F811
    client, _, _ = calendar_fixture
    for week_start, code in [('2026-11-17', 'invalid_week_start'), ('not-a-date', 'validation_error')]:
        response = client.get(ROUTE, params={'week_start': week_start})
        assert response.status_code == 422, response.text
        assert response.json()['error']['code'] == code


def _stored_state(connection):
    with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
        state = session.get(AppState, 1)
        assert state is not None
        return (session.scalar(select(func.count()).select_from(SessionCompletion)),
                session.scalar(select(func.count()).select_from(MetricResult)),
                state.data_revision, state.calendar_head_version)


def test_digest_get_is_read_only(calendar_fixture):  # noqa: F811
    client, connection, _ = calendar_fixture
    _bootstrap(client)
    before = _stored_state(connection)

    current = client.get(ROUTE)
    assert current.status_code == 200, current.text
    past = client.get(ROUTE, params={'week_start': '2026-11-09'})
    assert past.status_code == 200, past.text

    assert _stored_state(connection) == before
