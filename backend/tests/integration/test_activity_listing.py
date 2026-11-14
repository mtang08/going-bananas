"""Activity listing preserves detail payloads and stable cursor pagination."""
from __future__ import annotations

import os
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine, get_session
from app.main import app
from app.models import Activity, ActivityAnnotation, ProfileVersion

WINDOW = {'start_date': '2024-03-01', 'end_date': '2024-04-15'}


@pytest.fixture
def listing():
    parsed = urlsplit(settings.database_url)
    assert settings.app_mode == 'test'
    assert parsed.hostname in {'127.0.0.1', 'localhost'}
    assert parsed.port == int(os.environ.get('TEST_DATABASE_PORT', '55439'))
    assert parsed.path == '/garmin_test'
    with engine.connect() as connection:
        outer = connection.begin()
        def override():
            with Session(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
                yield session
        app.dependency_overrides[get_session] = override
        try:
            with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
                version = (session.scalar(select(func.max(ProfileVersion.version))) or 0) + 1
                session.add(ProfileVersion(version=version, effective_at=datetime(2024, 1, 1, tzinfo=UTC),
                    timezone='America/New_York', facts={}, preferences={}, unknowns=[]))
                ids = []
                for i in range(40):
                    day = date(2024, 3, 1) + timedelta(days=i)
                    activity = Activity(start_at=datetime.combine(day, time(13), UTC),
                        original_start=f'{day}T13:00:00Z', local_date=day, sport='running', distance_m=5000 + 100 * i,
                        elapsed_s=1900, moving_s=1800, avg_hr_bpm=140, resolution_state='resolved',
                        canonical_revision=1, field_provenance={})
                    session.add(activity)
                    session.flush()
                    ids.append(activity.id)
                    if i % 3 == 0:
                        session.add_all([ActivityAnnotation(activity_id=activity.id, version=1, workout_label='quality', notes='v1'),
                                         ActivityAnnotation(activity_id=activity.id, version=2, workout_label='easy', notes='v2', excluded=False)])
                session.add(Activity(start_at=datetime(2024, 3, 5, 18, tzinfo=UTC), original_start='2024-03-05T18:00:00Z',
                    local_date=date(2024, 3, 5), sport='strength', elapsed_s=1900, canonical_revision=1,
                    resolution_state='resolved', field_provenance={}))
                session.commit()
            yield TestClient(app), connection, ids
        finally:
            app.dependency_overrides.pop(get_session, None)
            outer.rollback()


def test_listing_payload_matches_detail(listing):
    client, _, ids = listing
    response = client.get('/api/v1/activities', params={**WINDOW, 'limit': 200})
    assert response.status_code == 200, response.text
    data = response.json()['data']
    items = data['items']
    assert len(items) == 41 and data['timezone'] == 'America/New_York'
    assert [row['start_at'] for row in items] == sorted((row['start_at'] for row in items), reverse=True)
    annotated = next(row for row in items if row['id'] == str(ids[0]))
    assert annotated['annotations'] == {'version': 2, 'workout_label': 'easy', 'notes': 'v2', 'excluded': False}
    assert annotated['workout_label'] == 'easy' and annotated['classification']['label_source'] == 'manual'
    unannotated = next(row for row in items if row['id'] == str(ids[1]))
    assert unannotated['annotations']['version'] == 0
    strength = next(row for row in items if row['sport'] == 'strength')
    assert strength['classification'] is None
    for row in (annotated, unannotated, strength):
        response = client.get(f"/api/v1/activities/{row['id']}")
        assert response.status_code == 200, response.text
        detail = response.json()['data']
        detail.pop('sources')
        assert detail == row


def test_listing_pages_with_cursor(listing):
    client, _, _ = listing
    expected = client.get('/api/v1/activities', params={**WINDOW, 'limit': 200}).json()['data']['items']
    seen = []
    cursor = None
    while True:
        params = {**WINDOW, 'limit': 15}
        if cursor is not None:
            params['cursor'] = cursor
        response = client.get('/api/v1/activities', params=params)
        assert response.status_code == 200, response.text
        page = response.json()['data']
        assert len(page['items']) == min(15, 41 - len(seen))
        seen.extend(row['id'] for row in page['items'])
        cursor = page['next_cursor']
        if cursor is None:
            break
        assert len(seen) < 41
    assert len(seen) == len(set(seen)) == 41
    assert seen == [row['id'] for row in expected]


def test_statement_count_independent_of_page_size(listing):
    client, connection, _ = listing
    statements = []
    def counter(*args):
        statements.append(1)
    event.listen(connection, 'before_cursor_execute', counter)
    try:
        counts = []
        for limit in (5, 30):
            statements.clear()
            response = client.get('/api/v1/activities', params={**WINDOW, 'limit': limit})
            assert response.status_code == 200, response.text
            assert len(response.json()['data']['items']) == limit
            counts.append(len(statements))
        assert counts[0] == counts[1] and counts[0] <= 20, counts
    finally:
        event.remove(connection, 'before_cursor_execute', counter)
