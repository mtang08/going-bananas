from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import core
from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.models import Activity, ProfileVersion
from app.services import calendar
from app.services.trips import create_manual_trip

TODAY = date(2026, 11, 16)
NOW = datetime.combine(TODAY, time(15), tzinfo=UTC)


def _day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _put(client: TestClient, version: int, episode: dict | None):
    return client.put("/api/v1/running-interruption", json={"expected_version": version, "interruption": episode})


def test_running_interruption_preview_from_accepted_calendar(proposal_session, api_client, monkeypatch):
    session = proposal_session
    monkeypatch.setattr(core, "athlete_today", lambda _: TODAY)
    client = api_client(core.router)

    def run(offset, intent, *, recipe="REC001", minutes=30, locked=False):
        return {
            "op": "add",
            "fields": {
                "local_date": _day(offset),
                "kind": "run",
                "intent": intent,
                "recipe_id": recipe,
                "planned_duration_s": minutes * 60,
                "locked": locked,
                "slot": 8,
            },
        }

    calendar.apply_edits(
        session,
        1,
        [
            *[run(offset, f"Missed opportunity {offset}") for offset in range(1, 11)],
            run(0, "Preserve protected appointment", locked=True),
            run(11, "Long run", recipe="REC002"),
            run(12, "Unavailable in confirmed trip"),
            run(13, "Unknown availability in confirmed trip"),
            run(14, "Too long for the restriction", minutes=50),
            run(15, "Relaxed strides", recipe="REC007", minutes=25),
            run(16, "First feasible easy run", minutes=25),
        ],
        "Training plan",
    )
    profile = session.scalar(select(ProfileVersion).order_by(ProfileVersion.version.desc()).limit(1))
    profile.facts = {
        "other": "keep",
        "running_restriction": {
            "starts_on": _day(11),
            "ends_on": _day(15),
            "max_duration_s": 1800,
            "source": "Athlete",
        },
    }
    booked_uid = session.scalar(
        select(CalendarSessionRevision.session_uid).where(CalendarSessionRevision.intent == "Missed opportunity 4")
    )
    session.add(
        SessionCompletion(
            session_uid=booked_uid,
            status="completed_as_planned",
            match_method="user_marked",
            updated_at=NOW,
        )
    )
    create_manual_trip(
        session,
        {
            "start_date": date.fromisoformat(_day(12)),
            "end_date": date.fromisoformat(_day(15)),
            "destination_tz": "UTC",
            "day_availability": [
                {"date": date.fromisoformat(_day(12)), "availability": "unavailable"},
                {"date": date.fromisoformat(_day(14)), "availability": "normal"},
                {"date": date.fromisoformat(_day(15)), "availability": "normal"},
            ],
        },
        NOW,
    )
    session.commit()

    initial = client.get("/api/v1/running-interruption").json()["data"]
    assert initial["interruption"] is None and initial["phase"] is None
    version = initial["profile_version"]
    episode = {"reason": "travel", "starts_on": _day(0), "return_on": _day(11)}
    invalid = _put(client, version, {**episode, "review_on": _day(3)})
    assert invalid.status_code == 422
    response = _put(client, version, episode)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["phase"] == "paused"
    assert data["affected_runs_omitted"] == 2
    assert len(data["affected_runs"]) == 8
    days = [run["local_date"] for run in data["affected_runs"]]
    assert days == sorted(days) and _day(0) not in days and _day(4) not in days
    assert data["first_run"]["intent"] == "First feasible easy run"
    assert data["recorded_return"] is None
    assert all(_day(offset) in data["review_reason"] for offset in (11, 12, 13, 14))
    assert "Confirm running access" in data["review_reason"]
    assert client.get("/api/v1/running-interruption").json()["data"] == data
    assert client.get("/api/v1/profile").json()["data"]["facts"]["other"] == "keep"
    conflict = _put(client, version, None)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "version_conflict"

    def activity(offset: int) -> Activity:
        day = TODAY + timedelta(days=offset)
        start = datetime.combine(day, time(15), tzinfo=UTC)
        return Activity(sport="running", start_at=start, original_start=start.isoformat(), local_date=day)

    prereturn = activity(10)
    session.add(prereturn)
    session.commit()
    monkeypatch.setattr(core, "athlete_today", lambda _: TODAY + timedelta(days=14))
    missing = client.get("/api/v1/running-interruption").json()["data"]
    assert missing["phase"] == "returning"
    assert missing["recorded_return"] is None
    assert missing["first_run"]["local_date"] == _day(16)
    assert _day(15) in missing["review_reason"]

    first_actual = activity(16)
    session.add_all([first_actual, activity(17)])
    session.commit()
    monkeypatch.setattr(core, "athlete_today", lambda _: TODAY + timedelta(days=17))
    after_return = client.get("/api/v1/running-interruption").json()["data"]
    assert after_return["recorded_return"] == {"activity_id": str(first_actual.id), "local_date": _day(16)}
    assert after_return["first_run"] is None
    assert after_return["interruption"]["return_on"] == _day(11)
    assert "Review your response" in after_return["review_reason"]

    monkeypatch.setattr(core, "athlete_today", lambda _: TODAY + timedelta(days=7))
    pending = _put(
        client,
        data["profile_version"],
        {
            "reason": "illness",
            "starts_on": _day(0),
            "review_on": _day(6),
        },
    ).json()["data"]
    assert pending["phase"] == "review_due"
    assert pending["first_run"] is None and "Confirm the first available day" in pending["review_reason"]
    assert pending["recorded_return"] is None
    pending_days = [run["local_date"] for run in pending["affected_runs"]]
    assert len(pending_days) == 8 and pending_days == sorted(pending_days)
    assert {_day(offset) for offset in (7, 8, 9, 11, 12, 13, 14)} <= set(pending_days)
    clear = _put(client, pending["profile_version"], None).json()["data"]
    assert clear["interruption"] is None and clear["affected_runs"] == []
    assert calendar.head_version(session, populate_existing=True) == 2
    assert session.scalar(select(ProfileVersion).where(ProfileVersion.version == data["profile_version"])).facts[
        "running_interruption"
    ]["return_on"] == _day(11)
    assert client.get("/api/v1/profile").json()["data"]["facts"] == profile.facts
