"""Drive the registered dashboard through the native HTTP server and a scripted coach."""

import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener


def install_fake(root, env):
    # A fresh private bin directory shadows any installed Codex. The shebang
    # points to the test interpreter even when the launcher strips its environment.
    fake_bin = root / "private" / "synthetic-app-server"
    fake_bin.mkdir(parents=True, mode=0o700)
    executable = fake_bin / "codex"
    script = (
        Path(__file__).resolve().parents[2]
        / "backend-go/internal/coachdashboardhttp/testdata/native_app_server.py"
    )
    executable.write_bytes(f"#!{sys.executable}\n".encode() + script.read_bytes())
    executable.chmod(0o700)
    env["PATH"] = os.pathsep.join((str(fake_bin), env.get("PATH", os.defpath)))


def exercise_chat(base):
    client = build_opener(ProxyHandler({}))

    def call(suffix, data=None):
        req = Request(
            base + "/api/v1/coach/chat" + suffix,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Content-Type": "application/json", "X-Local-Request": "1"},
        )
        with client.open(req, timeout=10) as response:
            return json.load(response)["data"]

    def wait_idle():
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            review = call("")
            if review["status"] != "running":
                assert review["status"] == "idle", review.get("error")
                return review
            time.sleep(0.05)
        raise TimeoutError("Native dashboard turn did not finish")

    call(
        "/messages",
        {
            "text": "Could we add five minutes to my next easy run?",
            "client_message_id": str(uuid.uuid4()),
        },
    )
    first = wait_idle()
    assert (
        "35 minutes" in first["messages"][-1]["text"] and first["proposal_id"] is None
    )
    agreement = {
        "thread_id": first["id"],
        "client_message_id": str(uuid.uuid4()),
        "text": "Yes, please save the 35-minute easy run for my review.",
    }
    call("/messages", agreement)
    saved = wait_idle()
    assert saved["proposal_id"] and saved["proposal_revision"] == 1
    assert "/#proposal/" + saved["proposal_id"] in saved["messages"][-1]["text"]
    replay = call("/messages", agreement)
    assert (
        replay["proposal_id"] == saved["proposal_id"]
        and replay["messages"] == saved["messages"]
    )
    with client.open(
        base + "/api/v1/coach/proposals/" + saved["proposal_id"] + "/document",
        timeout=10,
    ) as response:
        draft = json.load(response)["data"]
    assert draft["status"] == "pending" and draft["revision"] == 1
    assert draft["document"]["changes"][0]["after"]["planned_duration_s"] == 2100
    with client.open(base + "/api/v1/calendar/versions", timeout=10) as response:
        latest = json.load(response)["data"]["items"][0]["number"]
    assert latest == draft["document"]["base_calendar_version"]
    return agreement
