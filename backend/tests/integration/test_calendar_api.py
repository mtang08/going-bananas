"""Calendar lineage and completion behavior on the guarded synthetic test database."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.api.calendar import get_completion_assessor, router
from app.api.core import router as core_router
from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.coach_v2_models import CoachProposal, CoachSnapshot
from app.exception_models import ExceptionPatch
from app.models import Activity, AppState, ProfileVersion
from app.read.calendar import latest_revisions
from app.services import calendar
from app.services.matching import rematch_dates


def _headers():
    return {"X-Local-Request": "1", "Origin": "http://testserver"}


@pytest.fixture
def calendar_fixture(
    monkeypatch, db_connection, metrics_disabled, session_factory, api_client, profile_factory, calendar_state
):
    # This service-seam suite invokes matching/its injected assessor explicitly.
    # Real transactional refresh is covered by test_metrics_flow.
    monkeypatch.setattr(calendar, "calendar_today", lambda session, now=None: date(2026, 11, 16))
    with session_factory() as session:
        session.execute(delete(SessionCompletion))
        session.execute(delete(CalendarSessionRevision))
        session.execute(delete(CalendarVersion))
        calendar_state(session, reset_head=True)
        profile_factory(session)
        session.commit()

    def assessor():
        def assess(session, uid):
            row = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == uid))
            row.status = "completed_modified"
            row.version += 1

        return assess

    client = api_client(router, overrides={get_completion_assessor: assessor})
    return client, db_connection, client.app


def _bootstrap(client):
    response = client.post(
        "/api/v1/calendar/bootstrap",
        json={"anchor_date": "2026-11-02", "start_date": "2026-11-16", "pattern": {"quality": 1, "long": 1}},
        headers=_headers(),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_calendar_week_defaults_to_current_week(calendar_fixture):
    client, _, _ = calendar_fixture
    _bootstrap(client)

    response = client.get("/api/v1/calendar/week")
    assert response.status_code == 200, response.text
    week = response.json()["data"]
    start, end = "2026-11-16", "2026-11-22"
    assert (week["start"], week["end"], week["today"]) == (start, end, start)
    assert week["sessions"]
    assert all(start <= row["local_date"] <= end for row in week["sessions"])

    bounded = client.get(f"/api/v1/calendar?start={start}&end={end}").json()["data"]
    for field in ("sessions", "completions", "last_planned_date", "recorded_runs"):
        assert week[field] == bounded[field]


@pytest.mark.parametrize("start", ["2026-11-09", "2026-12-28"])
def test_calendar_week_before_and_after_the_plan(calendar_fixture, start):
    client, _, _ = calendar_fixture
    _bootstrap(client)

    response = client.get("/api/v1/calendar/week", params={"start": start})
    assert response.status_code == 200, response.text
    week = response.json()["data"]
    assert week["sessions"] == []
    assert week["head"] == 1
    assert week["last_planned_date"] is not None


@pytest.mark.parametrize(("start", "code"), [("2026-11-17", "invalid_week_start"), ("not-a-date", "validation_error")])
def test_calendar_week_rejects_non_monday(calendar_fixture, start, code):
    client, _, _ = calendar_fixture

    response = client.get("/api/v1/calendar/week", params={"start": start})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code


def test_calendar_week_reads_requested_version(calendar_fixture):
    client, _, _ = calendar_fixture
    _bootstrap(client)

    response = client.get("/api/v1/calendar/week?start=2026-11-16&version=1")
    assert response.status_code == 200, response.text
    week = response.json()["data"]
    assert week["version"] == 1
    bounded = client.get("/api/v1/calendar?start=2026-11-16&end=2026-11-22&version=1").json()["data"]
    assert week["sessions"] == bounded["sessions"]


def test_recorded_runs_before_plan_are_visible_without_creating_completions(calendar_fixture):
    client, connection, _ = calendar_fixture
    _bootstrap(client)
    earlier, same_day, linked = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        for uid, day in ((earlier, 10), (same_day, 16), (linked, 18)):
            session.add(
                Activity(
                    id=uid,
                    start_at=datetime(2026, 11, day, 13, tzinfo=UTC),
                    original_start=f"2026-11-{day}T13:00:00Z",
                    local_date=date(2026, 11, day),
                    sport="running",
                    distance_m=6740,
                    timer_s=2400,
                    canonical_revision=1,
                    resolution_state="resolved",
                    field_provenance={},
                )
            )
        session.commit()
    planned = client.get("/api/v1/calendar?start=2026-11-10&end=2026-11-18").json()["data"]
    uid = next(
        row["session_uid"] for row in planned["sessions"] if row["kind"] == "run" and row["local_date"] == "2026-11-18"
    )
    response = client.put(f"/api/v1/calendar/completions/{uid}", json={"activity_id": str(linked)}, headers=_headers())
    assert response.status_code == 200, response.text
    result = client.get("/api/v1/calendar?start=2026-11-10&end=2026-11-18").json()["data"]
    runs = {row["activity_id"]: row for row in result["recorded_runs"]}
    assert runs[str(earlier)] == {
        "activity_id": str(earlier),
        "local_date": "2026-11-10",
        "distance_m": 6740,
        "timer_s": 2400,
    }
    assert str(same_day) in runs  # Awaiting a match also remains visible.
    assert str(linked) not in runs  # Already displayed through its completion.
    assert len(result["completions"]) == 1 and result["head"] == 1
    bounded = client.get("/api/v1/calendar?start=2026-11-11&end=2026-11-15").json()["data"]
    assert not any(row["activity_id"] in {str(earlier), str(same_day), str(linked)} for row in bounded["recorded_runs"])


def test_bootstrap_move_old_view_stale_head_and_diff(calendar_fixture):
    client, connection, _ = calendar_fixture
    empty = client.get("/api/v1/calendar?start=2026-11-16&end=2026-11-29").json()["data"]
    assert empty["head"] == 0 and empty["sessions"] == [] and empty["last_planned_date"] is None
    assert _bootstrap(client)["version"] == 1
    first = client.get("/api/v1/calendar?start=2026-11-16&end=2026-11-29").json()["data"]
    runs = [item for item in first["sessions"] if item["kind"] == "run"]
    assert [item["local_date"] for item in runs] == [f"2026-11-{day}" for day in (16, 18, 20, 22, 24, 26, 28)]
    uid = runs[1]["session_uid"]
    move = client.post(
        "/api/v1/calendar/edits",
        json={
            "expected_head": 1,
            "edits": [{"op": "move", "session_uid": uid, "fields": {"local_date": "2026-11-19"}}],
        },
        headers=_headers(),
    )
    assert move.status_code == 201, move.text
    assert move.json()["data"]["version"] == 2
    old = client.get("/api/v1/calendar?start=2026-11-16&end=2026-11-29&version=1").json()["data"]
    new = client.get("/api/v1/calendar?start=2026-11-16&end=2026-11-29").json()["data"]
    assert next(item for item in old["sessions"] if item["session_uid"] == uid)["local_date"] == "2026-11-18"
    assert next(item for item in new["sessions"] if item["session_uid"] == uid)["local_date"] == "2026-11-19"
    assert new["last_planned_date"] == "2026-11-28"
    assert (
        client.get("/api/v1/calendar?start=2026-11-16&end=2026-11-16").json()["data"]["last_planned_date"]
        == "2026-11-28"
    )
    changes = client.get("/api/v1/calendar/diff?from=1&to=2").json()["data"]["changes"]
    assert len(changes) == 1 and changes[0]["op"] == "move" and changes[0]["session_uid"] == uid
    stale = client.post(
        "/api/v1/calendar/edits",
        json={
            "expected_head": 1,
            "edits": [{"op": "move", "session_uid": uid, "fields": {"local_date": "2026-11-20"}}],
        },
        headers=_headers(),
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "calendar_head_moved"
    noop = client.post(
        "/api/v1/calendar/edits",
        json={
            "expected_head": 2,
            "edits": [{"op": "move", "session_uid": uid, "fields": {"local_date": "2026-11-19"}}],
        },
        headers=_headers(),
    )
    assert noop.status_code == 422 and noop.json()["error"]["code"] == "edit_no_change"
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        rows = session.scalars(
            select(CalendarSessionRevision)
            .where(CalendarSessionRevision.session_uid == uuid.UUID(uid))
            .order_by(CalendarSessionRevision.revision)
        ).all()
        assert len(rows) == 2 and rows[0].id != rows[1].id


def test_advisory_lock_refreshes_cached_head(calendar_fixture):
    _, connection, _ = calendar_fixture
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        cached = session.get(AppState, 1)
        assert cached.calendar_head_version == 0
        connection.execute(text("UPDATE app_state SET calendar_head_version=1 WHERE id=1"))
        with pytest.raises(HTTPException) as error:
            calendar.lock_calendar(session, expected_head=0)
        assert error.value.detail["code"] == "calendar_head_moved"


def test_completion_assessed_after_flush_and_rollback_protects_link(calendar_fixture):
    client, connection, _ = calendar_fixture
    _bootstrap(client)
    first = client.get("/api/v1/calendar?start=2026-11-16&end=2026-11-29").json()["data"]
    runs = [item for item in first["sessions"] if item["kind"] == "run"]
    linked_uid = runs[0]["session_uid"]
    future_uid = runs[1]["session_uid"]
    activity_id = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(
            Activity(
                id=activity_id,
                start_at=datetime(2026, 11, 16, 13, tzinfo=UTC),
                original_start="2026-11-16T13:00:00Z",
                local_date=date(2026, 11, 16),
                sport="running",
                canonical_revision=1,
                resolution_state="resolved",
                field_provenance={},
            )
        )
        session.commit()
    linked = client.put(
        f"/api/v1/calendar/completions/{linked_uid}", json={"activity_id": str(activity_id)}, headers=_headers()
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["data"]["status"] == "completed_modified"
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        stored = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == uuid.UUID(linked_uid)))
        assert (stored.status, stored.version) == (linked.json()["data"]["status"], linked.json()["data"]["version"])
    assert (
        client.put(
            f"/api/v1/calendar/completions/{future_uid}", json={"activity_id": str(activity_id)}, headers=_headers()
        ).status_code
        == 409
    )
    assert (
        client.put(
            f"/api/v1/calendar/completions/{future_uid}", json={"status": "completed_as_planned"}, headers=_headers()
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/v1/calendar/completions/{future_uid}", json={"status": "skipped"}, headers=_headers()
        ).status_code
        == 200
    )
    # A mixed rollback restores an unprotected future edit and preserves the linked run.
    move = client.post(
        "/api/v1/calendar/edits",
        json={
            "expected_head": 1,
            "edits": [{"op": "move", "session_uid": runs[2]["session_uid"], "fields": {"local_date": "2026-11-21"}}],
        },
        headers=_headers(),
    )
    assert move.status_code == 201
    restored = client.post(
        "/api/v1/calendar/rollback",
        json={"expected_head": 2, "to_version": 1, "reason": "restore synthetic fixture"},
        headers=_headers(),
    )
    assert restored.status_code == 201, restored.text
    assert restored.json()["data"]["version"] == 3
    assert client.get("/api/v1/calendar?start=2026-11-16&end=2026-11-29").json()["data"]["head"] == 3


def test_demo_history_uuid(calendar_fixture):
    client, connection, _ = calendar_fixture
    past = client.post(
        "/api/v1/calendar/bootstrap",
        json={"anchor_date": "2026-11-02", "start_date": "2026-11-15", "pattern": {"quality": 1, "long": 1}},
        headers=_headers(),
    )
    assert past.status_code == 422 and past.json()["error"]["code"] == "protected_session"
    explicit = uuid.UUID("00000000-0000-4000-8000-000000000042")
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        result = calendar.seed_demo_calendar(
            session,
            anchor_date=date(2026, 11, 2),
            start_date=date(2026, 11, 16),
            now=datetime(2026, 11, 16, 17, tzinfo=UTC),
            history_edits=[
                {
                    "op": "add",
                    "session_uid": explicit,
                    "fields": {
                        "local_date": date(2026, 11, 14),
                        "kind": "run",
                        "recipe_id": "REC003",
                        "intent": "Intervals",
                        "planned_duration_s": 60,
                        "structure": [{"type": "work", "duration_type": "time", "duration_value": 60, "target": None}],
                    },
                }
            ],
        )
        assert result["version"] == 2
        assert explicit not in {item["session_uid"] for item in calendar.state_at(session, 1)}
        assert explicit in {item["session_uid"] for item in calendar.state_at(session, 2)}
        session.rollback()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        result = calendar.seed_demo_calendar(
            session,
            anchor_date=date(2026, 11, 2),
            start_date=date(2026, 11, 16),
            now=datetime(2026, 11, 16, 17, tzinfo=UTC),
            history_edits=[],
        )
        assert result["version"] == 1
        assert session.scalar(select(func.count()).select_from(CalendarVersion)) == 1
        session.rollback()


def test_rollback_keeps_deleted_historical_target_absent_and_restores_future(calendar_fixture):
    client, connection, _ = calendar_fixture
    historical_uid = uuid.UUID("00000000-0000-4000-8000-000000000042")
    with Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
        calendar.seed_demo_calendar(
            session,
            anchor_date=date(2026, 11, 2),
            start_date=date(2026, 11, 16),
            now=datetime(2026, 11, 16, 17, tzinfo=UTC),
            history_edits=[
                {
                    "op": "add",
                    "session_uid": historical_uid,
                    "fields": {
                        "local_date": date(2026, 11, 14),
                        "kind": "run",
                        "recipe_id": "REC003",
                        "intent": "Historical fixture",
                        "planned_duration_s": 60,
                    },
                }
            ],
        )
        head2 = latest_revisions(session, 2)
        future = next(row for row in head2.values() if row.local_date == date(2026, 11, 18) and row.kind == "run")
        state = session.get(AppState, 1)
        state.calendar_head_version = 3
        session.add(CalendarVersion(number=3, parent_number=2, kind="manual_edit", actor="system"))
        session.flush()
        historical = head2[historical_uid]
        session.add(
            CalendarSessionRevision(
                session_uid=historical_uid,
                revision=2,
                calendar_version_number=3,
                deleted=True,
                certainty="committed",
                **calendar._fields(historical),
            )
        )
        session.add(
            CalendarSessionRevision(
                session_uid=future.session_uid,
                revision=2,
                calendar_version_number=3,
                deleted=False,
                certainty="committed",
                **{**calendar._fields(future), "local_date": date(2026, 11, 19)},
            )
        )
        session.commit()
    restored = client.post(
        "/api/v1/calendar/rollback",
        json={"expected_head": 3, "to_version": 2, "reason": "preserve historical deletion"},
        headers=_headers(),
    )
    assert restored.status_code == 201, restored.text
    assert restored.json()["data"]["preserved_session_uids"] == [str(historical_uid)]
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        current = {item["session_uid"]: item for item in calendar.state_at(session, 4)}
        assert historical_uid not in current
        assert current[future.session_uid]["local_date"] == date(2026, 11, 18)
    protected_only = client.post(
        "/api/v1/calendar/rollback",
        json={"expected_head": 4, "to_version": 2, "reason": "still historical"},
        headers=_headers(),
    )
    assert protected_only.status_code == 422
    assert protected_only.json()["error"]["code"] == "rollback_no_change"


def test_assessor_unknown_is_valid_and_failed_commit_has_no_success(calendar_fixture, monkeypatch):
    client, connection, api = calendar_fixture
    _bootstrap(client)
    uid = next(
        item["session_uid"]
        for item in client.get("/api/v1/calendar?start=2026-11-16&end=2026-11-29").json()["data"]["sessions"]
        if item["kind"] == "run"
    )
    activity_id = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(
            Activity(
                id=activity_id,
                start_at=datetime(2026, 11, 16, 13, tzinfo=UTC),
                original_start="2026-11-16T13:00:00Z",
                local_date=date(2026, 11, 16),
                sport="running",
                canonical_revision=1,
                resolution_state="resolved",
                field_provenance={},
            )
        )
        session.commit()

    def unknown_assessor():
        def assess(session, session_uid):
            row = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == session_uid))
            row.status = "unknown"

        return assess

    api.dependency_overrides[get_completion_assessor] = unknown_assessor
    response = client.put(
        f"/api/v1/calendar/completions/{uid}", json={"activity_id": str(activity_id)}, headers=_headers()
    )
    assert response.status_code == 200 and response.json()["data"]["status"] == "unknown"
    uid2 = next(
        item["session_uid"]
        for item in client.get("/api/v1/calendar?start=2026-11-16&end=2026-11-29").json()["data"]["sessions"]
        if item["kind"] == "run" and item["session_uid"] != uid
    )
    original_commit = Session.commit

    def fail_commit(self):
        raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    try:
        with TestClient(api, raise_server_exceptions=False) as quiet_client:
            failed = quiet_client.put(
                f"/api/v1/calendar/completions/{uid2}", json={"status": "skipped"}, headers=_headers()
            )
        assert failed.status_code == 500
        assert "session_uid" not in failed.text
    finally:
        monkeypatch.setattr(Session, "commit", original_commit)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        assert session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == uuid.UUID(uid2))) is None


def test_calendar_change_marks_pending_proposal_stale(calendar_fixture):
    client, connection, _ = calendar_fixture
    _bootstrap(client)
    proposal_id = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        snapshot = CoachSnapshot(
            operation="review_rolling_plan",
            as_of=date(2026, 11, 16),
            generated_at=datetime(2026, 11, 16, tzinfo=UTC),
            calendar_version_number=1,
            data_revision=0,
            payload={},
            source_fingerprint="a" * 64,
            source_versions={},
            kb_digest="b" * 64,
            payload_sha256="c" * 64,
            kb_package_version="fixture",
            kb_routes={},
            approx_tokens=1,
        )
        session.add(snapshot)
        session.flush()
        session.add(
            CoachProposal(
                id=proposal_id,
                operation="review_rolling_plan",
                snapshot_id=snapshot.id,
                base_calendar_version=1,
                status="pending",
                submitted_at=datetime(2026, 11, 16, tzinfo=UTC),
                headline="synthetic",
                why=[{"kind": "observation", "text": "synthetic"}],
                confidence={},
                evidence_ids=[],
                policy_ids=[],
                recipe_ids=[],
                payload={},
                skill_version="fixture",
                input_hash="d" * 64,
            )
        )
        session.commit()
    uid = next(
        item["session_uid"]
        for item in client.get("/api/v1/calendar?start=2026-11-16&end=2026-11-29").json()["data"]["sessions"]
        if item["kind"] == "run" and item["local_date"] == "2026-11-18"
    )
    response = client.post(
        "/api/v1/calendar/edits",
        json={
            "expected_head": 1,
            "edits": [{"op": "move", "session_uid": uid, "fields": {"local_date": "2026-11-19"}}],
        },
        headers=_headers(),
    )
    assert response.status_code == 201
    assert response.json()["data"]["stale_proposals"] == [str(proposal_id)]
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        assert session.get(CoachProposal, proposal_id).status == "stale"


def test_calendar_sessions_carry_exception_patch(calendar_fixture):
    client, connection, _ = calendar_fixture
    _bootstrap(client)
    uid = next(
        item["session_uid"]
        for item in client.get("/api/v1/calendar?start=2026-11-16&end=2026-11-29").json()["data"]["sessions"]
        if item["kind"] == "run" and item["local_date"] == "2026-11-18"
    )
    move = client.post(
        "/api/v1/calendar/edits",
        json={
            "expected_head": 1,
            "edits": [{"op": "move", "session_uid": uid, "fields": {"local_date": "2026-11-19"}}],
        },
        headers=_headers(),
    )
    assert move.status_code == 201 and move.json()["data"]["version"] == 2
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        snapshot = CoachSnapshot(
            operation="exception_review",
            as_of=date(2026, 11, 16),
            generated_at=datetime(2026, 11, 16, tzinfo=UTC),
            calendar_version_number=1,
            data_revision=0,
            payload={},
            source_fingerprint="a" * 64,
            source_versions={},
            kb_digest="b" * 64,
            payload_sha256="c" * 64,
            kb_package_version="fixture",
            kb_routes={},
            approx_tokens=1,
        )
        session.add(snapshot)
        session.flush()
        proposal = CoachProposal(
            operation="exception_review",
            snapshot_id=snapshot.id,
            base_calendar_version=1,
            status="accepted",
            submitted_at=datetime(2026, 11, 16, tzinfo=UTC),
            decided_at=datetime(2026, 11, 16, tzinfo=UTC),
            headline="synthetic",
            why=[{"kind": "observation", "text": "synthetic"}],
            confidence={},
            evidence_ids=[],
            policy_ids=[],
            recipe_ids=[],
            payload={},
            skill_version="fixture",
            input_hash="d" * 64,
        )
        session.add(proposal)
        session.flush()
        patch = ExceptionPatch(
            proposal_id=proposal.id,
            calendar_version_number=2,
            category="accumulated_fatigue",
            severity="caution",
            ladder_level="next_session",
            window_start=date(2026, 11, 16),
            window_end=date(2026, 11, 18),
            reassess_on=date(2026, 11, 19),
            monitor=["Fatigue"],
            return_criteria=["Fatigue below 5"],
            escalate_criteria=["Fatigue rising"],
            status="open",
        )
        session.add(patch)
        session.commit()
        patch_id, proposal_id = patch.id, proposal.id
    head = client.get("/api/v1/calendar?start=2026-11-16&end=2026-11-29").json()["data"]["sessions"]
    moved = next(item for item in head if item["session_uid"] == uid)
    assert moved["exception_patch"] == {
        "patch_id": str(patch_id),
        "proposal_id": str(proposal_id),
        "reassess_on": "2026-11-19",
        "status": "open",
    }
    assert all(item["exception_patch"] is None for item in head if item["session_uid"] != uid)
    old = client.get("/api/v1/calendar?start=2026-11-16&end=2026-11-29&version=1").json()["data"]["sessions"]
    assert next(item for item in old if item["session_uid"] == uid)["exception_patch"] is None
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.get(ExceptionPatch, patch_id).status = "resolved"
        session.commit()
    head = client.get("/api/v1/calendar?start=2026-11-16&end=2026-11-29").json()["data"]["sessions"]
    assert next(item for item in head if item["session_uid"] == uid)["exception_patch"]["status"] == "resolved"


def _completion_test_run(session, day):
    start = datetime(day.year, day.month, day.day, 13, tzinfo=UTC)
    activity_id = uuid.uuid4()
    session.add(
        Activity(
            id=activity_id,
            start_at=start,
            original_start=start.isoformat(),
            local_date=day,
            sport="running",
            timer_s=1800,
            distance_m=5000,
            canonical_revision=1,
            resolution_state="resolved",
            field_provenance={},
        )
    )
    session.flush()
    return activity_id


@pytest.mark.parametrize("holder_method", ["none", "auto_same_day", "explicit"])
def test_explicit_link_respects_existing_subject_holder(calendar_fixture, holder_method):
    client, connection, api = calendar_fixture
    _bootstrap(client)
    runs = [row for row in client.get("/api/v1/calendar").json()["data"]["sessions"] if row["kind"] == "run"]
    target = runs[0]
    holder = next(row for row in runs if row["local_date"] != target["local_date"])
    is_extra = holder_method == "none"
    holder_uid = uuid.uuid4() if is_extra else uuid.UUID(holder["session_uid"])
    activity_day = date.fromisoformat((target if is_extra else holder)["local_date"])
    stamped_at = datetime(2026, 11, 16, 12, tzinfo=UTC)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        activity_id = _completion_test_run(session, activity_day)
        session.add(
            SessionCompletion(
                session_uid=holder_uid,
                activity_id=activity_id,
                status="extra" if is_extra else "completed_modified",
                match_method=holder_method,
                version=3,
                input_version=2,
                updated_at=stamped_at,
            )
        )
        session.commit()

    endpoint = f"/api/v1/calendar/completions/{target['session_uid']}"
    body = {"activity_id": str(activity_id)}

    if is_extra:

        def failing_assessor():
            def assess(_session, _uid):
                raise RuntimeError("synthetic assessment failure")

            return assess

        previous_assessor = api.dependency_overrides[get_completion_assessor]
        api.dependency_overrides[get_completion_assessor] = failing_assessor
        with TestClient(api, raise_server_exceptions=False) as failing_client:
            failure = failing_client.put(endpoint, json=body, headers=_headers())
        api.dependency_overrides[get_completion_assessor] = previous_assessor
        assert failure.status_code == 500
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            held = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == holder_uid))
            assert (held.activity_id, held.status) == (activity_id, "extra")
            assert (
                session.scalar(
                    select(SessionCompletion).where(SessionCompletion.session_uid == uuid.UUID(target["session_uid"]))
                )
                is None
            )

    response = client.put(endpoint, json=body, headers=_headers())
    if holder_method == "explicit":
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "subject_already_linked"
    else:
        assert response.status_code == 200, response.text
        assert response.json()["data"]["activity_id"] == str(activity_id)
        assert response.json()["data"]["match_method"] == ("explicit" if is_extra else "confirmed_move")

    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        held = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == holder_uid))
        if is_extra:
            assert held is None
        elif holder_method == "auto_same_day":
            assert (held.activity_id, held.strong_workout_id, held.manual_session_id) == (None, None, None)
            assert (held.status, held.match_method) == ("unknown", "none")
            assert (held.version, held.input_version) == (4, 3)
            assert held.updated_at > stamped_at
        else:
            assert (held.activity_id, held.match_method, held.version) == (activity_id, "explicit", 3)


def test_unskip_removes_completion_and_restores_auto_match(calendar_fixture):
    client, connection, _ = calendar_fixture
    _bootstrap(client)
    plan = next(row for row in client.get("/api/v1/calendar").json()["data"]["sessions"] if row["kind"] == "run")
    uid = uuid.UUID(plan["session_uid"])
    day = date.fromisoformat(plan["local_date"])
    endpoint = f"/api/v1/calendar/completions/{uid}"

    skipped = client.put(endpoint, json={"status": "skipped"}, headers=_headers())
    assert skipped.status_code == 200, skipped.text
    version = skipped.json()["data"]["version"]

    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        activity_id = _completion_test_run(session, day)
        assert uid not in rematch_dates(session, {day})
        session.commit()

    stale = client.put(endpoint, json={"status": "unknown", "expected_version": version + 1}, headers=_headers())
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"

    before = client.get("/api/v1/calendar").json()
    unskipped = client.put(endpoint, json={"status": "unknown", "expected_version": version}, headers=_headers())
    assert unskipped.status_code == 200, unskipped.text
    assert unskipped.json()["data"] is None
    assert unskipped.json()["data_revision"] == before["data_revision"] + 1

    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        query = select(SessionCompletion).where(SessionCompletion.session_uid == uid)
        assert session.scalar(query) is None
        assert uid in rematch_dates(session, {day})
        session.commit()
        matched = session.scalar(query)
        assert matched.activity_id == activity_id
        assert matched.match_method == "auto_same_day"


def test_explicit_link_uses_current_athlete_timezone(calendar_fixture):
    client, connection, _ = calendar_fixture
    _bootstrap(client)
    target = next(s for s in client.get("/api/v1/calendar").json()["data"]["sessions"] if s["kind"] == "run")
    day = date.fromisoformat(target["local_date"])
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        activity_id = _completion_test_run(session, day + timedelta(days=1))
        activity = session.get(Activity, activity_id)
        activity.start_at = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=UTC) + timedelta(
            hours=6
        )
        activity.original_start = activity.start_at.isoformat()
        session.flush()
        version = session.scalar(select(func.max(ProfileVersion.version))) + 1
        session.add(
            ProfileVersion(
                version=version,
                effective_at=datetime.now(UTC),
                timezone="America/Los_Angeles",
                facts={},
                preferences={},
                unknowns=[],
            )
        )
        session.commit()
    response = client.put(
        f"/api/v1/calendar/completions/{target['session_uid']}",
        json={"activity_id": str(activity_id)},
        headers=_headers(),
    )
    assert response.status_code == 200
    assert response.json()["data"]["match_method"] == "explicit"
    assert response.json()["data"]["local_date"] == day.isoformat()


def test_self_report_undo_and_later_import(calendar_fixture, monkeypatch):
    client, connection, _ = calendar_fixture
    _bootstrap(client)
    plan = next(s for s in client.get("/api/v1/calendar").json()["data"]["sessions"] if s["kind"] == "run")
    day = date.fromisoformat(plan["local_date"])
    monkeypatch.setattr(calendar, "calendar_today", lambda session, now=None: day)
    uid = uuid.UUID(plan["session_uid"])
    endpoint = f"/api/v1/calendar/completions/{uid}"

    def mark():
        response = client.put(
            endpoint, json={"status": "completed_as_planned", "expected_version": 0}, headers=_headers()
        )
        assert response.status_code == 200, response.text
        row = response.json()["data"]
        assert row["match_method"] == "user_marked" and row["activity_id"] is None
        assert row["status"] == "completed_as_planned"
        return row["version"]

    version = mark()
    assert (
        client.put(endpoint, json={"status": "unknown", "expected_version": version}, headers=_headers()).json()["data"]
        is None
    )
    mark()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        activity_id = _completion_test_run(session, day)
        assert uid in rematch_dates(session, {day})
        matched = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == uid))
        assert matched.activity_id == activity_id and matched.match_method == "auto_same_day"


def test_rehab_daily_limit_and_independent_manual_completion(calendar_fixture):
    client, _, _ = calendar_fixture
    _bootstrap(client)

    def add(slot, duration):
        return {
            "op": "add",
            "fields": {
                "local_date": "2026-11-16",
                "slot": slot,
                "kind": "rehab",
                "intent": "Calf routine",
                "planned_duration_s": duration,
            },
        }

    invalid = client.post(
        "/api/v1/calendar/edits", json={"expected_head": 1, "edits": [add(4, None)]}, headers=_headers()
    )
    assert invalid.status_code == 422
    over = client.post(
        "/api/v1/calendar/edits", json={"expected_head": 1, "edits": [add(4, 600), add(5, 301)]}, headers=_headers()
    )
    assert over.status_code == 422 and over.json()["error"]["code"] == "rehab_daily_limit"
    added = client.post(
        "/api/v1/calendar/edits", json={"expected_head": 1, "edits": [add(4, 600), add(5, 300)]}, headers=_headers()
    )
    assert added.status_code == 201, added.text
    week = client.get("/api/v1/calendar/week").json()["data"]
    rehab = [s for s in week["sessions"] if s["kind"] == "rehab"]
    assert len(rehab) == 2
    completed = client.put(
        f"/api/v1/calendar/completions/{rehab[0]['session_uid']}",
        json={"status": "completed_as_planned"},
        headers=_headers(),
    )
    assert completed.status_code == 200, completed.text
    week = client.get("/api/v1/calendar/week").json()["data"]
    assert [c["session_uid"] for c in week["completions"] if c["status"] == "completed_as_planned"] == [
        rehab[0]["session_uid"]
    ]


def test_recorded_dated_limit_flags_existing_runs_and_blocks_conflicting_edits(calendar_fixture, api_client):
    client, _, _ = calendar_fixture
    _bootstrap(client)
    profile_client = api_client(core_router)
    initial = profile_client.get("/api/v1/profile").json()["data"]
    version = initial.pop("version")
    response = profile_client.put(
        "/api/v1/profile",
        json={
            **initial,
            "expected_version": version,
            "facts": {
                **initial["facts"],
                "clinical_restriction": "Follow the existing symptom limits.",
                "running_restriction": {
                    "starts_on": "2026-11-16",
                    "ends_on": "2026-11-18",
                    "review_on": "2026-11-17",
                    "max_duration_s": 900,
                    "source": "Athlete",
                },
            },
        },
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["facts"]["clinical_restriction"] == "Follow the existing symptom limits."
    sessions = client.get("/api/v1/calendar/week").json()["data"]["sessions"]
    row = next(item for item in sessions if item["kind"] == "run" and item["local_date"] == "2026-11-18")
    assert "900 s" in row["running_restriction_conflict"]

    def edit(op: str, fields: dict, head: int = 1):
        return client.post(
            "/api/v1/calendar/edits",
            json={"expected_head": head, "edits": [{"op": op, "session_uid": row["session_uid"], "fields": fields}]},
            headers=_headers(),
        )

    blocked = edit("modify", {"planned_duration_s": 1000 if row["planned_duration_s"] is None else 5000})
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["error"]["code"] == "running_restriction"
    assert "900 s" in blocked.json()["error"]["message"]
    assert edit("modify", {"planned_duration_s": 900}).status_code == 201
    assert edit("move", {"local_date": "2026-11-19", "planned_duration_s": 1600}, head=2).status_code == 201
