"""Synthetic FIT persistence and isolation tests in a disposable PostgreSQL schema."""
from __future__ import annotations

import os
import sys
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fixtures' / 'fit'))
from synthetic import FIT_EPOCH_OFFSET, START_FIT_TS, build_synthetic_fit, build_synthetic_zip, crc16  # noqa: E402

from app.checkin_models import SessionRpe  # noqa: E402
from app.config import settings  # noqa: E402
from app.fit_models import ActivityLap, ActivityStream, ActivityWorkoutStep, FitFile  # noqa: E402
from app.models import Activity, ProfileVersion, RawObject  # noqa: E402
from app.services.fit_ingest import backfill_fit, ingest_activity_fit  # noqa: E402
from app.services.sync import import_activity_page  # noqa: E402

START = datetime.fromtimestamp(START_FIT_TS + FIT_EPOCH_OFFSET, UTC)


def _guard_url() -> str:
    url = os.environ.get('MIGRATION_TEST_DATABASE_URL', '')
    parsed = make_url(url)
    assert settings.app_mode == 'test'
    assert parsed.drivername in ('postgresql+psycopg', 'postgresql')
    assert parsed.host in ('localhost', '127.0.0.1')
    assert parsed.port == 55439 and parsed.database == 'mvp1_migration_test'
    return url


