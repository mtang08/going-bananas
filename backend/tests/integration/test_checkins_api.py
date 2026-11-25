"""Synthetic v2 check-in and guidance transactions under one outer rollback."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.checkins import router
from app.checkin_models import Checkin, CheckinRevision, SessionRpe, SymptomReport
from app.exception_models import ExceptionFinding, ExceptionPatch
from app.metric_models import Prompt
from app.models import Activity


@pytest.fixture
def api_fixture(db_connection, session_factory, api_client, profile_factory, calendar_state):
    with session_factory() as session:
        for model in (ExceptionFinding, ExceptionPatch, CheckinRevision, SymptomReport, Checkin, SessionRpe, Prompt):
            session.execute(delete(model))
        calendar_state(session)
        profile_factory(
            session, effective_at=datetime.now(UTC) - timedelta(days=365), cycle_anchor=datetime.now(UTC).date()
        )
        session.commit()
    return api_client(router), db_connection


def _observed():
    return (
        datetime.now(UTC)
        .astimezone(ZoneInfo("America/New_York"))
        .replace(hour=9, minute=0, second=0, microsecond=0)
        .isoformat()
    )


def _body(**changes):
    value = {
        "idempotency_key": "fixture-" + uuid.uuid4().hex,
        "kind": "exception",
        "observed_at": _observed(),
        "fatigue": 7,
        "illness": None,
        "gait_change": None,
        "context_tags": [],
        "symptoms": [{"site": "Achilles", "side": "left", "severity": 3.0, "timing": "during"}],
        "note": "synthetic note",
    }
    value.update(changes)
    return value


def _activity(connection, sport="running"):
    activity_id = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(
            Activity(
                id=activity_id,
                start_at=datetime.now(UTC) - timedelta(hours=1),
                original_start=_observed(),
                local_date=datetime.now(UTC).astimezone(ZoneInfo("America/New_York")).date(),
                sport=sport,
                elapsed_s=1800,
                canonical_revision=1,
                resolution_state="resolved",
                field_provenance={},
            )
        )
        session.commit()
    return activity_id


def test_create_replay_patch_and_revision(api_fixture):
    client, connection = api_fixture
    body = _body()
    created = client.post("/api/v1/v2/checkins", json=body)
    assert created.status_code == 201, created.text
    original = created.json()["data"]
    assert "daily_guidance" not in original and set(original["exceptions"]) == {"new_finding_ids", "review_recommended"}
    replay = client.post("/api/v1/v2/checkins", json=body)
    assert replay.status_code == 200 and replay.json()["data"]["id"] == original["id"]
    changed = {**body, "note": "other synthetic note"}
    assert client.post("/api/v1/v2/checkins", json=changed).status_code == 409
    patch = client.patch(
        f"/api/v1/v2/checkins/{original['id']}",
        json={
            "expected_version": 1,
            "note": None,
            "symptoms": [{"site": "Achilles", "side": "left", "severity": 3.1, "timing": "next_morning"}],
        },
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["data"]["version"] == 2
    assert patch.json()["data"]["note"] is None
    assert (
        client.patch(f"/api/v1/v2/checkins/{original['id']}", json={"expected_version": 1, "fatigue": 6}).status_code
        == 409
    )
    again = client.post("/api/v1/v2/checkins", json=body)
    assert again.status_code == 200
    assert {k: v for k, v in again.json()["data"].items() if k != "exceptions"} == {
        k: v for k, v in original.items() if k != "exceptions"
    }
    assert again.json()["data"]["exceptions"]["new_finding_ids"] == []
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        revision = session.scalar(
            select(CheckinRevision).where(CheckinRevision.checkin_id == uuid.UUID(original["id"]))
        )
        assert revision.payload["symptoms"][0]["severity"] == 3.0
        assert revision.payload["note"] == "synthetic note"
        assert session.scalar(select(func.count()).select_from(Checkin)) == 1


def test_expired_matching_prompt_answered_and_mismatch_rejected(api_fixture):
    client, connection = api_fixture
    activity_id = _activity(connection)
    other_id = _activity(connection)
    prompt_id = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(
            Prompt(
                id=prompt_id,
                kind="delayed_symptom",
                activity_id=activity_id,
                opens_at=datetime.now(UTC) - timedelta(days=2),
                closes_at=datetime.now(UTC) - timedelta(days=1),
                status="expired",
            )
        )
        session.commit()
    body = _body(kind="delayed_followup", activity_id=str(other_id), prompt_id=str(prompt_id))
    mismatch = client.post("/api/v1/v2/checkins", json=body)
    assert mismatch.status_code == 422 and mismatch.json()["error"]["code"] == "prompt_subject_mismatch"
    cycling_id = _activity(connection, sport="cycling")
    assert (
        client.post("/api/v1/v2/checkins", json=_body(kind="post_run", activity_id=str(cycling_id))).status_code == 422
    )
    body["activity_id"] = str(activity_id)
    created = client.post("/api/v1/v2/checkins", json=body)
    assert created.status_code == 201, created.text
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        assert session.get(Prompt, prompt_id).status == "answered"
    note_edit = client.patch(
        f"/api/v1/v2/checkins/{created.json()['data']['id']}", json={"expected_version": 1, "note": "updated"}
    )
    assert note_edit.status_code == 200
    assert client.post(f"/api/v1/prompts/{prompt_id}/dismiss").status_code == 409
    rpe_prompt_id = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(
            Prompt(
                id=rpe_prompt_id,
                kind="rpe",
                activity_id=activity_id,
                opens_at=datetime.now(UTC) - timedelta(hours=1),
                status="open",
            )
        )
        stale_open_id = uuid.uuid4()
        session.add(
            Prompt(
                id=stale_open_id,
                kind="missing_activity",
                session_uid=uuid.uuid4(),
                opens_at=datetime.now(UTC) - timedelta(days=2),
                closes_at=datetime.now(UTC) - timedelta(days=1),
                status="open",
            )
        )
        session.commit()
    visible = client.get("/api/v1/prompts").json()["data"]["items"]
    assert str(rpe_prompt_id) in {item["id"] for item in visible}
    assert str(stale_open_id) not in {item["id"] for item in visible}
    post_run = _body(kind="post_run", activity_id=str(activity_id), prompt_id=str(rpe_prompt_id))
    assert client.post("/api/v1/v2/checkins", json=post_run).status_code == 422
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        assert session.get(Prompt, rpe_prompt_id).status == "open"
        session.add(SessionRpe(activity_id=activity_id, rpe=7, source="manual", collected_at=datetime.now(UTC)))
        session.commit()
    assert client.post("/api/v1/v2/checkins", json=post_run).status_code == 201


def test_rpe_manual_wins(api_fixture):
    client, connection = api_fixture
    activity_id = _activity(connection)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(SessionRpe(activity_id=activity_id, rpe=6.5, source="garmin_fit", collected_at=datetime.now(UTC)))
        session.commit()
    manual = client.put(f"/api/v1/activities/{activity_id}/rpe", json={"rpe": 7})
    assert manual.status_code == 200 and manual.json()["data"]["rpe"] == 7
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        rows = session.scalars(select(SessionRpe).where(SessionRpe.activity_id == activity_id)).all()
        assert {(row.source, row.rpe) for row in rows} == {("manual", 7), ("garmin_fit", 6.5)}
    assert client.put(f"/api/v1/activities/{activity_id}/rpe", json={"rpe": 7.11}).status_code == 422


def test_rpe_autocompletion_allows_one_followup_note(api_fixture):
    client, connection = api_fixture
    activity_id = _activity(connection)
    prompt_id = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(
            Prompt(
                id=prompt_id,
                kind="rpe",
                activity_id=activity_id,
                opens_at=datetime.now(UTC) - timedelta(hours=1),
                status="answered",
            )
        )
        session.commit()
    body = _body(
        kind="post_run",
        activity_id=str(activity_id),
        prompt_id=str(prompt_id),
        symptoms=[],
        fatigue=None,
        note="synthetic post-run note",
    )
    assert client.post("/api/v1/v2/checkins", json=body).status_code == 422
    assert client.put(f"/api/v1/activities/{activity_id}/rpe", json={"rpe": 6}).status_code == 200
    created = client.post("/api/v1/v2/checkins", json=body)
    assert created.status_code == 201, created.text
    assert client.post("/api/v1/v2/checkins", json=body).status_code == 200
    duplicate = {**body, "idempotency_key": "another-" + uuid.uuid4().hex}
    assert client.post("/api/v1/v2/checkins", json=duplicate).status_code == 422
    assert (
        client.patch(
            f"/api/v1/v2/checkins/{created.json()['data']['id']}", json={"expected_version": 1, "note": "edited note"}
        ).status_code
        == 200
    )
    delayed_id = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(
            Prompt(
                id=delayed_id,
                kind="delayed_symptom",
                activity_id=activity_id,
                opens_at=datetime.now(UTC) - timedelta(hours=1),
                status="answered",
            )
        )
        session.commit()
    assert (
        client.post(
            "/api/v1/v2/checkins",
            json=_body(kind="delayed_followup", activity_id=str(activity_id), prompt_id=str(delayed_id)),
        ).status_code
        == 422
    )


def test_routes_removed_and_replay_retains_original_payload(api_fixture):
    client, _ = api_fixture
    assert client.get("/api/v1/coach/v2/daily").status_code == 404
    assert client.post("/api/v1/coach/v2/daily/request", json={}).status_code in {404, 405}
    body = _body()
    created = client.post("/api/v1/v2/checkins", json=body)
    assert created.status_code == 201, created.text
    checkin_id = created.json()["data"]["id"]
    patched = client.patch(f"/api/v1/v2/checkins/{checkin_id}", json={"expected_version": 1, "note": "x"})
    assert patched.status_code == 200, patched.text
    replay = client.post("/api/v1/v2/checkins", json=body)
    assert replay.status_code == 200
    original = created.json()["data"]
    replayed = replay.json()["data"]
    assert replayed.pop("exceptions")["new_finding_ids"] == []
    original.pop("exceptions")
    assert replayed == original


@pytest.mark.parametrize("answer", [False, None])
def test_late_workout_response_preserves_explicit_pain_and_replays_once(api_fixture, answer):
    from app.read.workout_feedback import load_workout_feedback

    client, connection = api_fixture
    activity_id = _activity(connection)
    now = datetime.now(UTC)
    end = now - timedelta(hours=60)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        activity = session.get(Activity, activity_id)
        activity.start_at = end - timedelta(minutes=30)
        activity.end_at = end
        prompt = Prompt(
            kind="delayed_symptom",
            activity_id=activity_id,
            opens_at=end + timedelta(hours=16),
            closes_at=end + timedelta(hours=48),
            status="open",
        )
        session.add(prompt)
        session.flush()
        prompt_id = prompt.id
        unread = load_workout_feedback(session, [activity_id], now)[activity_id]
        assert (unread["prompt"]["status"], unread["checkin_id"], unread["pain_reported"]) == ("expired", None, None)
        session.commit()
    body = _body(
        kind="delayed_followup",
        activity_id=str(activity_id),
        prompt_id=str(prompt_id),
        observed_at=now.isoformat(),
        fatigue=None,
        pain_reported=answer,
        gait_change="no",
        symptoms=[],
    )
    created = client.post("/api/v1/v2/checkins", json=body)
    assert created.status_code == 201, created.text
    checkin_id = created.json()["data"]["id"]
    assert created.json()["data"]["pain_reported"] is answer
    replay = client.post("/api/v1/v2/checkins", json=body)
    assert replay.status_code == 200 and replay.json()["data"]["id"] == checkin_id
    duplicate = client.post(
        "/api/v1/v2/checkins",
        json={**body, "idempotency_key": str(uuid.uuid4()), "prompt_id": None},
    )
    assert duplicate.status_code == 409
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        response = load_workout_feedback(session, [activity_id], datetime.now(UTC))[activity_id]
        assert response["checkin_id"] == uuid.UUID(checkin_id)
        assert response["prompt"]["status"] == "answered"
        assert response["pain_reported"] is answer
        assert response["gait_change"] == "no"
        assert response["hours_after_end"] == 60
        assert session.scalar(select(func.count()).select_from(Checkin).where(Checkin.activity_id == activity_id)) == 1


def test_delayed_feedback_can_be_recorded_without_a_reminder_after_the_window_opens(api_fixture):
    from app.read.workout_feedback import load_workout_feedback

    client, connection = api_fixture
    activity_id = _activity(connection)
    now = datetime.now(UTC)
    end = now - timedelta(hours=20)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        activity = session.get(Activity, activity_id)
        activity.start_at = end - timedelta(minutes=30)
        activity.end_at = end
        session.commit()
    body = _body(
        kind="delayed_followup",
        activity_id=str(activity_id),
        observed_at=(end - timedelta(hours=1)).isoformat(),
        pain_reported=False,
        symptoms=[],
    )
    too_early = client.post("/api/v1/v2/checkins", json=body)
    assert too_early.status_code == 422
    assert too_early.json()["error"]["code"] == "delayed_response_not_due"
    created = client.post("/api/v1/v2/checkins", json={**body, "observed_at": now.isoformat()})
    assert created.status_code == 201, created.text
    checkin_id = created.json()["data"]["id"]
    patched = client.patch(
        f"/api/v1/v2/checkins/{checkin_id}",
        json={"expected_version": 1, "observed_at": body["observed_at"]},
    )
    assert patched.status_code == 422
    assert patched.json()["error"]["code"] == "delayed_response_not_due"
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        response = load_workout_feedback(session, [activity_id], datetime.now(UTC))[activity_id]
        assert response["prompt"] is None
        assert response["pain_reported"] is False
        assert response["hours_after_end"] == 20
