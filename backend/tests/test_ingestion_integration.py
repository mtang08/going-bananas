"""Run with a migrated disposable PostgreSQL TEST_DATABASE_URL."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import app.services.sync as sync
from app.models import Conflict, SourceAccount, SourceRecord, SyncJob


@pytest.fixture
def isolated_db(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    assert url, "TEST_DATABASE_URL is required for integration verification"
    assert os.environ.get("APP_MODE") == "test", "Only test mode is allowed"
    assert (make_url(url).database or "").endswith("_test"), "Refusing non-test database"
    engine = create_engine(url)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with engine.connect() as connection:
        try:
            connection.execute(text("SELECT 1 FROM sync_jobs LIMIT 1"))
        except Exception as exc:
            raise AssertionError("Test database migration unavailable") from exc
    monkeypatch.setattr(sync, "engine", engine)
    monkeypatch.setattr(sync, "SessionLocal", session_factory)
    yield engine, session_factory
    engine.dispose()


def test_concurrent_enqueue_one_job(isolated_db):
    _, Session = isolated_db
    dataset = "test_concurrent_enqueue"

    def enqueue(_: int) -> str:
        with Session.begin() as session:
            return str(sync.enqueue_sync(session, date(2026, 10, 1), date(2026, 10, 2), dataset).id)

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(enqueue, range(8)))
    assert len(set(ids)) == 1
    with Session.begin() as session:
        job = session.get(SyncJob, UUID(ids[0]))
        assert job is not None
        session.delete(job)


def test_long_retry_attempts_persist_across_worker_calls(isolated_db, monkeypatch, tmp_path):
    engine, Session = isolated_db
    with Session.begin() as session:
        for old in session.scalars(select(SyncJob).where(
            SyncJob.dataset == "activities", SyncJob.status.in_(("queued", "running", "retry_wait")))):
            old.status = "failed"
        job = sync.enqueue_sync(session, date(2026, 9, 1), date(2026, 9, 2))
        job_id = job.id

    class Response:
        headers = {"Retry-After": "31"}

    class RateLimited(Exception):
        status_code = 429
        response = Response()

    class FakeSource:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def search_page(self, *_args):
            raise RateLimited()

    monkeypatch.setattr(sync, "GarminPersonalSource", FakeSource)
    results = []
    for _ in range(4):
        result = sync.run_one_job(tmp_path, Path("/unused"), "auto")
        with Session.begin() as session:
            current = session.get(SyncJob, job_id)
            assert current is not None
            results.append((result, current.checkpoint.get("attempts")))
            current.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    assert results == [("retry_wait", 1), ("retry_wait", 2), ("retry_wait", 3), ("failed", 3)]
    with engine.connect() as connection:
        assert connection.scalar(text(f"SELECT pg_try_advisory_lock({sync.ADVISORY_LOCK})"))
        connection.execute(text(f"SELECT pg_advisory_unlock({sync.ADVISORY_LOCK})"))
    with Session.begin() as session:
        current = session.get(SyncJob, job_id)
        if current:
            session.delete(current)


def test_partial_recovery_keeps_rejected_source(isolated_db, monkeypatch, tmp_path):
    _, Session = isolated_db
    with Session.begin() as session:
        existing = session.scalar(select(SourceAccount).where(SourceAccount.provider == "garmin"))
        if existing and existing.account_scope != "garmin-owner:17":
            existing_id = existing.id
            monkeypatch.setattr(sync, "_account", lambda current, _provider, _scope: current.get(SourceAccount, existing_id))
        job = sync.enqueue_sync(session, date(2026, 8, 1), date(2026, 8, 2), "sleep")
        job_id = job.id

    class FakeSource:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def fetch_recovery(self, *_args):
            return [
                {"userProfilePK": 17, "calendarDate": "2026-08-01", "sleepTimeSeconds": 20000},
                {"calendarDate": "2026-08-02", "sleepTimeSeconds": 19000},
            ]

    monkeypatch.setattr(sync, "GarminPersonalSource", FakeSource)
    assert sync.run_one_job(tmp_path, Path("/unused"), "auto") == "partial"
    with Session.begin() as session:
        current = session.get(SyncJob, job_id)
        assert current is not None and current.error_code == "rejected_records"
        rejected = session.scalar(select(SourceRecord).where(
            SourceRecord.source_identity == "sleep:2026-08-02:main_sleep_duration"))
        assert rejected is not None and rejected.rejected_reason == "missing_recovery_owner"
        session.delete(current)


def test_close_no_id_activities_enter_review(isolated_db, tmp_path):
    _, Session = isolated_db
    records = [
        {"startTimeGMT": "2026-07-01T12:00:00Z", "activityType": {"typeKey": "running"},
         "distance": 5000, "elapsedDuration": 1800},
        {"startTimeGMT": "2026-07-01T12:03:00Z", "activityType": {"typeKey": "running"},
         "distance": 5030, "elapsedDuration": 1820},
    ]
    with Session.begin() as session:
        sync.import_activity_page(session, tmp_path, records, account_scope="synthetic-overlap",
                                  source_kind="demo_fixture")
    with Session.begin() as session:
        conflicts = session.scalars(select(Conflict).where(Conflict.kind == "activity_overlap")).all()
        assert any(row.status == "open" and len(row.activity_ids) == 2 for row in conflicts)
