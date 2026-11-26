"""Dashboard chat to verified evidence, pending draft, and explicit calendar decision."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import pytest

from app.api import coach, coach_chat
from app.api.coach_chat import CoachChatGateway, get_chat_gateway
from app.read.calendar import head_version
from app.services import calendar
from app.services.coach_chat_store import ChatStore

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
from coach_chat_script import SIGN_IN_URL, ScriptedCoachRuntime  # noqa: E402

pytestmark = pytest.mark.integration
CHAT = "/api/v1/coach/chat"
PROPOSALS = "/api/v1/coach/proposals"


class _SavepointRuntime(ScriptedCoachRuntime):
    """Start provider I/O after the POST releases the test fixture's one DB connection."""

    post_finished: asyncio.Event | None = None

    async def run_turn(self, **kwargs):
        if self.post_finished is not None:
            await self.post_finished.wait()
        return await super().run_turn(**kwargs)

    def send(self, client, message):
        gate = self.post_finished = asyncio.Event()
        try:
            return client.post(f"{CHAT}/messages", json=message)
        finally:
            assert client.portal is not None
            client.portal.call(gate.set)


def _until(check):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        if result := check():
            return result
        sleep(0.01)
    pytest.fail("Timed out waiting for the coaching request")


def _message(text: str, thread_id: str | None = None):
    return {"thread_id": thread_id, "client_message_id": str(uuid4()), "text": text}


@pytest.fixture
def chat_stack(tmp_path, api_client, session_factory, proposal_session, monkeypatch):
    now = proposal_session.info["metrics_now"]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(coach, "datetime", Clock)
    fixture_root = Path(__file__).resolve().parents[3]
    runtime = _SavepointRuntime(mode="test", repo_root=fixture_root)
    store = ChatStore(tmp_path, "test")

    def make():
        gateway = CoachChatGateway(
            store,
            runtime,
            session_factory=lambda: session_factory(expire_on_commit=False),
            instructions=lambda: "Synthetic coach exercise.",
            clock=lambda: now,
        )
        client = api_client(coach_chat.router, coach.router, overrides={get_chat_gateway: lambda: gateway})
        return client, gateway

    return runtime, store, make


def _finished(client, store):
    _until(lambda: store.read().status != "running")
    return client.get(CHAT).json()["data"]


def test_review_resumes_after_restart_and_manual_decision_applies_calendar(chat_stack, session_factory):
    runtime, store, make = chat_stack
    with session_factory() as session:
        head = head_version(session)
    client, _ = make()
    with client:
        view = client.get(CHAT).json()["data"]
        assert view["id"] is None and view["messages"] == [] and not runtime.started_turns
        discussion = _message("Can we adjust next week's easy run?")
        discussion["intent"] = "sunday_review"
        first = runtime.send(client, discussion).json()["data"]
        review_id = first["id"]
        chat = _finished(client, store)
        assert chat["status"] == "idle" and chat["proposal_id"] is None
        assert "next easy run" in chat["messages"][-1]["text"]
        codex_thread = store.read().codex_thread_id
        assert codex_thread and codex_thread not in str(chat)
        assert runtime.started_turns == [f"The athlete selected Sunday Review.\n\n{discussion['text']}"]

    # A fresh gateway has the private conversation, client receipts, and resume ID.
    client, _ = make()
    with client:
        assert client.get(CHAT).json()["data"] == chat
        assert client.post(f"{CHAT}/messages", json=discussion).json()["data"] == chat
        assert len(runtime.started_turns) == 1
        agreement = _message("Looks good. Save it.", review_id)
        runtime.send(client, agreement).raise_for_status()
        pending = _finished(client, store)
        assert pending["status"] == "idle", pending["error"]
        proposal_id = pending["proposal_id"]
        assert proposal_id, runtime.draft_results
        assert pending["proposal_revision"] == 1
        assert "Pending your review" in pending["messages"][-1]["text"]
        assert runtime.resumed_threads == [codex_thread]
        assert client.post(f"{CHAT}/messages", json=agreement).json()["data"] == pending
        assert len(runtime.started_turns) == 2 and len(runtime.draft_results) == 1

        detail = client.get(f"{PROPOSALS}/{proposal_id}").json()["data"]
        assert detail["status"] == "pending" and detail["is_current"]
        run = detail["changes"][0]
        assert run["after"]["planned_duration_s"] == run["before"]["planned_duration_s"] + 300
        with session_factory() as session:
            assert head_version(session) == head

        revision = _message("Please save a revision.", review_id)
        runtime.send(client, revision).raise_for_status()
        revised = _finished(client, store)
        assert revised["proposal_id"] == proposal_id
        assert revised["proposal_revision"] == 2, runtime.draft_results
        assert client.post(f"{CHAT}/messages", json=revision).json()["data"] == revised
        assert len(runtime.started_turns) == 3 and len(runtime.draft_results) == 2
        with session_factory() as session:
            assert head_version(session) == head

        decision = client.post(
            f"{PROPOSALS}/{proposal_id}/decision",
            json={
                "expected_head": head,
                "expected_revision": 2,
                "idempotency_key": "chat-explicit-acceptance",
                "accept_change_ids": ["c1"],
                "reject_change_ids": [],
            },
        )
        decision.raise_for_status()
        assert decision.json()["data"]["status"] == "accepted"
        assert client.get(CHAT).json()["data"]["proposal_id"] == proposal_id
        with session_factory() as session:
            assert head_version(session) == head + 1
            planned = next(
                row for row in calendar.state_at(session, head + 1) if str(row["session_uid"]) == run["session_uid"]
            )
            assert planned["planned_duration_s"] == run["after"]["planned_duration_s"]


