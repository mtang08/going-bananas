import asyncio
import json
import sys
from pathlib import Path

import pytest

from app.services import coach_chat_runtime as runtime

SERVER = r"""
import json
import os
import sys
from pathlib import Path

scenario = os.environ.get('USER')
log = Path(os.environ['CODEX_HOME']) / 'rpc.jsonl'
rollout = Path('thread.json')
thread = {'id': 'thread-1', 'ephemeral': False}
turn = {'id': 'turn-1'}
identity = {'threadId': 'thread-1', 'turnId': 'turn-1'}
answer = {'type': 'agentMessage', 'id': 'answer', 'phase': 'final_answer', 'text': 'Keep the easy run.'}
tool_recipient = 'tool-1'

def send(message):
    print(json.dumps(message), flush=True)

def event(method, params, request_id=None):
    message = {'method': method, 'params': params}
    if request_id:
        message['id'] = request_id
    send(message)

for line in sys.stdin:
    message = json.loads(line)
    with log.open('a') as records:
        records.write(json.dumps(message) + '\n')
    method = message.get('method')
    request_id = message.get('id')
    params = message.get('params', {})
    if method == 'initialized':
        continue
    if method == 'initialize':
        result = {}
    elif method == 'account/read':
        result = {'account': None if scenario.startswith('login') or scenario == 'unsigned' else {'type':'chatgpt'}}
    elif method == 'model/list':
        options = [] if scenario == 'model' else [{'reasoningEffort': 'medium'}]
        result = {'data': [{'model': 'gpt-6-astra', 'supportedReasoningEfforts': options}]}
    elif method in ('thread/start', 'thread/resume'):
        if method == 'thread/resume':
            assert rollout.read_text() == params['threadId']
        result = {
            'thread': thread,
            'model': 'gpt-6-astra',
            'modelProvider': 'openai',
            'reasoningEffort': 'medium',
            'cwd': os.getcwd(),
            'approvalPolicy': 'never',
            'runtimeWorkspaceRoots': [],
            'instructionSources': [],
            'activePermissionProfile': {'id': 'going_bananas_coach', 'extends': None},
            'sandbox': {'type': 'readOnly', 'networkAccess': scenario == 'profile'},
        }
    elif method == 'turn/start':
        rollout.write_text(thread['id'])
        send({'id': request_id, 'result': {'turn': turn}})
        event('item/commandExecution/requestApproval', identity, 'approval')
        if scenario == 'cancel':
            continue
        arguments = {**identity, 'tool': 'active_proposal', 'arguments': {}, 'namespace': None}
        event('item/tool/call', arguments, tool_recipient)
        continue
    elif request_id == tool_recipient and 'result' in message:
        if scenario == 'turn-failure':
            error = {'message': 'very-private', 'codexErrorInfo': 'unauthorized'}
            event('turn/completed', {'threadId': thread['id'], 'turn': {**turn, 'status': 'failed', 'error': error}})
            continue
        thinking = {'type': 'agentMessage', 'id': 'progress', 'phase': 'commentary', 'text': 'Internal progress.'}
        event('item/started', {**identity, 'item': thinking})
        event('item/agentMessage/delta', {**identity, 'itemId': thinking['id'], 'delta': thinking['text']})
        event('item/completed', {**identity, 'item': thinking})
        event('item/started', {**identity, 'item': {**answer, 'text': ''}})
        event('item/agentMessage/delta', {**identity, 'itemId': answer['id'], 'delta': 'Keep the '})
        event('item/agentMessage/delta', {**identity, 'itemId': answer['id'], 'delta': 'easy run.'})
        event('item/completed', {**identity, 'item': answer})
        event('turn/completed', {'threadId': thread['id'], 'turn': {**turn, 'status': 'completed', 'items':[answer]}})
        continue
    elif method == 'turn/interrupt':
        event('turn/completed', {'threadId': thread['id'], 'turn': {**turn, 'status': 'interrupted'}})
        result = {}
    elif method == 'account/login/start':
        host = 'attacker.example' if scenario == 'login-invalid' else 'auth.openai.com'
        url = f'https://{host}/oauth/authorize?redirect_uri=http%3A%2F%2F127.0.0.1%3A1455%2Fauth%2Fcallback'
        result = {'type': 'chatgpt', 'loginId': 'login-1', 'authUrl': url}
        if scenario == 'login-ok':
            event('account/login/completed', {'loginId': 'login-1', 'success': True})
    elif method == 'account/login/cancel':
        result = {}
    else:
        continue
    send({'id': request_id, 'result': result})
"""


