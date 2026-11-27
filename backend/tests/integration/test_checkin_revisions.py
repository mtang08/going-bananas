"""Check-in replay preserves the original payload when a later edit creates a revision."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.checkin_models import CheckinRevision
from app.errors import AppError
from app.services.checkins import create_checkin, patch_checkin


def test_create_replay_patch_and_revision(session_factory):
    observed_at = datetime.now(UTC) - timedelta(days=1)
    body = {
        "idempotency_key": f"fixture-{uuid4().hex}",
        "kind": "exception",
        "observed_at": observed_at.isoformat(),
        "fatigue": 7,
        "symptoms": [{"site": "Achilles", "side": "left", "severity": 3.0, "timing": "during"}],
        "note": "synthetic note",
    }
    with session_factory() as session:
        original, created = create_checkin(session, body)
        assert created
        assert create_checkin(session, body) == (original, False)
        with pytest.raises(AppError) as conflict:
            create_checkin(session, {**body, "note": "different note"})
        assert conflict.value.code == "idempotency_conflict"

        edited = patch_checkin(session, original["id"], {"expected_version": 1, "note": None})
        assert (edited["version"], edited["note"]) == (2, None)
        with pytest.raises(AppError) as stale:
            patch_checkin(session, original["id"], {"expected_version": 1, "fatigue": 6})
        assert stale.value.code == "version_conflict"

        replay, created = create_checkin(session, body)
        revision = session.scalar(select(CheckinRevision).where(CheckinRevision.checkin_id == original["id"]))
        assert revision is not None
        assert not created and replay == revision.payload
        assert replay["id"] == str(original["id"])
        assert replay["observed_at"] == observed_at.isoformat()
        assert replay["symptoms"][0]["id"] == str(original["symptoms"][0]["id"])
        assert replay["symptoms"][0]["severity"] == 3.0
        assert replay["note"] == body["note"]
