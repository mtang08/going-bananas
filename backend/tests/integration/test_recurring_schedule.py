"""Versioned recurrence configuration and calendar/Coach API wiring."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine, get_session
from app.main import app

HEADERS = {'X-Local-Request': '1', 'Origin': 'http://testserver'}


def test_confirmed_rotation_reaches_calendar_and_coach_without_plan_write():
    assert settings.app_mode == 'test'
    with engine.connect() as connection:
        transaction = connection.begin()

        def session_override():
            with Session(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
                yield session

        app.dependency_overrides[get_session] = session_override
        try:
            with TestClient(app) as client:
                current = client.get('/api/v1/profile').json()['data']
                today = datetime.now(ZoneInfo(current['timezone'])).date()
                monday = today - timedelta(days=today.weekday())
                # Keep the test profile independent of existing athlete setup.
                strength_a = [(today.weekday()+1) % 7, (today.weekday()+4) % 7]
                strength_b = [(today.weekday()+2) % 7, (today.weekday()+5) % 7]
                body = {**current, 'expected_version': current['version'],
                        'strength_days_confirmed': True, 'strength_schedule_mode': 'alternating',
                        'strength_week_a_start': monday.isoformat(),
                        'strength_week_a_days': strength_a, 'strength_week_b_days': strength_b,
                        'mobility_week_a_days': [today.weekday()],
                        'mobility_week_b_days': [(today.weekday()+3) % 7],
                        'mobility_optional_days': [(today.weekday()+6) % 7]}
                body.pop('version')
                saved = client.put('/api/v1/profile', json=body, headers=HEADERS)
                assert saved.status_code == 200, saved.text
                assert saved.json()['data']['strength_week_a_start'] == monday.isoformat()
                plans_before = connection.exec_driver_sql('SELECT count(*) FROM plan_versions').scalar_one()
                end = today + timedelta(days=13)
                response = client.get(f'/api/v1/plans?start_date={today}&end_date={end}')
                assert response.status_code == 200, response.text
                slots = response.json()['data']['recurring_sessions']
                assert sum(s['kind'] == 'strength' for s in slots) == 4
                assert any(s['kind'] == 'mobility' and not s['optional'] and s['date'] == today.isoformat() for s in slots)
                assert sum(s['kind'] == 'mobility' and s['optional'] for s in slots) == 2
                coach = client.post('/api/v1/coach/daily', json={'as_of': today.isoformat()}, headers=HEADERS)
                assert coach.status_code == 200, coach.text
                assert any(s['kind'] == 'mobility' and s['source'] == 'recurring_schedule'
                           for s in coach.json()['data']['item']['payload']['planned_sessions'])
                assert connection.exec_driver_sql('SELECT count(*) FROM plan_versions').scalar_one() == plans_before
        finally:
            app.dependency_overrides.pop(get_session, None)
            transaction.rollback()