def test_in_flight_replay_conflict_cancel_and_new_review(chat_stack):
    runtime, store, make = chat_stack
    client, gateway = make()
    with client:
        body = _message("Hold this turn")
        first = runtime.send(client, body).json()["data"]
        review_id = first["id"]
        _until(lambda: gateway.turn and gateway.turn.reply)
        replay = client.post(f"{CHAT}/messages", json=body).json()["data"]
        assert replay["status"] == "running"
        assert replay["messages"][-1]["text"] == "Checking the training log"
        conflict = client.post(f"{CHAT}/messages", json={**body, "text": "Different text"})
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "chat_message_conflict"
        conflict = client.post(f"{CHAT}/messages", json=_message("One more thing", review_id))
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "chat_running"
        stopped = client.post(f"{CHAT}/cancel", json={"thread_id": review_id}).json()["data"]
        assert stopped["status"] == "cancelled" and len(stopped["messages"]) == 1
        assert runtime.interruptions == 1
        next_review = client.post(f"{CHAT}/new", json={"thread_id": review_id}).json()["data"]
        assert next_review["messages"] == [] and next_review["id"] != review_id
        assert (store.directory / "reviews" / f"{review_id}.json").is_file()
        stale = client.post(f"{CHAT}/cancel", json={"thread_id": review_id})
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "chat_review_changed"
        assert client.post(f"{CHAT}/messages", json=body).json()["data"] == next_review
        assert len(runtime.started_turns) == 1


def test_source_edit_during_coaching_cannot_create_a_stale_draft(chat_stack, session_factory):
    runtime, store, make = chat_stack
    runtime.before_save = asyncio.Event()
    client, _ = make()
    with client:
        runtime.send(client, _message("Looks good. Save it.")).raise_for_status()
        _until(lambda: runtime.save_ready)
        with session_factory() as session:
            head = head_version(session)
            run = next(row for row in calendar.state_at(session, head) if row["kind"] == "run")
            calendar.apply_edits(
                session,
                head,
                [{"op": "modify", "session_uid": run["session_uid"], "fields": {"planned_duration_s": 2100}}],
                "Synthetic concurrent session edit",
            )
            session.commit()
        assert client.portal is not None
        client.portal.call(runtime.before_save.set)
        chat = _finished(client, store)
        assert chat["proposal_id"] is None
        assert runtime.draft_results[-1]["error"] == "stale_evidence"
        assert client.get(f"{PROPOSALS}/active").json()["data"]["proposal"] is None
        with session_factory() as session:
            assert head_version(session) == head + 1


def test_explicit_login_survives_dashboard_reload_without_model_turn(chat_stack):
    runtime, _, make = chat_stack
    runtime.signed_in = False
    client, gateway = make()
    with client:
        assert client.get(f"{CHAT}/auth").json()["data"]["status"] == "signed_out"
        assert runtime.account_reads == 1
        client.post(f"{CHAT}/auth/start", json={}).raise_for_status()
        _until(lambda: gateway.auth.url)
        waiting = client.get(f"{CHAT}/auth").json()["data"]
        assert waiting == {"status": "waiting", "url": SIGN_IN_URL, "error": None}
        assert client.post(f"{CHAT}/auth/start", json={}).json()["data"] == waiting
        assert runtime.login_starts == 1
        assert client.post(f"{CHAT}/auth/cancel", json={}).json()["data"]["status"] == "cancelled"
        client.post(f"{CHAT}/auth/start", json={}).raise_for_status()
        _until(lambda: gateway.auth.url)
        assert client.portal is not None
        client.portal.call(runtime.sign_in_finished.set)
        _until(lambda: gateway.auth.status == "signed_in")
        assert client.get(f"{CHAT}/auth").json()["data"] == {"status": "signed_in", "url": None, "error": None}
        assert not runtime.started_turns

    client, _ = make()
    assert client.get(f"{CHAT}/auth").json()["data"]["status"] == "signed_in"


def test_unavailable_auth_retains_the_users_message(chat_stack):
    runtime, store, make = chat_stack
    runtime.signed_in = False
    client, _ = make()
    with client:
        body = _message("Review training this week")
        runtime.send(client, body).raise_for_status()
        chat = _finished(client, store)
        assert chat["status"] == "failed" and chat["error"]["code"] == "auth_required"
        assert [item["text"] for item in chat["messages"]] == [body["text"]]
        assert not runtime.started_turns
