"""Synthetic end-to-end export import transaction tests against the test DB."""

import hashlib
import json
from datetime import UTC, datetime
from zipfile import ZipFile

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Activity, CoverageInterval, SourceAccount, SourceRecord
from app.services.export_import import import_export
from app.services.sync import import_activity_page


def test_export_preserves_bytes_and_replays_without_revisions(tmp_path):
    assert settings.app_mode == "test"
    with SessionLocal() as session:
        existing = session.scalar(select(SourceAccount).where(SourceAccount.provider == "garmin"))
        owner = int(existing.account_scope.rsplit(":", 1)[-1]) if existing else 777
        activity_id = 9_990_001
        stamp = datetime(2021, 5, 1, 12, tzinfo=UTC)
        api = {"activityId": activity_id, "ownerId": owner, "startTimeGMT": stamp.isoformat(),
               "activityType": {"typeKey": "running"}, "distance": 5010,
               "elapsedDuration": 1800, "movingDuration": 1750}
        import_activity_page(session, tmp_path, [api], account_scope="auto")
        export_row = {"activityId": activity_id, "userProfileId": owner,
                      "startTimeGmt": int(stamp.timestamp() * 1000), "activityType": "running",
                      "distance": 500_000, "elapsedDuration": 1_800_000,
                      "movingDuration": 1_750_000}
        member_bytes = json.dumps([{"summarizedActivitiesExport": [export_row]}]).encode()
        archive_path = tmp_path / "synthetic.zip"
        with ZipFile(archive_path, "w") as archive:
            archive.writestr("test/summarizedActivities.json", member_bytes)
        original_archive = archive_path.read_bytes()
        preview = import_export(session, tmp_path, archive_path)
        assert preview["existing_activity_overlap"] == 1
        assert preview["overlap_differing_fields"] == 1
        assert not (tmp_path / "raw" / "archives").exists()
        first = import_export(session, tmp_path, archive_path, apply=True)
        assert first["activity_counts"]["new_revisions"] == 1
        assert (tmp_path / "raw" / "archives" / f"{hashlib.sha256(original_archive).hexdigest()}.zip").read_bytes() == original_archive
        assert (tmp_path / "raw" / hashlib.sha256(member_bytes).hexdigest()[:2] /
                f"{hashlib.sha256(member_bytes).hexdigest()}.json").read_bytes() == member_bytes
        activity = session.scalar(select(Activity).where(Activity.garmin_id == str(activity_id)))
        assert activity.distance_m == 5010
        source = session.scalar(select(SourceRecord).where(
            SourceRecord.source_identity == f"garmin:{activity_id}",
            SourceRecord.source_kind == "garmin_export"))
        assert source.fields["export_provenance"]["archive_sha256"] == hashlib.sha256(original_archive).hexdigest()
        replay = import_export(session, tmp_path, archive_path, apply=True)
        assert replay["activity_counts"]["new_revisions"] == 0
        assert replay["activity_counts"]["changed"] == 0
        coverage = session.scalars(select(CoverageInterval).where(
            CoverageInterval.dataset == "activities",
            CoverageInterval.reason == "export_snapshot_observed")).all()
        assert sum(row.start_date.year == 2021 and row.end_date.year == 2021 for row in coverage) == 1
        session.rollback()
