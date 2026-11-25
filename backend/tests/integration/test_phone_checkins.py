"""A rest-day observation survives a delayed or duplicated sync."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.api.checkins import router
from app.checkin_models import Checkin
from app.metrics.symptoms import linked_activity_for_checkin
from app.models import Activity
from app.services.snapshot.common import ROLLING
from app.services.snapshot.inputs import load_inputs
from app.services.snapshot.payload import build_payload


def test_offline_replay_in_rolling_review(api_client, session_factory, profile_factory):
    client = api_client(router)
    now = datetime.now(UTC)
    observed = now - timedelta(days=1)
    with session_factory() as session:
        profile_factory(session)
        # A previous day's run is close enough to otherwise be linked automatically.
        run_start = observed - timedelta(days=1)
        session.add(
            Activity(
                start_at=run_start,
                end_at=run_start + timedelta(minutes=30),
                original_start=run_start.isoformat(),
                local_date=run_start.date(),
                sport="running",
                canonical_revision=1,
                resolution_state="resolved",
                field_provenance={},
            )
        )
        session.commit()
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    for entry, pain, response in zip(ids, (0, 3), (None, "eased"), strict=True):
        body = {"observed_at": observed.isoformat(), "pain": pain, "walking_response": response}
        url = "/api/v1/phone/checkins/" + entry
        wrong_workspace = client.put(url, json=body, headers={"X-Phone-Mode": "real"})
        assert wrong_workspace.status_code == 409
        assert wrong_workspace.json()["error"]["code"] == "phone_mode_mismatch"
        for _ in range(2):
            reply = client.put(url, json=body)
            assert reply.status_code == 200, reply.text
            assert reply.json()["data"]["id"] == entry
        assert client.put(url, json={**body, "observed_at": now.isoformat()}).status_code == 409
        observed += timedelta(minutes=1)

    with session_factory() as session:
        rows = list(
            session.scalars(
                select(Checkin)
                .where(Checkin.idempotency_key.in_(["phone-first-steps:" + id for id in ids]))
                .order_by(Checkin.observed_at)
            )
        )
        assert [row.pain_reported for row in rows] == [False, True]
        assert all(row.activity_id is None and linked_activity_for_checkin(session, row) is None for row in rows)
        review_time = datetime.now(UTC)
        payload = build_payload(load_inputs(session, review_time.date(), now=review_time), ROLLING)
        section = payload["symptoms"]
        morning = [row for row in section["morning_first_step_ankle"] if row["checkin_id"] in {str(r.id) for r in rows}]
        assert [(r["pain"], r["walking_response"]) for r in morning] == [(0, None), (3, "eased")]
        assert datetime.fromisoformat(morning[0]["observed_at"]) == now - timedelta(days=1)
        assert not any(r["checkin_id"] == str(rows[0].id) for r in section["reports"])


@pytest.mark.parametrize(
    "changes",
    [
        {"pain": 0},
        {"walking_response": None},
        {"pain": True},
        {"pain": 11},
        {"pain": -1},
        {"walking_response": "unknown"},
        {"observed_at": "2026-11-25T07:00:00"},
    ],
)
def test_phone_rejects_ambiguous_observation(api_client, changes):
    body = {"observed_at": "2026-11-25T07:00:00-05:00", "pain": 2, "walking_response": "gone", **changes}
    response = api_client(router).put(f"/api/v1/phone/checkins/{uuid.uuid4()}", json=body)
    assert response.status_code == 422
