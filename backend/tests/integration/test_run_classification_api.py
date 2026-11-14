"""Historical run suggestions and manual overrides reach activity detail."""

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine, get_session
from app.main import app
from app.models import Activity, ActivityAnnotation


def test_heuristic_and_manual_override_reach_activity_detail():
    assert settings.app_mode == 'test'
    target_day = date(2024, 6, 15)  # Saturday; synthetic, far from current connected data.
    with engine.connect() as connection:
        transaction = connection.begin()

        def session_override():
            with Session(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
                yield session

        app.dependency_overrides[get_session] = session_override
        try:
            with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
                for weeks in range(1, 9):
                    day = target_day - timedelta(days=7 * weeks)
                    session.add(Activity(start_at=datetime.combine(day, datetime.min.time(), UTC).replace(hour=13),
                                         original_start=f'{day}T13:00:00Z', local_date=day,
                                         sport='running', distance_m=5000, elapsed_s=1900,
                                         moving_s=1800, avg_hr_bpm=140, resolution_state='resolved'))
                target = Activity(start_at=datetime.combine(target_day, datetime.min.time(), UTC).replace(hour=13),
                                  original_start=f'{target_day}T13:00:00Z', local_date=target_day,
                                  sport='running', distance_m=8000, elapsed_s=3600,
                                  moving_s=3500, avg_hr_bpm=140, resolution_state='resolved')
                session.add(target)
                session.commit()
                target_id = target.id
            with TestClient(app) as client:
                detail = client.get(f'/api/v1/activities/{target_id}')
                assert detail.status_code == 200, detail.text
                run = detail.json()['data']
                assert run['workout_label'] == 'long'
                assert run['classification']['label_source'] == 'heuristic'
                with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
                    session.add(ActivityAnnotation(activity_id=target_id, version=1,
                                                   workout_label='easy', excluded=False))
                    session.commit()
                corrected = client.get(f'/api/v1/activities/{target_id}').json()['data']
                assert corrected['workout_label'] == 'easy'
                assert corrected['classification']['label_source'] == 'manual'
        finally:
            app.dependency_overrides.pop(get_session, None)
            transaction.rollback()
