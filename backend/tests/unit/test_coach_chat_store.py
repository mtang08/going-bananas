"""Failure recovery and access boundaries for the local coach."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
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


def test_local_coach_rejects_remote_peer_cross_site_and_unmarked_writes():
    path = "/api/v1/coach/chat"
    public_peer = TestClient(app, client=("192.0.2.5", 8000))
    assert public_peer.get(path).json()["error"]["code"] == "local_coach_required"
    local_peer = TestClient(app, client=("127.0.0.1", 8000))
    assert local_peer.get(path, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert local_peer.get(path, headers={"Origin": "https://external.test"}).json()["error"]["code"] == "invalid_origin"
    assert local_peer.post(f"{path}/auth/start", json={}).json()["error"]["code"] == "csrf_header_required"