@pytest.fixture
def db():
    engine = create_engine(_guard_url())
    schema = 'mvp010_' + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        with engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            config = Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
            connection.commit()
            yield sessionmaker(bind=connection, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


class FakeSource:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []
    def download_activity(self, activity_id: str) -> bytes:
        self.calls.append(activity_id)
        value = self.payloads[activity_id]
        if isinstance(value, Exception):
            raise value
        return value


def _record(remote_id: str, start: datetime = START) -> dict:
    return {'ownerId': 12345, 'activityId': remote_id,
            'startTimeGMT': start.isoformat(), 'activityType': {'typeKey': 'running'},
            'distance': 1764.0, 'elapsedDuration': 600.0}


def _import(db, private_dir: Path, remote_id: str, start: datetime = START) -> uuid.UUID:
    with db() as session:
        import_activity_page(session, private_dir, [_record(remote_id, start)],
                             account_scope='garmin-owner:12345')
        session.commit()
        return session.scalar(select(Activity.id).where(Activity.garmin_id == remote_id))


def _changed_zip() -> bytes:
    payload = bytearray(build_synthetic_fit())
    offset = payload.index(b'Warm up')
    payload[offset:offset + 7] = b'Warm UP'
    payload[-2:] = crc16(payload[:-2]).to_bytes(2, 'little')
    return build_synthetic_zip({'changed.fit': bytes(payload)})


@pytest.mark.integration
def test_first_replay_changed_and_failed_retry_preserve_provenance(db, tmp_path: Path, monkeypatch) -> None:
    remote_id = str(uuid.uuid4().int)
    activity_id = _import(db, tmp_path, remote_id)
    source = FakeSource({remote_id: build_synthetic_zip()})
    with db() as session:
        activity = session.get(Activity, activity_id)
        initial_revision = activity.canonical_revision
        assert ingest_activity_fit(session, source, tmp_path, activity) == 'decoded'
        assert activity.canonical_revision == initial_revision + 1
        fit = session.scalar(select(FitFile).where(FitFile.activity_id == activity_id))
        assert fit.fit_sha256 != fit.zip_sha256
        assert session.scalar(select(func.count()).select_from(ActivityLap)) == 2
        assert session.scalar(select(func.count()).select_from(ActivityWorkoutStep)) == 4
        stream = session.get(ActivityStream, activity_id)
        assert stream.sample_count == 588
        assert activity.timer_s == 588 and activity.end_at == START + timedelta(seconds=600)
        assert activity.workout_rpe == 6.5
        assert session.scalar(select(SessionRpe).where(SessionRpe.activity_id == activity_id,
            SessionRpe.source == 'garmin_fit')).rpe == 6.5
        first_fit_id, first_raw_id, first_sha = fit.id, fit.raw_object_id, fit.zip_sha256
        lap_ids = {row.id for row in session.scalars(select(ActivityLap))}
        revision = activity.canonical_revision
        session.commit()
    with db() as session:
        activity = session.get(Activity, activity_id)
        assert ingest_activity_fit(session, source, tmp_path, activity) == 'decoded'
        assert activity.canonical_revision == revision
        assert {row.id for row in session.scalars(select(ActivityLap))} == lap_ids
        session.add(SessionRpe(activity_id=activity_id, source='manual', rpe=7,
                               collected_at=START + timedelta(hours=1)))
        session.commit()
    source.payloads[remote_id] = b'bad ZIP'
    with db() as session:
        activity = session.get(Activity, activity_id)
        assert ingest_activity_fit(session, source, tmp_path, activity) == 'decoded'
        fit = session.scalar(select(FitFile).where(FitFile.activity_id == activity_id))
        assert fit.id == first_fit_id and fit.raw_object_id == first_raw_id
        assert fit.zip_sha256 == first_sha and fit.last_error == 'bad_zip'
        assert activity.canonical_revision == revision and activity.workout_rpe == 6.5
        assert session.scalar(select(func.count()).select_from(RawObject)) >= 2
        session.commit()
    source.payloads[remote_id] = build_synthetic_zip()
    with db() as session:
        activity = session.get(Activity, activity_id)
        assert ingest_activity_fit(session, source, tmp_path, activity) == 'decoded'
        fit = session.scalar(select(FitFile).where(FitFile.activity_id == activity_id))
        assert fit.id == first_fit_id and fit.raw_object_id == first_raw_id
        assert fit.last_error is None and activity.canonical_revision == revision
        assert {row.id for row in session.scalars(select(ActivityLap))} == lap_ids
        session.commit()
    source.payloads[remote_id] = _changed_zip()
    with db() as session:
        activity = session.get(Activity, activity_id)
        assert ingest_activity_fit(session, source, tmp_path, activity) == 'decoded'
        assert activity.canonical_revision == revision + 1
        fit = session.scalar(select(FitFile).where(FitFile.activity_id == activity_id))
        assert fit.id == first_fit_id and fit.last_error is None
        assert {row.id for row in session.scalars(select(ActivityLap))} != lap_ids
        assert session.scalar(select(SessionRpe).where(SessionRpe.activity_id == activity_id,
            SessionRpe.source == 'manual')).rpe == 7
        session.commit()
    from app.services import fit_ingest
    no_rpe_fit = bytearray(build_synthetic_fit())
    offset = no_rpe_fit.index(b'Warm up')
    no_rpe_fit[offset:offset + 7] = b'Warm no'
    no_rpe_fit[-2:] = crc16(no_rpe_fit[:-2]).to_bytes(2, 'little')
    source.payloads[remote_id] = build_synthetic_zip({'no-rpe.fit': bytes(no_rpe_fit)})
    original_decode = fit_ingest.decode_fit
    with monkeypatch.context() as patcher:
        patcher.setattr(fit_ingest, 'decode_fit', lambda payload: replace(
            (decoded := original_decode(payload)), session=replace(decoded.session, workout_rpe=None)))
        with db() as session:
            activity = session.get(Activity, activity_id)
            assert ingest_activity_fit(session, source, tmp_path, activity) == 'decoded'
            assert activity.workout_rpe is None
            assert session.scalar(select(SessionRpe).where(SessionRpe.activity_id == activity_id,
                SessionRpe.source == 'garmin_fit')) is None
            assert session.scalar(select(SessionRpe).where(SessionRpe.activity_id == activity_id,
                SessionRpe.source == 'manual')).rpe == 7
            good_sha = session.scalar(select(FitFile).where(FitFile.activity_id == activity_id)).fit_sha256
            session.commit()
    # A failure after derivative replacement must roll back the whole activity transaction.
    changed_again = bytearray(build_synthetic_fit())
    offset = changed_again.index(b'Warm up')
    changed_again[offset:offset + 7] = b'Warm zz'
    changed_again[-2:] = crc16(changed_again[:-2]).to_bytes(2, 'little')
    source.payloads[remote_id] = build_synthetic_zip({'another.fit': bytes(changed_again)})
    original_bump = fit_ingest.bump_data_revision
    monkeypatch.setattr(fit_ingest, 'bump_data_revision', lambda _session: (_ for _ in ()).throw(RuntimeError('synthetic_flush_failure')))
    with db() as session:
        with pytest.raises(RuntimeError, match='synthetic_flush_failure'):
            ingest_activity_fit(session, source, tmp_path, session.get(Activity, activity_id))
        session.rollback()
    monkeypatch.setattr(fit_ingest, 'bump_data_revision', original_bump)
    with db() as session:
        assert session.scalar(select(FitFile).where(FitFile.activity_id == activity_id)).fit_sha256 == good_sha
        assert session.get(Activity, activity_id).canonical_revision == revision + 2


@pytest.mark.integration
def test_initial_corrupt_middle_failure_and_backfill_isolation(db, tmp_path: Path) -> None:
    ids = [str(uuid.uuid4().int) for _ in range(3)]
    activity_ids = [_import(db, tmp_path, remote_id, START + timedelta(days=n))
                    for n, remote_id in enumerate(ids)]
    # The same synthetic FIT start only matches the first; use an explicit corrupt middle
    # and a third run at the original FIT start for a valid third decode.
    with db() as session:
        third = session.get(Activity, activity_ids[2])
        third.start_at = START
        third.local_date = START.date()
        session.commit()
    source = FakeSource({ids[0]: build_synthetic_zip(), ids[1]: b'corrupt',
                         ids[2]: _changed_zip()})
    counts = backfill_fit(db, source, tmp_path, START.date())
    assert counts == {'attempted': 3, 'decoded': 2, 'unavailable': 0, 'failed': 1}
    with db() as session:
        rows = [session.get(Activity, row_id) for row_id in activity_ids]
        assert [row.fit_status for row in rows] == ['decoded', 'decode_error', 'decoded']
        failed = session.scalar(select(FitFile).where(FitFile.activity_id == activity_ids[1]))
        assert failed.fit_sha256 is None and failed.zip_sha256
        assert failed.last_error == 'bad_zip'
        assert session.scalar(select(func.count()).select_from(ActivityStream)) == 2


@pytest.mark.integration
def test_profile_timezone_and_fit_timer_survive_summary_replay(db, tmp_path: Path) -> None:
    with db() as session:
        session.add(ProfileVersion(version=1, effective_at=START,
                                   timezone='Asia/Tokyo'))
        session.commit()
    remote_id = str(uuid.uuid4().int)
    midnight = datetime(2026, 11, 10, 23, 30, tzinfo=UTC)
    with db() as session:
        first = import_activity_page(session, tmp_path, [_record(remote_id, midnight)],
                                     account_scope='garmin-owner:12345')
        assert first['changed'] == 1
        session.commit()
        activity = session.scalar(select(Activity).where(Activity.garmin_id == remote_id))
        assert activity.local_date == date(2026, 11, 11)
        assert activity.timer_s is None
    # A separate run matching the synthetic FIT start exercises timer provenance replay.
    fit_id = str(uuid.uuid4().int)
    activity_id = _import(db, tmp_path, fit_id)
    with db() as session:
        activity = session.get(Activity, activity_id)
        assert ingest_activity_fit(session, FakeSource({fit_id: build_synthetic_zip()}),
                                   tmp_path, activity) == 'decoded'
        session.commit()
        revision = activity.canonical_revision
        provenance = dict(activity.field_provenance)
    with db() as session:
        again = import_activity_page(session, tmp_path, [_record(fit_id)],
                                     account_scope='garmin-owner:12345')
        assert again['changed'] == 0
        activity = session.get(Activity, activity_id)
        assert activity.canonical_revision == revision
        assert activity.timer_s == 588
        assert activity.field_provenance == provenance
        session.commit()
