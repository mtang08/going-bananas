"""Coaching endpoint lifecycle against rollback-isolated PostgreSQL sessions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import coaching as api
from app.coaching_models import CoachOutcomeEvent, CoachRecommendation
from app.config import settings
from app.db import engine, get_session
from app.main import app
from app.services.knowledge import KnowledgeIntegrityError

HEADERS = {"X-Local-Request": "1", "Origin": "http://testserver"}


@pytest.fixture
def coach_client(monkeypatch):
    assert settings.app_mode == "test"
    assert settings.database_url.rsplit("/", 1)[-1].endswith("_test")
    with engine.connect() as connection:
        transaction = connection.begin()
        state = {"marker": 0, "revision": 3, "generated_at": datetime.now(UTC), "checkins": []}
        today = datetime.now(ZoneInfo("America/New_York")).date()

        def context(*, as_of, session):
            return {"data": {
                "context_version": "coach_context.v1", "generated_at": state["generated_at"],
                "as_of": as_of, "timezone": "America/New_York", "data_revision": state["revision"],
                "profile_version": 0, "plan_version": 0,
                "profile": {"anchor_confirmed": False, "cycle_anchor": None},
                "recent_checkins": deepcopy(state["checkins"]), "recent_activities": [],
                "next_14_days_plan": [], "recent_14_days_plan": [],
                "recovery": {"series": {"hrv": []}},
                "last_14_days": {"rolling_7": {}, "rolling_14": {}},
                "marker": state["marker"],
            }}

        monkeypatch.setattr(api, "get_context", context)
        monkeypatch.setattr(api, "tz", lambda session: "America/New_York")

        def session_override():
            with Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                yield session

        app.dependency_overrides[get_session] = session_override
        try:
            with TestClient(app) as client:
                yield client, state, connection, today
        finally:
            app.dependency_overrides.pop(get_session, None)
            transaction.rollback()


def _post(client, endpoint, body):
    response = client.post(endpoint, json=body, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_cache_selection_feedback_and_no_plan_write(coach_client):
    client, state, connection, today = coach_client
    daily = "/api/v1/coach/daily"
    a = {"as_of": today.isoformat(), "illness": "none", "lower_body_soreness": "none", "clinician_restriction": "none"}
    b = {**a, "illness": "mild"}
    before = connection.exec_driver_sql("SELECT count(*) FROM plan_versions").scalar_one()
    first = _post(client, daily, a)["item"]
    assert first["payload"]["decision"] == "modify"  # Current symptoms are unknown.
    assert first["payload"]["references"]["sources"]
    assert all(s["title"] and s["url"] for s in first["payload"]["references"]["sources"])
    assert "topics/hybrid_strength_and_scheduling.md" in first["payload"]["audit"]["files_sections_loaded"]
    state["generated_at"] += timedelta(seconds=60)
    assert _post(client, daily, a)["item"]["id"] == first["id"]
    second = _post(client, daily, b)["item"]
    assert second["id"] != first["id"]
    assert _post(client, daily, a)["item"]["id"] == first["id"]
    assert client.get(daily).json()["data"]["item"]["id"] == first["id"]
    _post(client, f"/api/v1/coach/recommendations/{first['id']}/outcome", {"status": "accepted"})
    state["revision"] += 1  # Real outcome POST bumps the global revision; the advice semantics did not change.
    assert client.get(daily).json()["data"]["item"]["stale"] is False
    _post(client, f"/api/v1/coach/recommendations/{first['id']}/outcome", {"status": "completed", "effect": "helpful"})
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        events = session.scalars(select(CoachOutcomeEvent).where(CoachOutcomeEvent.recommendation_id == first["id"]).order_by(CoachOutcomeEvent.recorded_at)).all()
        assert [event.status for event in events] == ["accepted", "completed"]
        assert session.scalar(select(func.count()).select_from(CoachRecommendation).where(CoachRecommendation.as_of == today)) >= 2
    assert connection.exec_driver_sql("SELECT count(*) FROM plan_versions").scalar_one() == before


def test_stale_acceptance_refused_and_knowledge_failure_is_useful(coach_client, monkeypatch):
    client, state, _, today = coach_client
    daily = "/api/v1/coach/daily"
    row = _post(client, daily, {"as_of": today.isoformat()})["item"]
    state["marker"] += 1
    stale = client.get(daily).json()["data"]["item"]
    assert stale["stale"]
    refused = client.post(f"/api/v1/coach/recommendations/{row['id']}/outcome", json={"status": "accepted"}, headers=HEADERS)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "stale_recommendation"
    assert _post(client, f"/api/v1/coach/recommendations/{row['id']}/outcome", {"status": "completed"})["plan_changed"] is False
    from app.services import knowledge
    monkeypatch.setattr(knowledge, "load_knowledge", lambda *a, **kw: (_ for _ in ()).throw(KnowledgeIntegrityError("bad manifest")))
    response = client.get(daily)
    assert response.status_code == 200, response.text
    unavailable = response.json()["data"]
    assert unavailable["knowledge"]["available"] is False
    assert unavailable["item"]["stale"] is True
    assert client.post(daily, json={}, headers=HEADERS).status_code == 503


def test_knowledge_digest_and_weekly_feedback_chronology(coach_client, monkeypatch):
    client, state, _, today = coach_client
    daily = "/api/v1/coach/daily"
    weekly = "/api/v1/coach/weekly"
    day_item = _post(client, daily, {})["item"]
    _post(client, f"/api/v1/coach/recommendations/{day_item['id']}/outcome", {"status": "accepted"})
    _post(client, f"/api/v1/coach/recommendations/{day_item['id']}/outcome", {"status": "completed", "effect": "neutral"})
    week = _post(client, weekly, {})["item"]
    assert any("accepted" in item for item in week["payload"]["prior_advice_outcomes"])
    assert any("completed" in item for item in week["payload"]["prior_advice_outcomes"])
    _post(client, f"/api/v1/coach/recommendations/{week['id']}/outcome", {"status": "accepted"})
    assert client.get(weekly).json()["data"]["item"]["stale"] is False
    from app.services import knowledge
    original = knowledge.load_knowledge
    monkeypatch.setattr(knowledge, "load_knowledge", lambda *a, **kw: replace(original(*a, **kw), text=original(*a, **kw).text + "\nReviewed prose changed."))
    assert client.get(weekly).json()["data"]["item"]["stale"] is True


def test_future_preview_is_provisional_and_cannot_be_accepted(coach_client):
    client, _, _, today = coach_client
    tomorrow = today + timedelta(days=1)
    item = _post(client, "/api/v1/coach/daily", {"as_of": tomorrow.isoformat()})["item"]
    assert item["payload"]["decision"] == "modify"
    assert any("Future-day" in reason for reason in item["payload"]["missing_or_stale_inputs"])
    response = client.post(
        f"/api/v1/coach/recommendations/{item['id']}/outcome",
        json={"status": "accepted"}, headers=HEADERS,
    )
    assert response.status_code == 409


def test_future_observed_checkin_is_excluded(coach_client):
    client, state, _, today = coach_client
    state["checkins"] = [{
        "observed_at": datetime.now(UTC) + timedelta(hours=2),
        "symptoms": "none", "change": "same", "gait": "normal", "feeling": "fresh",
    }]
    item = _post(client, "/api/v1/coach/daily", {"as_of": today.isoformat()})["item"]
    assert item["payload"]["decision"] == "modify"
    assert any("No current-day" in reason for reason in item["payload"]["missing_or_stale_inputs"])
