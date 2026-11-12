from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.adapters.garmin.normalize import parse_activity
from app.adapters.garmin.personal import GarminRemoteError
from app.services import fit_ingest, sync


class _FakeSession:
    def scalar(self, _statement):
        return None


class _FakeSource:
    calls: list[str]
    def __init__(self, error):
        self.error = error
        self.calls = []
    def download_activity(self, activity_id: str) -> bytes:
        self.calls.append(activity_id)
        raise self.error


def test_private_zip_store_is_bytes_exact_and_replay_safe(tmp_path: Path) -> None:
    payload = b'PK synthetic fit zip bytes \x00\xff'
    digest, relative = fit_ingest.store_fit_zip(tmp_path, payload)
    path = tmp_path / relative
    assert digest == hashlib.sha256(payload).hexdigest()
    assert path.read_bytes() == payload
    assert path.suffix == '.zip'
    assert path.stat().st_mode & 0o077 == 0
    assert path.parent.stat().st_mode & 0o077 == 0
    assert fit_ingest.store_fit_zip(tmp_path, payload) == (digest, relative)


def test_missing_and_ambiguous_remote_id_do_not_download(monkeypatch, tmp_path: Path) -> None:
    class IdSession:
        def __init__(self, identities):
            self.identities = identities
        def scalars(self, _):
            return SimpleNamespace(all=lambda: self.identities)
        def scalar(self, _):
            return None
    activity = SimpleNamespace(id='synthetic', fit_status='not_fetched')
    monkeypatch.setattr(fit_ingest, '_locked_rows', lambda _session, _id: (activity, None))
    source = _FakeSource(RuntimeError('must not call'))
    assert fit_ingest.ingest_activity_fit(IdSession([]), source, tmp_path, activity) == 'decode_error'
    assert source.calls == []
    activity.fit_status = 'not_fetched'
    assert fit_ingest.ingest_activity_fit(IdSession(['garmin:1', 'garmin:2']),
                                          source, tmp_path, activity) == 'decode_error'
    assert source.calls == []


def test_404_unavailable_and_retryable_read_timeout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(fit_ingest, '_remote_id', lambda *_: '123')
    activity = SimpleNamespace(id='synthetic', fit_status='not_fetched')
    monkeypatch.setattr(fit_ingest, '_locked_rows', lambda _session, _id: (activity, None))
    source = _FakeSource(GarminRemoteError(404, None))
    assert fit_ingest.ingest_activity_fit(_FakeSession(), source, tmp_path, activity) == 'unavailable'
    assert source.calls == ['123']
    class ReadTimeout(Exception):
        pass
    assert sync.retry_delay(ReadTimeout(), 1, datetime(2026, 11, 12, tzinfo=UTC)) is not None
    assert sync.retry_delay(RuntimeError('not retryable'), 1) is None


def test_athlete_timezone_defaults_to_profile() -> None:
    class ProfileSession:
        def scalar(self, _):
            return SimpleNamespace(timezone='Asia/Tokyo')
    assert sync.athlete_tz(ProfileSession()) == 'Asia/Tokyo'
    assert sync.athlete_tz(_FakeSession()) == 'America/New_York'
    before = parse_activity({'activityId': '1', 'startTimeGMT': '2026-11-01T05:30:00Z',
                             'activityType': {'typeKey': 'running'}}, 'America/New_York')
    after = parse_activity({'activityId': '2', 'startTimeGMT': '2026-11-01T06:30:00Z',
                            'activityType': {'typeKey': 'running'}}, 'America/New_York')
    assert before.local_date == after.local_date == '2026-11-01'
    assert before.start_at != after.start_at


def test_job_lookup_failure_before_id_preserves_original_error(monkeypatch, tmp_path: Path) -> None:
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def execute(self, _):
            return None
        def commit(self):
            pass
        def rollback(self):
            pass
    class JobSession:
        def __init__(self, **_):
            self.reads = 0
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def scalar(self, _):
            self.reads += 1
            if self.reads == 1:
                return True
            raise ValueError('job_lookup_broken')
        def rollback(self):
            pass
    monkeypatch.setattr(sync, 'engine', SimpleNamespace(connect=Connection))
    monkeypatch.setattr(sync, 'Session', JobSession)
    with pytest.raises(ValueError, match='job_lookup_broken'):
        sync.run_one_job(tmp_path, tmp_path / 'unused', 'auto')


def test_fit_page_isolates_middle_failure_after_page_commit(monkeypatch, tmp_path: Path) -> None:
    outcomes = []
    sessions = []
    class PageSession:
        def __init__(self, remote_id):
            self.remote_id = remote_id
            self.reads = 0
            self.committed = False
            self.rolled_back = False
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def scalar(self, _):
            self.reads += 1
            return SimpleNamespace(id='synthetic-account') if self.reads == 1 else SimpleNamespace(garmin_id=self.remote_id)
        def commit(self):
            self.committed = True
        def rollback(self):
            self.rolled_back = True
    remaining = iter(('first', 'middle', 'third'))
    def factory():
        instance = PageSession(next(remaining))
        sessions.append(instance)
        return instance
    def ingest(_session, _source, _private_dir, activity):
        outcomes.append(activity.garmin_id)
        if activity.garmin_id == 'middle':
            raise RuntimeError('synthetic middle failure')
        return 'decoded'
    monkeypatch.setattr(fit_ingest, 'ingest_activity_fit', ingest)
    page = [{'ownerId': 12345, 'activityId': remote_id} for remote_id in ('first', 'middle', 'third')]
    sync._ingest_fit_page(SimpleNamespace(), tmp_path, page, session_factory=factory)
    assert outcomes == ['first', 'middle', 'third']
    assert [item.committed for item in sessions] == [True, False, True]
    assert [item.rolled_back for item in sessions] == [False, True, False]
