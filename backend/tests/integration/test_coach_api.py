"""Explicit review API against synthetic proposal and calendar state."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.coach import resolve_kb
from app.calendar_models import CalendarSessionRevision, CalendarVersion
from app.coach_v2_models import CoachProposal, CoachSnapshot
from app.exception_models import ExceptionFinding
from app.models import AppState
from app.read.strength_omissions import accepted_strength_omissions
from app.services import calendar
from app.services.decision_inputs import VerifiedKnowledge, collect_decision_inputs
from app.services.profile import current_profile
from app.services.proposals.lifecycle import submit_proposal
from app.services.snapshot.build import build_snapshot
from app.services.strength_routine import replace_routine, routine_view

NOW = datetime(2026, 11, 16, 15, tzinfo=UTC)
TODAY = date(2026, 11, 16)
KB = VerifiedKnowledge("0" * 64, (), (), frozenset({"P001"}), frozenset({"REC001"}), frozenset({"E-AER-01"}))


def _resolve(selection: tuple[dict, ...]) -> VerifiedKnowledge:
    assert selection == ()
    return KB


def _snapshot(session: Session, operation: str = "review_rolling_plan") -> tuple[CoachSnapshot, uuid.UUID]:
    state = session.get(AppState, 1)
    assert state is not None
    rows = calendar.state_at(session, state.calendar_head_version)
    run_uid = next(row["session_uid"] for row in rows if row["kind"] == "run")
    inputs = collect_decision_inputs(session, operation, TODAY, now=NOW, kb=KB)
    snapshot = CoachSnapshot(
        operation=operation,
        as_of=TODAY,
        generated_at=NOW - timedelta(hours=1),
        calendar_version_number=state.calendar_head_version,
        block_version_id=None,
        data_revision=state.data_revision,
        payload={"snapshot_meta": {"safety_guard": inputs["safety_guard"], "knowledge": {"selected_records": []}}},
        source_fingerprint=inputs["source_fingerprint"],
        source_versions=inputs["source_versions"],
        kb_digest=KB.digest,
        payload_sha256="0" * 64,
        kb_package_version="test",
        kb_routes=[],
        approx_tokens=0,
    )
    session.add(snapshot)
    session.flush()
    return snapshot, run_uid


def _doc(snapshot: CoachSnapshot, uid: uuid.UUID) -> dict:
    return {
        "schema_version": "coach_proposal.v1",
        "operation": snapshot.operation,
        "snapshot_id": str(snapshot.id),
        "base_calendar_version": snapshot.calendar_version_number,
        "base_block_version_id": None,
        "summary": "Add easy time",
        "rationale": "Ready for a small increase",
        "confidence": {"decision": "moderate", "evidence": "moderate", "data": "moderate"},
        "changes": [
            {
                "change_id": "c1",
                "op": "modify",
                "session_uid": str(uid),
                "after": {"planned_duration_s": 2400},
                "reason": "Progression",
            }
        ],
        "preserved": [],
        "evidence_ids": ["E-AER-01"],
        "policy_ids": ["P001"],
        "recipe_ids": ["REC001"],
        "skill_version": "running-coach.v1",
    }


@pytest.fixture
def api(proposal_session, monkeypatch):
    from fastapi import FastAPI, HTTPException
    from fastapi.exceptions import RequestValidationError
    from fastapi.testclient import TestClient

    from app.api import coach
    from app.db import get_session
    from app.main import handle_http, handle_validation

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            now = proposal_session.info.get("coach_api_now", NOW)
            return now if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(coach, "datetime", Clock)
    monkeypatch.setattr(coach, "resolve_kb", _resolve)
    app = FastAPI()
    app.include_router(coach.router, prefix="/api/v1")
    app.add_exception_handler(HTTPException, handle_http)
    app.add_exception_handler(RequestValidationError, handle_validation)

    def override():
        yield proposal_session

    app.dependency_overrides[get_session] = override
    return TestClient(app), proposal_session


def pending(session):
    snapshot, uid = _snapshot(session)
    result = submit_proposal(session, _doc(snapshot, uid), now=NOW, resolve_kb=_resolve)
    assert result.status == "pending", [issue.to_json() for issue in result.issues]
    session.commit()
    return result.proposal_id, uid, snapshot.calendar_version_number


def decision(head, *, accept=None, reject=None, key="api-decision-key"):
    return {
        "expected_head": head,
        "expected_revision": 1,
        "idempotency_key": key,
        "accept_change_ids": accept or [],
        "reject_change_ids": reject or [],
    }


def test_detail_includes_current_and_flags(api):
    client, session = api
    proposal_id, uid, _ = pending(session)
    response = client.get(f"/api/v1/coach/proposals/{proposal_id}")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["is_current"] is True
    assert data["changes"][0]["current"]["planned_duration_s"] == 1800
    assert data["changes"][0]["material_flags"] == []
    assert "payload" not in data and "input_hash" not in data
    items = client.get("/api/v1/coach/proposals?status=pending").json()["data"]["items"]
    assert items[0]["id"] == str(proposal_id) and items[0]["change_count"] == 1
    assert client.get(f"/api/v1/coach/proposals/{uuid.uuid4()}").status_code == 404


def test_detail_rechecks_pending_freshness(api, monkeypatch):
    from app.api import coach

    client, session = api
    proposal_id, _, head = pending(session)
    url = f"/api/v1/coach/proposals/{proposal_id}"

    def detail():
        response = client.get(url)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["status"] == "pending"
        return data

    assert detail()["is_current"] is True
    proposal = session.get(CoachProposal, proposal_id)
    snapshot = session.get(CoachSnapshot, proposal.snapshot_id)
    generated_at = snapshot.generated_at
    snapshot.generated_at = NOW - timedelta(hours=24, seconds=1)
    session.flush()
    assert detail()["is_current"] is False
    snapshot.generated_at = generated_at
    session.flush()

    with monkeypatch.context() as patch:
        patch.setattr(coach, "resolve_kb", lambda selection: replace(KB, digest="1" * 64))
        assert detail()["is_current"] is False
    assert detail()["is_current"] is True

    # Advance the head without the edit service's proactive stale marking.
    session.add(CalendarVersion(number=head + 1, parent_number=head, kind="manual_edit", actor="user"))
    session.get(AppState, 1).calendar_head_version = head + 1
    session.flush()
    moved = detail()
    assert moved["head"] == head + 1 and moved["is_current"] is False


def test_active_and_discard_api(api):
    client, session = api
    base = "/api/v1/coach/proposals"
    assert client.get(f"{base}/active").json()["data"]["proposal"] is None
    proposal_id, _, head = pending(session)
    assert client.get(f"{base}/active").json()["data"]["proposal"]["id"] == str(proposal_id)
    assert client.get(f"{base}?status=open").json()["data"]["items"][0]["id"] == str(proposal_id)
    assert client.delete(f"{base}/{proposal_id}").status_code == 422
    assert client.delete(f"{base}/{proposal_id}?expected_revision=2").status_code == 409
    response = client.delete(f"{base}/{proposal_id}?expected_revision=1")
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"proposal_id": str(proposal_id), "revision": 1, "status": "discarded"}
    assert client.delete(f"{base}/{proposal_id}?expected_revision=1").json()["data"] == response.json()["data"]
    assert client.get(f"{base}/active").json()["data"]["proposal"] is None
    assert client.get(base).json()["data"]["items"] == []
    assert client.get(f"{base}?status=discarded").json()["data"]["items"][0]["discarded_at"] is not None
    assert client.get(f"{base}/{proposal_id}").json()["data"]["discarded_at"] is not None
    assert session.get(AppState, 1).calendar_head_version == head
    decision_response = client.post(f"{base}/{proposal_id}/decision", json=decision(head, accept=["c1"]))
    assert decision_response.status_code == 409
    assert decision_response.json()["error"]["code"] == "proposal_discarded"


def test_accept_replay_and_changed_selection(api):
    client, session = api
    proposal_id, uid, head = pending(session)
    request = decision(head, accept=["c1"])
    url = f"/api/v1/coach/proposals/{proposal_id}/decision"
    response = client.post(url, json=request)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "accepted" and data["calendar_version"] == head + 1
    assert (
        next(row for row in calendar.state_at(session, head + 1) if row["session_uid"] == uid)["planned_duration_s"]
        == 2400
    )
    assert client.post(url, json=request).json()["data"] == data
    changed = client.post(url, json=decision(head, reject=["c1"]))
    assert changed.status_code == 409


def test_reject_all_recorded(api):
    client, session = api
    proposal_id, uid, head = pending(session)
    response = client.post(f"/api/v1/coach/proposals/{proposal_id}/decision", json=decision(head, reject=["c1"]))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "rejected"
    assert response.json()["data"]["calendar_version"] is None
    assert session.get(AppState, 1).calendar_head_version == head


def test_decision_incomplete_422(api):
    client, session = api
    proposal_id, _, head = pending(session)
    response = client.post(f"/api/v1/coach/proposals/{proposal_id}/decision", json=decision(head))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "decision_incomplete"
    assert session.get(AppState, 1).calendar_head_version == head


def test_accept_stale_409(api):
    client, session = api
    proposal_id, uid, head = pending(session)
    calendar.apply_edits(
        session, head, [{"op": "modify", "session_uid": uid, "fields": {"intent": "User correction"}}], "User edit"
    )
    session.commit()
    response = client.post(f"/api/v1/coach/proposals/{proposal_id}/decision", json=decision(head, accept=["c1"]))
    assert response.status_code == 409, response.text
    assert session.get(CoachProposal, proposal_id, populate_existing=True).status == "stale"


def test_no_snapshot_or_submit_routes(api):
    client, _ = api
    assert client.post("/api/v1/coach/snapshot").status_code in (404, 405)
    assert client.post("/api/v1/coach/submit").status_code in (404, 405)


def test_partial_accept_writes_version_with_lineage(api):
    client, session = api
    calendar.apply_edits(
        session,
        1,
        [
            {
                "op": "add",
                "fields": {
                    "local_date": day,
                    "kind": "run",
                    "intent": "Easy",
                    "recipe_id": "REC001",
                    "planned_duration_s": 1800,
                },
            }
            for day in (TODAY + timedelta(days=4), TODAY + timedelta(days=8))
        ],
        "Fixture runs",
    )
    session.commit()
    snapshot, uid = _snapshot(session)
    doc = _doc(snapshot, uid)
    runs = [row for row in calendar.state_at(session, snapshot.calendar_version_number) if row["kind"] == "run"]
    doc["changes"] = [
        {
            "change_id": f"c{index + 1}",
            "op": "modify",
            "session_uid": str(row["session_uid"]),
            "after": {"planned_duration_s": 2100},
            "reason": "Small adjustment",
        }
        for index, row in enumerate(runs)
    ]
    result = submit_proposal(session, doc, now=NOW, resolve_kb=_resolve)
    assert result.status == "pending", result.issues
    session.commit()
    response = client.post(
        f"/api/v1/coach/proposals/{result.proposal_id}/decision",
        json=decision(snapshot.calendar_version_number, accept=["c1", "c3"], reject=["c2"]),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "partially_accepted"
    rows = list(
        session.scalars(
            select(CalendarSessionRevision).where(
                CalendarSessionRevision.calendar_version_number == data["calendar_version"]
            )
        )
    )
    assert len(rows) == 2 and all(row.revision == 2 for row in rows)
    version = session.scalar(select(CalendarVersion).where(CalendarVersion.number == data["calendar_version"]))
    assert version.kind == "proposal_accept" and version.actor == "coach"
    assert version.proposal_id == result.proposal_id


def test_empty_proposal_accept(api):
    client, session = api
    snapshot, uid = _snapshot(session)
    doc = _doc(snapshot, uid)
    doc["changes"] = []
    result = submit_proposal(session, doc, now=NOW, resolve_kb=_resolve)
    assert result.status == "pending"
    session.commit()
    response = client.post(
        f"/api/v1/coach/proposals/{result.proposal_id}/decision", json=decision(snapshot.calendar_version_number)
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "accepted"
    assert response.json()["data"]["calendar_version"] is None


def test_accept_block_change_appends_decision(api):
    from app.planning_models import BlockDecision, BlockVersion

    client, session = api
    snapshot, uid = _snapshot(session, "review_training_block")
    doc = _doc(snapshot, uid)
    doc["changes"] = []
    doc["block_change"] = {
        "decision": "start",
        "block_uid": None,
        "version_fields": {
            "status": "active",
            "objective": "Build",
            "rationale": "Ready",
            "maintained_qualities": [],
            "non_goals": [],
            "eligible_recipe_ids": ["REC001", "REC009"],
            "progression_dimension": "duration",
            "constraints": [],
            "start_date": str(TODAY),
            "review_date": str(TODAY + timedelta(days=42)),
            "completion_indicators": [],
            "early_review_triggers": [],
            "objective_status": "unresolved",
            "benchmark": {
                "kind": "time_trial",
                "protocol": "5 km solo time trial",
                "planned_date": str(TODAY + timedelta(days=35)),
                "progress_if": "Under 22:00",
                "consolidate_if": "Over 22:30",
            },
        },
    }
    result = submit_proposal(session, doc, now=NOW, resolve_kb=_resolve)
    assert result.status == "pending", result.issues
    session.commit()
    request = {**decision(snapshot.calendar_version_number), "accept_block_change": True}
    response = client.post(f"/api/v1/coach/proposals/{result.proposal_id}/decision", json=request)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "accepted" and data["calendar_version"] is None
    block = session.get(BlockVersion, uuid.UUID(data["block_version_id"]))
    assert block.status == "active" and block.version == 1
    assert session.scalar(select(BlockDecision).where(BlockDecision.block_uid == block.block_uid)).decision == "start"


def test_subset_invalid_422(api):
    client, session = api
    snapshot, uid = _snapshot(session)
    doc = _doc(snapshot, uid)
    strength = next(
        row
        for row in calendar.state_at(session, snapshot.calendar_version_number)
        if row["kind"] == "strength" and row["local_date"] == TODAY + timedelta(days=4)
    )
    doc["changes"] = [
        {
            "change_id": "c1",
            "op": "add",
            "after": {"local_date": str(TODAY + timedelta(days=3)), "kind": "strength", "intent": "Full body"},
            "reason": "Schedule",
        },
        {"change_id": "c2", "op": "delete", "session_uid": str(strength["session_uid"]), "reason": "Replace Friday"},
    ]
    result = submit_proposal(session, doc, now=NOW, resolve_kb=_resolve)
    assert result.status == "pending", result.issues
    session.commit()
    response = client.post(
        f"/api/v1/coach/proposals/{result.proposal_id}/decision",
        json=decision(snapshot.calendar_version_number, accept=["c2"], reject=["c1"]),
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "proposal_invalid_subset"
    assert session.get(AppState, 1).calendar_head_version == snapshot.calendar_version_number


def test_strength_omissions_are_reviewed_and_scoped_to_their_dates(api, monkeypatch):
    from app.api import coach

    client, session = api
    now = NOW + timedelta(days=7)
    session.info["coach_api_now"] = now
    monkeypatch.setattr(coach, "resolve_kb", resolve_kb)
    travel_day = date(2026, 12, 1)
    recovery_day = date(2026, 12, 4)
    routine_days = [1, 4]
    profile = current_profile(session)
    assert profile is not None and profile.strength_days_confirmed
    profile.scheduled_strength_days = routine_days
    replace_routine(
        session,
        routine_view(session)["version"],
        [
            {"label": label, "default_weekday": weekday, "lower_body_cost": "moderate"}
            for label, weekday in zip(["Full body A", "Full body B"], routine_days, strict=True)
        ],
    )
    calendar.apply_edits(
        session,
        1,
        [
            {
                "op": "move",
                "session_uid": row["session_uid"],
                "fields": {"local_date": row["local_date"] + timedelta(days=1)},
            }
            for row in calendar.state_at(session, 1)
            if row["kind"] == "strength" and row["local_date"].weekday() == 0
        ]
        + [{"op": "add", "fields": {"local_date": travel_day, "kind": "mobility", "intent": "Travel mobility"}}],
        "Confirm the Tuesday and Friday routine",
    )
    run_uid = next(row["session_uid"] for row in calendar.state_at(session, 1) if row["kind"] == "run")

    def review(at: datetime) -> tuple[dict, dict]:
        result = build_snapshot(session, "review_rolling_plan", at.date(), now=at)
        snapshot = session.get(CoachSnapshot, uuid.UUID(result["snapshot_id"]))
        doc = _doc(snapshot, run_uid)
        doc.update(evidence_ids=[], recipe_ids=[], policy_ids=[])
        return doc, result["payload"]["goals_and_constraints"]

    doc, constraints = review(now)
    expected = {row["local_date"]: row for row in constraints["confirmed_strength_sessions"]}
    travel_slot = expected[str(travel_day)]
    friday_slot = expected[str(recovery_day)]
    assert constraints["accepted_strength_omissions"] == []
    head = doc["base_calendar_version"]
    baseline_calendar = calendar.state_at(session, head)
    doc["summary"] = "Omit Tuesday lifting during travel"
    doc["rationale"] = "Travel prevents the usual Tuesday lift. Keep Friday lifting."
    doc["changes"] = [
        {
            "change_id": "c1",
            "op": "add",
            "after": {"local_date": str(travel_day), "kind": "rest", "intent": travel_slot["intent"]},
            "material_flags": ["strength_omission"],
            "reason": "Travel",
        },
        {
            "change_id": "c2",
            "op": "add",
            "after": {**friday_slot, "kind": "strength"},
            "reason": "Keep the confirmed Friday lift",
        },
    ]
    travel = submit_proposal(session, doc, now=now, resolve_kb=resolve_kb)
    assert travel.status == "pending", travel.issues
    session.commit()
    travel_url = f"/api/v1/coach/proposals/{travel.proposal_id}"

    travel_reason = "Flight and hotel check-in prevent the Tuesday lift"
    doc["changes"][0]["reason"] = travel_reason
    revised = client.post(
        travel_url + "/revise", json={"expected_revision": 1, "reason": "Confirm travel timing", "document": doc}
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["data"]["proposal_id"] == str(travel.proposal_id)
    assert revised.json()["data"]["revision"] == 2
    travel_change = client.get(travel_url).json()["data"]["changes"][0]
    assert travel_change["material_flags"] == ["strength_omission"]
    assert travel_change["reason"] == travel_reason
    assert travel_change["after"]["kind"] == "rest"

    invalid = client.post(
        travel_url + "/decision",
        json={**decision(head, accept=["c1"], reject=["c2"], key="reject-friday-lift"), "expected_revision": 2},
    )
    assert invalid.status_code == 422, invalid.text
    assert invalid.json()["error"]["code"] == "proposal_invalid_subset"
    assert any(item["code"] == "V9.strength_count" for item in invalid.json()["error"]["fields"])
    assert session.get(AppState, 1).calendar_head_version == head
    assert calendar.state_at(session, head) == baseline_calendar

    accepted = client.post(
        travel_url + "/decision",
        json={**decision(head, accept=["c1", "c2"], key="accept-travel"), "expected_revision": 2},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["status"] == "accepted"
    travel_change = client.get(travel_url).json()["data"]["changes"][0]
    assert travel_change["decision"] == "accepted"
    assert travel_change["session_uid"] is None
    head = accepted.json()["data"]["calendar_version"]
    rows = calendar.state_at(session, head)
    assert [row["kind"] for row in rows if row["local_date"] == travel_day] == ["mobility"]
    friday = next(row for row in rows if row["local_date"] == recovery_day and row["kind"] == "strength")

    doc, _ = review(now)
    recovery_reason = "Reduce lower-body load this week while recovering from travel"
    doc["summary"] = "Omit Friday lifting for recovery"
    doc["rationale"] = recovery_reason
    doc["changes"] = [
        {
            "change_id": "c1",
            "op": "delete",
            "session_uid": str(friday["session_uid"]),
            "material_flags": ["strength_omission"],
            "reason": recovery_reason,
        }
    ]
    recovery = submit_proposal(session, doc, now=now, resolve_kb=resolve_kb)
    assert recovery.status == "pending", recovery.issues
    session.commit()
    recovery_url = f"/api/v1/coach/proposals/{recovery.proposal_id}"
    change = client.get(recovery_url).json()["data"]["changes"][0]
    assert change["material_flags"] == ["strength_omission"]
    assert change["reason"] == recovery_reason
    assert change["current"]["kind"] == "strength"
    assert session.get(AppState, 1).calendar_head_version == head
    accepted = client.post(recovery_url + "/decision", json=decision(head, accept=["c1"], key="accept-recovery"))
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["status"] == "accepted"
    head = accepted.json()["data"]["calendar_version"]
    assert not any(row["session_uid"] == friday["session_uid"] for row in calendar.state_at(session, head))
    assert current_profile(session).scheduled_strength_days == routine_days

    following_now = now + timedelta(days=7)
    next_doc, constraints = review(following_now)
    assert constraints["accepted_strength_omissions"] == [
        {**travel_slot, "reason": travel_reason},
        {**friday_slot, "reason": recovery_reason},
    ]
    following_days = [travel_day + timedelta(days=7), recovery_day + timedelta(days=7)]
    assert {str(day) for day in following_days} <= {
        row["local_date"] for row in constraints["confirmed_strength_sessions"]
    }
    next_doc.update(summary="Resume usual lifting", rationale="The temporary omissions are over")
    next_doc["changes"] = [
        {
            "change_id": f"c{i}",
            "op": "add",
            "after": {"local_date": str(day), "kind": "strength", "intent": "Full body"},
            "reason": "Resume the confirmed routine",
        }
        for i, day in enumerate(following_days, start=1)
    ]
    result = submit_proposal(session, next_doc, now=following_now, resolve_kb=resolve_kb)
    assert result.status == "pending", result.issues
    session.commit()
    session.info["coach_api_now"] = following_now
    accepted = client.post(
        f"/api/v1/coach/proposals/{result.proposal_id}/decision",
        json=decision(head, accept=["c1", "c2"], key="resume-routine"),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["status"] == "accepted"
    head = accepted.json()["data"]["calendar_version"]
    strength_days = {row["local_date"] for row in calendar.state_at(session, head) if row["kind"] == "strength"}
    assert set(following_days) <= strength_days

    calendar.apply_edits(
        session,
        head,
        [{"op": "add", "fields": {**friday_slot, "local_date": recovery_day + timedelta(days=1), "kind": "strength"}}],
        "Reinstate Friday's lift on Saturday",
    )
    saturday = next(
        row for row in calendar.state_at(session, head + 1) if row["local_date"] == recovery_day + timedelta(days=1)
    )
    calendar.apply_edits(
        session, head + 1, [{"op": "delete", "session_uid": saturday["session_uid"]}], "Remove Saturday lifting"
    )
    assert accepted_strength_omissions(
        session, travel_day, recovery_day, constraints["confirmed_strength_sessions"]
    ) == [constraints["accepted_strength_omissions"][0]]


def test_revision_api_preserves_link_and_requires_reviewed_revision(api):
    client, session = api
    proposal_id, uid, head = pending(session)
    base = f"/api/v1/coach/proposals/{proposal_id}"
    draft = client.get(base + "/document").json()["data"]
    assert draft["revision"] == 1 and draft["is_current"]
    draft["document"]["changes"][0]["after"]["planned_duration_s"] = 2100
    request = {"expected_revision": 1, "reason": "Shorter run", "document": draft["document"]}
    revised = client.post(base + "/revise", json=request)
    assert revised.status_code == 200, revised.text
    assert revised.json()["data"]["proposal_id"] == str(proposal_id)
    assert revised.json()["data"]["revision"] == 2
    assert client.post(base + "/revise", json=request).json()["data"] == revised.json()["data"]
    detail = client.get(base).json()["data"]
    assert detail["revision"] == 2
    assert [r["revision"] for r in detail["revisions"]] == [2, 1]
    assert detail["revisions"][0]["changed_change_ids"] == ["c1"]
    old = client.get(base + "/revisions/1").json()["data"]
    assert old["document"]["changes"][0]["after"]["planned_duration_s"] == 2400
    assert client.get(base + "/revisions/99").status_code == 404
    stale = client.post(base + "/decision", json=decision(head, accept=["c1"]))
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "proposal_revision_conflict"
    missing_revision = decision(head, accept=["c1"])
    del missing_revision["expected_revision"]
    assert client.post(base + "/decision", json=missing_revision).status_code == 422
    accepted = client.post(base + "/decision", json={**decision(head, accept=["c1"]), "expected_revision": 2})
    assert accepted.status_code == 200
    assert client.post(base + "/revise", json={**request, "expected_revision": 2}).status_code == 409


def test_invalid_revision_api_preserves_current_draft(api):
    client, session = api
    proposal_id, _, _ = pending(session)
    base = f"/api/v1/coach/proposals/{proposal_id}"
    document = client.get(base + "/document").json()["data"]["document"]
    document["changes"][0]["after"]["local_date"] = "2027-01-01"
    response = client.post(
        base + "/revise", json={"expected_revision": 1, "reason": "Outside horizon", "document": document}
    )
    assert response.status_code == 422
    current = client.get(base).json()["data"]
    assert current["revision"] == 1 and current["status"] == "pending"
    assert current["changes"][0]["after"] == {"planned_duration_s": 2400}


def test_detail_exposes_exception_fields_and_patch(api):
    client, session = api
    seen = NOW - timedelta(hours=2)
    finding = ExceptionFinding(
        rule_code="FATIGUE_PERSISTING",
        rule_version="exceptions.v1",
        category="accumulated_fatigue",
        severity="caution",
        entity_key="fatigue_persisting",
        status="open",
        summary="Synthetic",
        evidence=[],
        evidence_at=seen,
        first_seen_at=seen,
        last_seen_at=seen,
    )
    session.add(finding)
    session.flush()
    snapshot, uid = _snapshot(session, "exception_review")
    doc = _doc(snapshot, uid)
    doc["changes"][0]["after"] = {"planned_duration_s": 1200}
    doc["exception"] = {
        "finding_ids": [str(finding.id)],
        "category": "accumulated_fatigue",
        "severity": "caution",
        "confidence": "moderate",
        "triggering_evidence": "Fatigue 8 on two mornings",
        "relevant_context": None,
        "ladder_level": "next_session",
        "patch_window": {"start": "2026-11-16", "end": "2026-11-18"},
        "unchanged": [],
        "reassess_on": "2026-11-19",
        "monitor": ["Morning fatigue"],
        "return_criteria": ["Usual fatigue twice"],
        "escalate_criteria": ["High through Saturday"],
    }
    result = submit_proposal(session, doc, now=NOW, resolve_kb=_resolve)
    assert result.status == "pending", result.issues
    session.commit()
    response = client.post(
        f"/api/v1/coach/proposals/{result.proposal_id}/decision",
        json=decision(snapshot.calendar_version_number, accept=["c1"]),
    )
    assert response.status_code == 200, response.text
    data = client.get(f"/api/v1/coach/proposals/{result.proposal_id}").json()["data"]
    assert data["exception"]["ladder_level"] == "next_session"
    assert data["event_review"] is None
    assert data["patch_resolutions"] == []
    assert data["patch"]["status"] == "open"
    assert data["patch"]["calendar_version_number"] == 2
    rolling_id, _, _ = pending(session)
    assert client.get(f"/api/v1/coach/proposals/{rolling_id}").json()["data"]["patch"] is None
