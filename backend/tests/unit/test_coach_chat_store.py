"""Failure recovery and access boundaries for the local coach."""

from uuid import uuid4

from app.services.coach_chat_store import ChatMessage, ChatStore


def test_running_turn_recovers_when_its_process_lease_disappears(tmp_path):
    real = ChatStore(tmp_path, "real")
    demo = ChatStore(tmp_path, "demo")
    turn = uuid4()
    with real.transaction() as state:
        lease = real.lease()
        assert lease is not None
        state.review.id = uuid4()
        state.review.status = "running"
        state.review.active_turn = turn
        state.review.messages.append(ChatMessage(id=turn, role="user", text="Review my week"))
    assert ChatStore(tmp_path, "real").lease() is None
    assert real.read().status == "running"
    assert demo.read().messages == []
    lease.close()
    resumed = ChatStore(tmp_path, "real").read()
    assert resumed.status == "failed" and resumed.active_turn is None
    assert resumed.error and resumed.error.code == "interrupted"
    assert resumed.messages[0].text == "Review my week"
    assert real.path.stat().st_mode & 0o777 == 0o600
