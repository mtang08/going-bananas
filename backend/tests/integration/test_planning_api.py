"""Synthetic API preservation checks; all writes roll back beneath one outer transaction."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.api.planning import router
from app.planning_models import Block, BlockDecision, BlockVersion, Event, Goal, StrengthRoutineSlot
from app.services.strength_routine import confirmed_schedule, routine_occurrences


@pytest.fixture
def planning_fixture(db_connection, session_factory, api_client, profile_factory, calendar_state):
    with session_factory() as session:
        for model in (StrengthRoutineSlot, Goal, BlockDecision, BlockVersion, Event, Block):
            session.execute(delete(model))
        calendar_state(session)
        profile_factory(
            session,
            scheduled_strength_days=[],
            strength_schedule_mode="alternating",
            strength_week_a_start=date(2026, 11, 2),
            strength_week_a_days=[0, 4],
            strength_week_b_days=[1, 5],
            mobility_week_a_days=[2],
            mobility_week_b_days=[3],
            mobility_optional_days=[6],
        )
        session.commit()
    return api_client(router), db_connection


def test_routine_preserves_confirmed_schedule_and_versions(planning_fixture):
    client, connection = planning_fixture
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        schedule_before = confirmed_schedule(session)
        dates_before = [
            (row["date"], row["kind"], row["optional"])
            for row in routine_occurrences(session, date(2026, 11, 2), date(2026, 11, 15))
        ]
    empty = client.get("/api/v1/strength-routine").json()["data"]
    assert empty["version"] == 0 and empty["suggested"] is True
    slots = [
        {
            "label": "A",
            "default_weekday": 0,
            "lower_body_cost": "moderate",
            "typical_duration_s": 3600,
            "main_lower_body_lifts": ["Squat"],
        },
        {
            "label": "B",
            "default_weekday": 4,
            "lower_body_cost": "high",
            "typical_duration_s": 3300,
            "main_lower_body_lifts": ["Deadlift"],
        },
    ]
    created = client.put("/api/v1/strength-routine", json={"expected_version": 0, "slots": slots})
    assert created.status_code == 200, created.text
    assert created.json()["data"]["version"] == 1
    assert created.json()["data"]["schedule"] == empty["schedule"]
    assert client.put("/api/v1/strength-routine", json={"expected_version": 0, "slots": slots}).status_code == 409
    slots[0]["label"] = "A revised"
    revised = client.put("/api/v1/strength-routine", json={"expected_version": 1, "slots": slots})
    assert revised.status_code == 200 and revised.json()["data"]["version"] == 2
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        assert confirmed_schedule(session) == schedule_before
        assert [
            (row["date"], row["kind"], row["optional"])
            for row in routine_occurrences(session, date(2026, 11, 2), date(2026, 11, 15))
        ] == dates_before
        assert (
            session.scalar(
                select(func.count()).select_from(StrengthRoutineSlot).where(StrengthRoutineSlot.version == 1)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count()).select_from(StrengthRoutineSlot).where(StrengthRoutineSlot.version == 2)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(StrengthRoutineSlot)
                .where(StrengthRoutineSlot.version == 1, StrengthRoutineSlot.active.is_(True))
            )
            == 2
        )


def _future(days: int) -> str:
    return (datetime.now(UTC).astimezone(ZoneInfo("America/New_York")).date() + timedelta(days=days)).isoformat()


def test_goal_event_block_routes(planning_fixture):
    client, _ = planning_fixture
    assert client.get("/api/v1/blocks/active").json()["data"] is None
    assert client.get("/api/v1/goals").json()["data"]["items"] == []
    created = client.post("/api/v1/goals", json={"text": "Complete a 5K", "horizon": "season", "priority": 1})
    assert created.status_code == 201
    goal = created.json()["data"]
    assert goal["status"] == "active" and goal["version"] == 1
    assert (
        client.patch(f"/api/v1/goals/{goal['id']}", json={"expected_version": 0, "status": "paused"}).status_code == 422
    )
    revised = client.patch(f"/api/v1/goals/{goal['id']}", json={"expected_version": 1, "status": "paused"})
    assert revised.status_code == 200 and revised.json()["data"]["version"] == 2
    assert (
        client.patch(f"/api/v1/goals/{goal['id']}", json={"expected_version": 1, "status": "done"}).status_code == 409
    )
    event = client.post(
        "/api/v1/events",
        json={
            "name": "Fixture race",
            "event_date": _future(60),
            "distance_m": 5000,
            "purpose": "pr",
            "goal_time_s": 1500,
        },
    )
    assert event.status_code == 201
    data = event.json()["data"]
    assert (data["purpose"], data["goal_time_s"], data["rank"]) == ("pr", 1500, 1)
    event_id = data["id"]
    assert (
        client.patch(f"/api/v1/events/{event_id}", json={"expected_version": 1, "status": "registered"}).status_code
        == 200
    )
    assert client.get("/api/v1/events").json()["data"]["items"][0]["status"] == "registered"


def _add_version(session, uid, version, status, **extra):
    fields = dict(
        block_uid=uid,
        version=version,
        status=status,
        objective="Synthetic objective",
        why=[{"kind": "inference", "text": "Synthetic"}],
        maintained_qualities=[],
        non_goals=[],
        eligible_recipe_ids=[],
        progression_dimension="none",
        constraints={},
        start_date=date(2026, 11, 2),
        review_date=date(2026, 12, 2),
        indicators=[],
        early_review_triggers=[],
        objective_status="unresolved",
    )
    fields.update(extra)
    session.add(BlockVersion(**fields))


def test_block_active_uses_latest_version_and_history_is_ordered(planning_fixture):
    client, connection = planning_fixture
    block_uid = uuid.uuid4()

    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(Block(block_uid=block_uid))
        session.flush()
        _add_version(session, block_uid, 1, "active")
        _add_version(session, block_uid, 2, "ended")
        session.commit()
    assert client.get("/api/v1/blocks/active").json()["data"] is None
    history = client.get(f"/api/v1/blocks/{block_uid}/history")
    assert history.status_code == 200
    assert [item["version"] for item in history.json()["data"]["items"]] == [1, 2]
    active_uid = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(Block(block_uid=active_uid))
        session.flush()
        _add_version(session, active_uid, 1, "active")
        session.commit()
    assert client.get("/api/v1/blocks/active").json()["data"]["block_uid"] == str(active_uid)


def _post(client, name, days, purpose="training", **extra):
    response = client.post(
        "/api/v1/events", json={"name": name, "event_date": _future(days), "purpose": purpose, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _events(client):
    return client.get("/api/v1/events").json()["data"]["items"]


def _patch(client, event, **changes):
    return client.patch(f"/api/v1/events/{event['id']}", json={"expected_version": event["version"], **changes})


def _order(client, *events):
    return client.put(
        "/api/v1/events/order",
        json={"items": [{"id": event["id"], "expected_version": event["version"]} for event in events]},
    )


def test_event_input_requires_purpose_and_rejects_bad_values(planning_fixture):
    client, _ = planning_fixture
    base = {"name": "Race", "event_date": _future(10)}
    for extra in ({}, {"purpose": "target"}, {"purpose": "pr", "goal_time_s": 0}, {"purpose": "pr", "rank": 1}):
        assert client.post("/api/v1/events", json={**base, **extra}).status_code == 422
    assert _post(client, "Race", 10)["goal_time_s"] is None


def test_new_events_append_to_the_ranking_and_past_events_have_no_rank(planning_fixture):
    client, _ = planning_fixture
    events = [_post(client, f"Race {days}", days) for days in (30, 20, 10, -1)]
    assert [event["rank"] for event in events] == [1, 2, 3, None]
    assert {event["id"]: event["rank"] for event in _events(client)} == {event["id"]: event["rank"] for event in events}


def test_cancelling_or_completing_renumbers_the_rest(planning_fixture):
    client, _ = planning_fixture
    first, second, third = [_post(client, str(days), days) for days in (10, 20, 30)]
    assert _patch(client, first, status="cancelled").json()["data"]["rank"] is None
    assert [event["rank"] for event in _events(client)] == [None, 1, 2]
    assert _patch(client, second, status="completed").json()["data"]["rank"] is None
    assert [event["rank"] for event in _events(client)] == [None, None, 1]
    assert _patch(client, third, event_date=_future(-1)).json()["data"]["rank"] is None


def test_patch_clears_goal_time_and_rejects_null_purpose(planning_fixture):
    client, _ = planning_fixture
    first = _post(client, "Race", 10, "pr", goal_time_s=1800)
    response = _patch(client, first, goal_time_s=None)
    updated = response.json()["data"]
    assert response.status_code == 200 and updated["goal_time_s"] is None
    invalid = _patch(client, updated, purpose=None)
    assert invalid.json()["error"]["code"] == "invalid_event"
    assert _events(client) == [updated]


def test_put_events_order_reorders_and_bumps_versions(planning_fixture):
    client, _ = planning_fixture
    first, second, third = [_post(client, str(days), days) for days in (10, 20, 30)]
    response = _order(client, third, second, first)
    assert response.status_code == 200, response.text
    items = response.json()["data"]["items"]
    assert [(event["id"], event["rank"], event["version"]) for event in items] == [
        (third["id"], 1, 2),
        (second["id"], 2, 1),
        (first["id"], 3, 2),
    ]
    assert _events(client) == list(reversed(items))


def test_put_events_order_overrides_stale_stored_ranks(planning_fixture):
    client, connection = planning_fixture
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add_all(
            Event(
                name=str(days),
                event_date=date.fromisoformat(_future(days)),
                purpose="training",
                status="planned",
                rank=rank,
            )
            for rank, days in enumerate((10, 20, 30), start=2)
        )
        session.commit()
    first, second, third = _events(client)
    response = _order(client, third, second, first)
    assert response.status_code == 200, response.text
    items = response.json()["data"]["items"]
    assert [(event["id"], event["rank"]) for event in items] == [(third["id"], 1), (second["id"], 2), (first["id"], 3)]
    assert _events(client) == list(reversed(items))
    connection.execute(text("SET CONSTRAINTS uq_events_rank IMMEDIATE"))


def test_put_events_order_conflicts(planning_fixture):
    client, _ = planning_fixture
    first, second = [_post(client, str(days), days) for days in (10, 20)]
    past = _post(client, "Past", -1)
    missing = {**first, "id": str(uuid.uuid4())}
    for items in ((first,), (first, second, missing), (first, first), (past, second)):
        response = _order(client, *items)
        assert response.status_code == 409 and response.json()["error"]["code"] == "event_order_stale"
    response = _order(client, second, {**first, "version": 42})
    assert response.status_code == 409 and response.json()["error"]["code"] == "version_conflict"
    assert _events(client) == [past, first, second]


def _decide(session, uid, decision, to_version, **extra):
    session.add(
        BlockDecision(
            block_uid=uid,
            decision=decision,
            to_version=to_version,
            rationale="Synthetic rationale",
            confidence="moderate",
            decided_at=datetime(2026, 11, 1, tzinfo=UTC),
            **extra,
        )
    )


def _active(client):
    return client.get("/api/v1/blocks/active").json()["data"]


def test_active_block_reports_target_event_and_status(planning_fixture):
    client, connection = planning_fixture
    race = _post(client, "Goal race", 90, "pr", goal_time_s=1500)
    block_uid = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(Block(block_uid=block_uid))
        session.flush()
        _add_version(session, block_uid, 1, "active", target_event_id=uuid.UUID(race["id"]))
        session.commit()
    active = _active(client)
    assert active["target_event_id"] == race["id"]
    assert active["target_event"] == {
        key: race[key] for key in ("id", "name", "event_date", "distance_m", "purpose", "goal_time_s", "rank")
    }
    assert active["target_event_status"] == "current"
    next_race = _post(client, "Another race", 120)
    reordered = _order(client, next_race, race).json()["data"]["items"]
    assert _active(client)["target_event_status"] == "changed"
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        _add_version(session, block_uid, 2, "active")
        session.commit()
    active = _active(client)
    assert active["target_event_status"] == "unset" and active["target_event"] is None
    for event in reordered:
        assert _patch(client, event, status="cancelled").status_code == 200
    assert _active(client)["target_event_status"] == "none"


def test_block_responses_echo_build_outline(planning_fixture):
    client, connection = planning_fixture
    block_uid = uuid.uuid4()
    outline = [{"emphasis": "threshold durability", "weeks": 4}]
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(Block(block_uid=block_uid))
        session.flush()
        _add_version(session, block_uid, 1, "ended")
        _add_version(session, block_uid, 2, "active", build_outline=outline)
        session.commit()
    assert _active(client)["build_outline"] == outline
    history = client.get(f"/api/v1/blocks/{block_uid}/history").json()["data"]["items"]
    assert [item["build_outline"] for item in history] == [[], outline]


def test_block_responses_carry_why_indicators_legacy_text_and_sources(planning_fixture):
    client, connection = planning_fixture
    block_uid = uuid.uuid4()
    why = [{"kind": "observation", "text": "Tempo held at RPE 6"}, {"kind": "inference", "text": "Calf is quiet"}]
    indicators = [
        {"source": "quality_progression", "label": "Tempo at the same RPE", "progress_when": "pace 2% faster"}
    ]
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(Block(block_uid=block_uid))
        session.flush()
        _add_version(session, block_uid, 1, "active", why=why, indicators=indicators)
        _decide(session, block_uid, "start", 1, evidence_ids=["E-AER-01"], policy_ids=["P001"])
        session.commit()
    active = _active(client)
    assert {"why", "indicators", "legacy_text", "sources"} <= set(active)
    assert {"rationale", "completion_indicators"}.isdisjoint(active)
    assert (active["why"], active["indicators"], active["legacy_text"]) == (why, indicators, None)
    assert [(s["kind"], s["title"]) for s in active["sources"]] == [
        ("policy", "Work with missing or stale data"),
        ("evidence", "Aerobic progression"),
    ]
    assert "E-AER" not in str(active["sources"]) and "P001" not in str(active["sources"])
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        _add_version(session, block_uid, 2, "active", why=[], legacy_text="Earlier prose")
        session.commit()
    migrated = _active(client)
    assert (migrated["why"], migrated["indicators"], migrated["legacy_text"]) == ([], [], "Earlier prose")
    assert migrated["sources"] == []
    history = client.get(f"/api/v1/blocks/{block_uid}/history").json()["data"]["items"]
    assert [item["why"] for item in history] == [why, []]
    assert all("sources" not in item and "rationale" not in item for item in history)


def test_event_blocks_returns_one_row_per_training_block_oldest_first(planning_fixture):
    client, connection = planning_fixture
    target = uuid.UUID(_post(client, "Target race", 90)["id"])
    other = uuid.UUID(_post(client, "Other race", 120)["id"])
    first, second, untargeted = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add_all(Block(block_uid=uid) for uid in (first, second, untargeted))
        session.flush()
        _add_version(session, first, 1, "active", target_event_id=target)
        _add_version(session, first, 2, "ended", target_event_id=target)
        _decide(session, first, "start", 1)
        _decide(session, first, "continue", 2)
        _add_version(session, second, 1, "ended", target_event_id=other)
        _add_version(session, second, 2, "active", target_event_id=target, start_date=date(2026, 11, 23))
        _decide(session, second, "start", 1)
        _decide(session, second, "transition", 2)
        _add_version(session, untargeted, 1, "ended")
        session.commit()
    items = client.get(f"/api/v1/events/{target}/blocks").json()["data"]["items"]
    assert [(row["block_uid"], row["version"]) for row in items] == [(str(first), 2), (str(second), 2)]
    missing = client.get(f"/api/v1/events/{uuid.uuid4()}/blocks")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "event_not_found"


def test_event_blocks_splits_a_block_at_a_transition(planning_fixture):
    client, connection = planning_fixture
    event_id = uuid.UUID(_post(client, "Race", 90)["id"])
    block_uid = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(Block(block_uid=block_uid))
        session.flush()
        _add_version(session, block_uid, 1, "ended", target_event_id=event_id)
        for version in (2, 3):
            _add_version(session, block_uid, version, "active", target_event_id=event_id, start_date=date(2026, 11, 23))
        for version, decision in enumerate(("start", "transition", "continue"), start=1):
            _decide(session, block_uid, decision, version)
        session.commit()
    items = client.get(f"/api/v1/events/{event_id}/blocks").json()["data"]["items"]
    assert [(row["block_uid"], row["version"]) for row in items] == [(str(block_uid), 1), (str(block_uid), 3)]
