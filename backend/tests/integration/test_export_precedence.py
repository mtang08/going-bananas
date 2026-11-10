"""Independent assertions for cross-source recovery/activity reconciliation."""
import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Activity, RecoveryObservation, SourceAccount, SourceRecord
from app.services.sync import import_activity_page, import_recovery_page


@pytest.mark.parametrize('order', [('garmin_export', 'garmin_api'), ('garmin_api', 'garmin_export')])
def test_recovery_api_wins_in_either_order_and_replay_is_noop(tmp_path, order):
    assert settings.app_mode == 'test'
    with SessionLocal() as session:
        account = session.scalar(select(SourceAccount).where(SourceAccount.provider == 'garmin'))
        owner = int(account.account_scope.split(':')[-1]) if account else 777
        for kind in order:
            value = 41000 if kind == 'garmin_api' else 40000
            record = {'userProfilePK': owner, 'calendarDate': '1980-01-01', 'sleepTimeSeconds': value}
            raw = {'exportSleepSeconds': value} if kind == 'garmin_export' else record
            import_recovery_page(session, tmp_path, 'sleep', [record], source_kind=kind,
                                 raw_records=[raw], fetched_at=datetime(2026, 1, 1, tzinfo=UTC))
        row = session.scalar(select(RecoveryObservation).where(
            RecoveryObservation.source_date == date(1980, 1, 1), RecoveryObservation.metric == 'sleep'))
        assert row is not None and row.value == 41000
        assert session.get(SourceRecord, row.source_record_id).source_kind == 'garmin_api'
        replay = import_recovery_page(session, tmp_path, 'sleep',
            [{'userProfilePK': owner, 'calendarDate': '1980-01-01', 'sleepTimeSeconds': 40000}],
            source_kind='garmin_export', raw_records=[{'exportSleepSeconds': 40000}])
        assert replay['changed'] == replay['new_revisions'] == 0


def test_activity_export_preserves_original_units_and_api_value(tmp_path):
    assert settings.app_mode == 'test'
    with SessionLocal() as session:
        account = session.scalar(select(SourceAccount).where(SourceAccount.provider == 'garmin'))
        owner = int(account.account_scope.split(':')[-1]) if account else 777
        record = {'ownerId': owner, 'activityId': 'export-test-activity',
                  'startTimeGMT': '1980-01-01T12:00:00Z', 'activityType': {'typeKey': 'track_running'},
                  'distance': 5000, 'elapsedDuration': 1800, 'movingDuration': 1750}
        original = {'activityId': record['activityId'], 'distance': 500000, 'elapsedDuration': 1800000}
        metadata = {'field_paths': {'distance_m': 'distance / 100'}, 'archive_sha256': 'a'*64}
        imported = import_activity_page(session, tmp_path, [record], account_scope=f'garmin-owner:{owner}',
            source_kind='garmin_export', raw_records=[original], source_metadata=[metadata])
        assert imported['changed'] == 1
        exported_source = session.scalar(select(SourceRecord).where(
            SourceRecord.source_identity == 'garmin:export-test-activity'))
        assert exported_source.fields['distance_m'] == 5000
        assert exported_source.fields['export_provenance']['archive_sha256'] == 'a'*64
        raw_file = next(path for path in tmp_path.rglob('*.json') if json.loads(path.read_text()) == original)
        assert json.loads(raw_file.read_text())['distance'] == 500000
        imported = import_activity_page(session, tmp_path, [{**record, 'distance': 5010}],
                                         account_scope=f'garmin-owner:{owner}')
        row = session.scalar(select(Activity).where(Activity.garmin_id == 'export-test-activity'))
        assert row.distance_m == 5010 and row.sport == 'running' and row.subtype == 'track_running'
        replay = import_activity_page(session, tmp_path, [record], account_scope=f'garmin-owner:{owner}',
            source_kind='garmin_export', raw_records=[original], source_metadata=[metadata])
        assert replay['changed'] == replay['new_revisions'] == 0
        assert row.distance_m == 5010
