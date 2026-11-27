"""A scripted model peer. Read and write only stdio messages from the local launcher."""

import json
import sys
from datetime import date, timedelta


def read():
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return json.loads(line)


def send(message):
    print(json.dumps(message), flush=True)


def result(req, value):
    send({"id": req["id"], "result": value})


def request(method):
    req = read()
    assert req["method"] == method
    return req


def tool(name, args=None):
    send(
        {
            "id": name,
            "method": "item/tool/call",
            "params": {
                "threadId": thread,
                "turnId": "turn",
                "namespace": "going_bananas",
                "tool": name,
                "arguments": args or {},
            },
        }
    )
    reply = read()
    assert reply["id"] == name
    return json.loads(reply["result"]["contentItems"][0]["text"])


def finish(text):
    send(
        {
            "method": "turn/completed",
            "params": {
                "threadId": thread,
                "turnId": "turn",
                "turn": {
                    "id": "turn",
                    "status": "completed",
                    "items": [
                        {
                            "id": "answer",
                            "type": "agentMessage",
                            "phase": "final_answer",
                            "text": text,
                        }
                    ],
                },
            },
        }
    )


result(request("initialize"), {})
request("initialized")
result(request("account/read"), {"account": {"type": "chatgpt"}})
result(
    request("model/list"),
    {
        "data": [
            {
                "model": "gpt-6-astra",
                "supportedReasoningEfforts": [{"reasoningEffort": "medium"}],
            }
        ]
    },
)
req = read()
thread = "synthetic-native-thread"
if req["method"] == "thread/resume":
    assert req["params"]["threadId"] == thread
else:
    assert (
        req["method"] == "thread/start"
        and len(req["params"]["dynamicTools"][0]["tools"]) == 6
    )
result(
    req,
    {
        "thread": {"id": thread, "ephemeral": False},
        "cwd": req["params"]["cwd"],
        "model": "gpt-6-astra",
        "reasoningEffort": "medium",
        "modelProvider": "openai",
        "approvalPolicy": "never",
        "runtimeWorkspaceRoots": [],
        "instructionSources": [],
        "activePermissionProfile": {"id": "going_bananas_coach", "extends": None},
        "sandbox": {"type": "readOnly", "networkAccess": False},
    },
)
req = request("turn/start")
msg = req["params"]["input"][0]["text"].removeprefix(
    "The athlete selected Sunday Review.\n\n"
)
result(req, {"turn": {"id": "turn"}})
active = tool("active_proposal")
assert active == {"proposal": None}, active
findings = tool("review_findings", {"include": "active"})
assert all(
    isinstance(findings[key], list)
    for key in ("findings", "patches", "review_recommended")
)
diff = tool(
    "coaching_query", {"name": "calendar_diff", "from_version": 0, "to_version": 1}
)
assert diff["query"] == "calendar_diff"
assert len(diff["data"]["changes"]) == 5 and all(
    row["op"] == "add" for row in diff["data"]["changes"]
)
snapshot = tool("coaching_snapshot", {"operation": "review_rolling_plan"})
if "error" in snapshot:
    finish("Snapshot error: " + str(snapshot["error"]))
    sys.exit()
assert snapshot["kb"]["excerpts"]
meta = snapshot["payload"]["snapshot_meta"]
run = next(
    row
    for row in snapshot["payload"]["calendar"]["sessions"]
    if row["kind"] == "run"
    and row["local_date"] > meta["as_of"]
    and not row.get("locked")
    and not row.get("completion_status")
)
assert run["planned_duration_s"] == 1800
if msg == "Could we add five minutes to my next easy run?":
    finish(
        "We could extend the next easy run from 30 to 35 minutes. Would you like to save that?"
    )
elif msg == "Yes, please save the 35-minute easy run for my review.":
    shape = tool("proposal_schema")
    assert shape["activation"] == "manual"
    document = {
        "schema_version": "coach_proposal.v2",
        "operation": meta["operation"],
        "snapshot_id": snapshot["snapshot_id"],
        "base_calendar_version": meta["calendar_version"],
        "base_block_version_id": meta["block_version_id"],
        "headline": "Add five easy minutes",
        "why": [
            {"kind": "inference", "text": "A small change to the existing aerobic run."}
        ],
        "uncertainty": ["Response to the extra time is unknown."],
        "change_triggers": [
            {"when": "The run feels harder", "then": "Return to the original duration."}
        ],
        "next_check": {
            "on": (date.fromisoformat(meta["as_of"]) + timedelta(days=7)).isoformat(),
            "check": "Review effort after the run.",
        },
        "confidence": {
            "decision": "moderate",
            "evidence": "moderate",
            "data": "moderate",
        },
        "changes": [
            {
                "change_id": "c1",
                "op": "modify",
                "session_uid": run["session_uid"],
                "after": {
                    "planned_duration_s": 2100,
                    "brief": {
                        "effort": {
                            "rpe_low": 3,
                            "rpe_high": 4,
                            "feel": "conversational",
                        },
                        "focus": ["Keep your shoulders relaxed."],
                        "adjust_if": [
                            {
                                "when": "Effort rises",
                                "then": "Finish at the original duration.",
                            }
                        ],
                        "why": "Build easy aerobic time gradually.",
                    },
                },
                "reason": "A short progression while keeping effort easy.",
            }
        ],
        "preserved": [],
        "evidence_ids": [],
        "policy_ids": [],
        "recipe_ids": [],
        "skill_version": "running-coach.v1",
    }
    saved = tool("save_pending_proposal", {"document": document})
    if saved.get("status") != "pending":
        finish("Save error: " + json.dumps(saved))
    else:
        finish("Pending your review: " + saved["review_path"])
else:
    raise AssertionError("unexpected synthetic athlete message")