@pytest.fixture
def coach(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> runtime.CoachChatRuntime:
    binary = tmp_path / "codex"
    binary.write_text(f"#!{sys.executable}\n" + SERVER, encoding="utf-8")
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("USER", "ok")
    return runtime.CoachChatRuntime(mode="demo", repo_root=tmp_path)


def records(coach: runtime.CoachChatRuntime) -> list[dict]:
    return [json.loads(line) for line in (coach.home / "rpc.jsonl").read_text().splitlines()]


class Callbacks:
    def __init__(self) -> None:
        self.threads: list[str] = []
        self.deltas: list[str] = []
        self.calls: list[tuple[str, dict]] = []
        self.started = asyncio.Event()

    async def on_thread(self, thread_id: str) -> None:
        self.threads.append(thread_id)
        self.started.set()

    async def on_delta(self, delta: str) -> None:
        self.deltas.append(delta)

    async def call_tool(self, tool: str, arguments: dict) -> dict:
        self.calls.append((tool, arguments))
        return {"data": {"proposal": None}}

    async def run(self, coach: runtime.CoachChatRuntime, thread: str | None = None) -> str:
        return await coach.run_turn(
            thread_id=thread,
            message="Sunday review",
            instructions="Trusted coaching instructions",
            tool_definitions=[
                {"name": "active_proposal", "description": "Read current draft", "inputSchema": {"type": "object"}}
            ],
            call_tool=self.call_tool,
            on_thread=self.on_thread,
            on_delta=self.on_delta,
        )


def test_replies_stream_and_reopen_durable_thread(coach: runtime.CoachChatRuntime) -> None:
    async def exercise() -> None:
        callbacks = Callbacks()
        assert await callbacks.run(coach) == "Keep the easy run."
        assert callbacks.threads == ["thread-1"]
        assert callbacks.deltas == ["Keep the ", "easy run."]
        assert callbacks.calls == [("active_proposal", {})]
        assert await Callbacks().run(coach, callbacks.threads[0]) == "Keep the easy run."

    asyncio.run(exercise())
    calls = records(coach)
    start = next(call["params"] for call in calls if call.get("method") == "thread/start")
    assert start["dynamicTools"][0]["type"] == "function"
    assert start["developerInstructions"] == "Trusted coaching instructions"
    assert start["environments"] == start["runtimeWorkspaceRoots"] == []
    turn = next(call["params"] for call in calls if call.get("method") == "turn/start")
    assert turn["input"] == [{"type": "text", "text": "Sunday review", "text_elements": []}]
    assert turn["model"] == "gpt-6-astra" and turn["effort"] == "medium"
    assert any("error" in call for call in calls if call.get("id") == "approval")
    assert any(call.get("method") == "thread/resume" for call in calls)


@pytest.mark.parametrize(
    ("scenario", "code"),
    [("unsigned", "auth_required"), ("model", "model_unavailable"), ("profile", "turn_failed")],
)
def test_runtime_checks_access_before_starting_a_turn(
    coach: runtime.CoachChatRuntime, monkeypatch: pytest.MonkeyPatch, scenario: str, code: str
) -> None:
    monkeypatch.setenv("USER", scenario)
    with pytest.raises(runtime.CoachRuntimeError) as caught:
        asyncio.run(Callbacks().run(coach))
    assert caught.value.code == code
    assert all(call.get("method") != "turn/start" for call in records(coach))


def test_turn_failure_hides_provider_message(coach: runtime.CoachChatRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USER", "turn-failure")
    with pytest.raises(runtime.CoachRuntimeError) as caught:
        asyncio.run(Callbacks().run(coach))
    assert caught.value.code == "auth_required"
    assert "very-private" not in str(caught.value)


def test_cancel_interrupts_the_owned_turn(coach: runtime.CoachChatRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USER", "cancel")

    async def exercise() -> None:
        callbacks = Callbacks()
        task = asyncio.create_task(callbacks.run(coach))
        await asyncio.wait_for(callbacks.started.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert any(call.get("method") == "turn/interrupt" for call in records(coach))


@pytest.mark.parametrize("scenario", ["login-ok", "login-invalid"])
def test_managed_sign_in_checks_its_url(
    coach: runtime.CoachChatRuntime, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    monkeypatch.setenv("USER", scenario)
    urls = []

    async def on_url(url: str) -> None:
        urls.append(url)

    if scenario == "login-ok":
        asyncio.run(coach.run_login(on_url=on_url))
        assert len(urls) == 1 and urls[0].startswith("https://auth.openai.com/oauth/authorize?")
    else:
        with pytest.raises(runtime.CoachRuntimeError, match="invalid ChatGPT sign-in link"):
            asyncio.run(coach.run_login(on_url=on_url))
        assert urls == []
        assert any(call.get("method") == "account/login/cancel" for call in records(coach))
