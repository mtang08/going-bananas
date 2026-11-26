"""Synthetic dashboard process for the managed PostgreSQL workflow test."""

import json
import os
import sys
from pathlib import Path

workspace = Path.cwd()
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    params = message.get("params", {})
    if method == "initialize":
        result = {}
    elif method == "initialized":
        continue
    elif method == "account/read":
        result = {"account": {"type": "chatgpt"}}
    elif method == "model/list":
        result = {
            "data": [
                {
                    "model": "gpt-6-astra",
                    "supportedReasoningEfforts": [{"reasoningEffort": "medium"}],
                }
            ]
        }
    elif method == "thread/resume":
        assert params["threadId"] == "private-fixture-thread"
        instructions = params["developerInstructions"]
        assert all(
            x in instructions
            for x in [
                "save_pending_proposal",
                "fixture skill",
                "fixture workflow",
                "fixture format",
            ]
        )
        assert os.environ["CODEX_HOME"] == str(workspace.parent.parent)
        result = {
            "thread": {"id": params["threadId"], "ephemeral": False},
            "model": "gpt-6-astra",
            "reasoningEffort": "medium",
            "cwd": str(workspace),
            "modelProvider": "openai",
            "approvalPolicy": "never",
            "runtimeWorkspaceRoots": [],
            "instructionSources": [],
            "activePermissionProfile": {"id": "going_bananas_coach", "extends": None},
            "sandbox": {"type": "readOnly", "networkAccess": False},
        }
    elif method == "turn/start":
        assert (
            params["input"][0]["text"]
            == "The athlete selected Sunday Review.\n\nReview the week"
        )
        result = {"turn": {"id": "runtime-turn"}}
    elif message.get("id") == "read-active":
        content = json.loads(message["result"]["contentItems"][0]["text"])
        assert content == {"proposal": None}
        data = {
            "threadId": "private-fixture-thread",
            "turnId": "runtime-turn",
            "turn": {
                "id": "runtime-turn",
                "status": "completed",
                "items": [
                    {
                        "id": "answer",
                        "type": "agentMessage",
                        "phase": "final_answer",
                        "text": "Updated fixture review complete."
                        if "updated fixture skill" in instructions
                        else "Fixture review complete.",
                    }
                ],
            },
        }
        print(json.dumps({"method": "turn/completed", "params": data}), flush=True)
        continue
    else:
        raise AssertionError("unexpected synthetic request")
    print(json.dumps({"id": message["id"], "result": result}), flush=True)
    if method == "turn/start":
        print(
            json.dumps(
                {
                    "method": "item/tool/call",
                    "id": "read-active",
                    "params": {
                        "threadId": "private-fixture-thread",
                        "turnId": "runtime-turn",
                        "namespace": "going_bananas",
                        "tool": "active_proposal",
                        "arguments": {},
                    },
                }
            ),
            flush=True,
        )
