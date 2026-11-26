"""Exercise the installed Codex transport against a local synthetic model."""

import asyncio
import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.api.coach_chat_tools import TOOL_DEFINITIONS
from app.services import coach_chat_runtime as runtime


def _advertised_tools(body: dict) -> dict:
    # Astra puts tools into a model input item instead of a top-level request field.
    entries = [item for item in body["input"] if item["type"] == "additional_tools"]
    packages = {namespace["name"]: namespace["tools"] for item in entries for namespace in item["tools"]}
    assert set(packages) == {"functions", runtime.TOOL_NAMESPACE}
    wrappers = {tool["name"]: tool for tool in packages["functions"]}
    assert set(wrappers) == {"exec", "wait"}
    for name in ("apply_patch", "exec_command", "view_image", "spawn_agent", "request_user_input"):
        assert f"### `{name}`" not in wrappers["exec"]["description"]
    tools = {tool["name"]: tool["parameters"] for tool in packages[runtime.TOOL_NAMESPACE]}
    expected = {tool["name"]: tool["inputSchema"] for tool in TOOL_DEFINITIONS}
    assert tools.keys() == expected.keys()
    for name, schema in tools.items():
        assert schema["type"] == "object"
        assert schema["properties"].keys() == expected[name]["properties"].keys()
        assert schema.get("additionalProperties") is False
    return tools


def _response_events(index: int, body: dict) -> list[dict]:
    response = {
        "id": f"resp_fixture_{index}",
        "object": "response",
        "created_at": 1,
        "model": runtime.MODEL,
        "status": "in_progress",
        "output": [],
    }
    tools = _advertised_tools(body)
    if index % 2 == 1:
        # The simulated model can call only a declared tool whose schema it received.
        assert "operation" in tools["coaching_snapshot"]["properties"]
        item = {
            "id": f"fc_fixture_{index}",
            "type": "function_call",
            "call_id": f"call_fixture_{index}",
            "namespace": runtime.TOOL_NAMESPACE,
            "name": "coaching_snapshot",
            "arguments": '{"operation":"review_rolling_plan"}',
            "status": "completed",
        }
        added = {**item, "arguments": "", "status": "in_progress"}
        deltas = []
    else:
        assert "synthetic evidence available" in json.dumps(body["input"])
        item = {
            "id": f"msg_fixture_{index}",
            "type": "message",
            "role": "assistant",
            "phase": "final_answer",
            "status": "completed",
            "content": [{"type": "output_text", "text": "Keep the easy run.", "annotations": []}],
        }
        added = {**item, "content": [], "status": "in_progress"}
        deltas = [
            {
                "type": "response.output_text.delta",
                "item_id": item["id"],
                "output_index": 0,
                "content_index": 0,
                "delta": delta,
            }
            for delta in ("Keep the ", "easy run.")
        ]

    return [
        {"type": "response.created", "response": response},
        {"type": "response.output_item.added", "output_index": 0, "item": added},
        *deltas,
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        {
            "type": "response.completed",
            "response": {
                **response,
                "status": "completed",
                "output": [item],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            },
        },
    ]


@pytest.mark.skipif(shutil.which("codex") is None, reason="The optional Codex CLI is missing.")
def test_installed_app_server_advertises_and_dispatches_only_coach_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = []
    failures = []

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert self.path == "/v1/responses"
                assert body["model"] == runtime.MODEL
                requests.append(body)
                events = _response_events(len(requests), body)
            except (AssertionError, KeyError, ValueError) as exc:
                failures.append(exc)
                self.send_error(400)
                return
            payload = b"".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode() for event in events)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *args: object) -> None:
            pass

    async def skip_account_check(_self, _server) -> None:
        # This is an isolated provider. Managed account auth is exercised separately.
        pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Provider) as provider:
        worker = threading.Thread(target=provider.serve_forever, daemon=True)
        worker.start()
        monkeypatch.setenv("OPENAI_API_KEY", "synthetic-local-key")
        monkeypatch.setattr(runtime, "INHERITED_ENV", (*runtime.INHERITED_ENV, "OPENAI_API_KEY"))
        monkeypatch.setattr(
            runtime,
            "LAUNCH_FLAGS",
            (*runtime.LAUNCH_FLAGS, "-c", f'openai_base_url="http://127.0.0.1:{provider.server_port}/v1"'),
        )
        monkeypatch.setattr(runtime.CoachChatRuntime, "_require_coach_model", skip_account_check)
        coach = runtime.CoachChatRuntime(mode="test", repo_root=tmp_path)
        threads = []
        calls = []
        deltas = []

        async def on_thread(thread_id: str) -> None:
            threads.append(thread_id)

        async def on_delta(text: str) -> None:
            deltas.append(text)

        async def call_tool(name: str, data: dict) -> dict:
            calls.append((name, data))
            return {"data": "synthetic evidence available"}

        async def turns() -> None:
            for message in ("Synthetic review", "Synthetic follow-up"):
                answer = await coach.run_turn(
                    thread_id=threads[0] if threads else None,
                    message=message,
                    instructions="Synthetic protocol test",
                    tool_definitions=TOOL_DEFINITIONS,
                    call_tool=call_tool,
                    on_thread=on_thread,
                    on_delta=on_delta,
                )
                assert answer == "Keep the easy run."

        try:
            asyncio.run(asyncio.wait_for(turns(), 35))
        finally:
            provider.shutdown()
            worker.join()
            assert not failures

    assert len(threads) == 1
    assert len(requests) == 4
    assert calls == [("coaching_snapshot", {"operation": "review_rolling_plan"})] * 2
    assert deltas == ["Keep the ", "easy run."] * 2
