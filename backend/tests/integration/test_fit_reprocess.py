"""Exercise the offline CLI with retained synthetic FIT data."""
from __future__ import annotations

import json
import sys
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from test_fit_ingest import START, FakeSource, _import
from test_fit_ingest import db as db

from app import cli
from app.adapters.garmin.fit import DECODER_VERSION
from app.fit_models import ActivityLap, FitFile
from app.models import Activity, AppState, RawObject
from app.services.fit_ingest import ingest_activity_fit

# isort: split
from synthetic import START_FIT_TS, _Writer, build_synthetic_zip  # noqa: E402


@pytest.fixture
def retained(db, tmp_path, monkeypatch):
    writer = _Writer()
    start = START_FIT_TS
    writer.define(0, 0, [(0, 1, 0x00), (4, 4, 0x86)])
    writer.data(0, 4, start)
    writer.define(1, 19, [(253, 4, 0x86), (2, 4, 0x86), (7, 4, 0x86), (23, 1, 0x00)])
    writer.data(1, start + 600, start, 600000, 2)
    writer.define(2, 18, [(253, 4, 0x86), (2, 4, 0x86), (7, 4, 0x86), (8, 4, 0x86), (5, 1, 0x00)])
    writer.data(2, start + 600, start, 600000, 588000, 1)
    payload = build_synthetic_zip({'activity.fit': writer.finish()})
    remote_id = str(uuid.uuid4().int)
    uid = _import(db, tmp_path, remote_id)
    with db() as session:
        activity = session.get(Activity, uid)
        assert ingest_activity_fit(session, FakeSource({remote_id: payload}), tmp_path, activity) == 'decoded'
        lap = session.scalar(select(ActivityLap).where(ActivityLap.activity_id == uid))
        assert lap.intensity == 'warmup'
        fit = session.scalar(select(FitFile).where(FitFile.activity_id == uid))
        path = tmp_path / session.get(RawObject, fit.raw_object_id).relative_path
        fit.decoder_version = DECODER_VERSION - 1
        lap.intensity = None
        lap.end_at = None
        session.commit()

    monkeypatch.setattr(cli, 'SessionLocal', db)
    monkeypatch.setattr(cli, 'settings', SimpleNamespace(app_mode='test', private_dir=tmp_path))
    return uid, path, payload


def _invoke(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, 'argv', ['cli', 'fit-reprocess', *args])
    assert cli.main() == 0
    return json.loads(capsys.readouterr().out)


def _stored(db, uid):
    with db() as session:
        activity = session.get(Activity, uid)
        fit = session.scalar(select(FitFile).where(FitFile.activity_id == uid))
        lap = session.scalar(select(ActivityLap).where(ActivityLap.activity_id == uid))
        return SimpleNamespace(
            activity_revision=activity.canonical_revision, data_revision=session.get(AppState, 1).data_revision,
            fit_status=activity.fit_status, decoder_version=fit.decoder_version, last_error=fit.last_error,
            last_attempt_at=fit.last_attempt_at, raw_object_id=fit.raw_object_id,
            lap_id=lap.id, intensity=lap.intensity, end_at=lap.end_at,
        )


def test_preview_then_apply_reprocesses_retained_fit_once(db, retained, monkeypatch, capsys):
    uid, path, payload = retained
    before = _stored(db, uid)
    since = str(START.date())
    assert _invoke(monkeypatch, capsys, '--since', since) == {
        'mode': 'dry_run', 'selected': 1, 'reprocessed': 1, 'unchanged': 0, 'errors': {},
    }
    assert _stored(db, uid) == before

    later = str(START.date() + timedelta(days=1))
    assert _invoke(monkeypatch, capsys, '--since', later, '--apply')['selected'] == 0
    assert _invoke(monkeypatch, capsys, '--since', later, '--activity-id', str(uid), '--apply') == {
        'mode': 'apply', 'selected': 1, 'reprocessed': 1, 'unchanged': 0, 'errors': {},
    }
    after = _stored(db, uid)
    assert after.decoder_version == DECODER_VERSION
    assert after.activity_revision == before.activity_revision + 1
    assert after.data_revision > before.data_revision
    assert after.raw_object_id == before.raw_object_id
    assert after.intensity == 'warmup'
    assert after.end_at == START + timedelta(seconds=600)
    assert path.read_bytes() == payload
    assert _invoke(monkeypatch, capsys, '--since', since, '--apply')['selected'] == 0
    assert _stored(db, uid) == after


@pytest.mark.parametrize('error', ['raw_missing', 'fit_raw_hash_mismatch'])
def test_unusable_archive_preserves_decoded_rows(db, retained, monkeypatch, capsys, error):
    uid, path, _ = retained
    with db() as session:
        session.execute(update(FitFile).where(FitFile.activity_id == uid).values(decoder_version=None))
        session.commit()
    before = _stored(db, uid)
    if error == 'raw_missing':
        path.unlink()
    else:
        path.write_bytes(b'not the retained FIT archive')

    assert _invoke(monkeypatch, capsys, '--since', str(START.date()), '--apply') == {
        'mode': 'apply', 'selected': 1, 'reprocessed': 0, 'unchanged': 0, 'errors': {error: 1},
    }
    after = _stored(db, uid)
    assert after.last_error == error
    assert after.last_attempt_at >= before.last_attempt_at
    for field in ('activity_revision', 'data_revision', 'fit_status', 'decoder_version', 'raw_object_id',
                  'lap_id', 'intensity', 'end_at'):
        assert getattr(after, field) == getattr(before, field)
