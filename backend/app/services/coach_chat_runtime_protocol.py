"""The stdio subset of the Codex App Server JSON-RPC protocol used by chat."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

MAX_LINE = 4 * 1024 * 1024
REQUEST_SECONDS = 30

JsonObject = dict[str, Any]


class CoachRuntimeError(Exception):
    """An error suitable for returning through the dashboard API."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AppServer:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        assert process.stdin is not None and process.stdout is not None
        self.process = process
        self.input = process.stdin
        self.output = process.stdout
        self.sequence = 0
        self.pending: deque[JsonObject] = deque()

    @classmethod
    @asynccontextmanager
    async def spawn(cls, command: tuple[str, ...], cwd: Path, environment: dict[str, str]) -> AsyncIterator[AppServer]:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                env=environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=MAX_LINE,
                umask=0o077,
            )
        except FileNotFoundError as exc:
            raise CoachRuntimeError(
                "not_installed", "Install the Codex CLI on the machine running Going Bananas."
            ) from exc
        except OSError as exc:
            raise CoachRuntimeError("turn_failed", "The dashboard could not start the local Codex App Server.") from exc
        server = cls(process)
        try:
            await server.request(
                "initialize",
                {
                    "clientInfo": {"name": "going_bananas_coach", "title": "Going Bananas Coach", "version": "1.0"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            await server.send({"method": "initialized"})
            yield server
        finally:
            await server.close()

    async def close(self) -> None:
        self.input.close()
        try:
            async with asyncio.timeout(2):
                await self.process.communicate()
        except TimeoutError:
            with suppress(ProcessLookupError):
                self.process.kill()
            await self.process.communicate()

    async def send(self, message: JsonObject) -> None:
        try:
            self.input.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
            await self.input.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise CoachRuntimeError("turn_failed", "The local Codex App Server stopped responding. Try again.") from exc

    async def receive(self) -> JsonObject:
        try:
            line = await self.output.readline()
            if not line:
                raise CoachRuntimeError(
                    "turn_failed", "The local Codex App Server stopped. Check the Codex installation and try again."
                )
            message = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            raise CoachRuntimeError("turn_failed", "The local Codex App Server returned an invalid message.") from exc
        if not isinstance(message, dict):
            raise CoachRuntimeError("turn_failed", "The local Codex App Server returned an invalid message.")
        return message

    async def request(self, method: str, params: JsonObject) -> JsonObject:
        self.sequence += 1
        request_id = self.sequence
        try:
            async with asyncio.timeout(REQUEST_SECONDS):
                await self.send({"method": method, "id": request_id, "params": params})
                while True:
                    received = await self.receive()
                    if "method" in received:
                        if len(self.pending) >= 2048:
                            raise CoachRuntimeError("turn_failed", "Codex sent too many messages.")
                        self.pending.append(received)
                    elif received.get("id") == request_id:
                        result = received.get("result")
                        if isinstance(result, dict):
                            return result
                        raise _request_error(method)
        except TimeoutError as exc:
            raise CoachRuntimeError(
                "timeout", "The local Codex App Server took too long to respond. Try again."
            ) from exc

    async def event(self) -> JsonObject:
        return self.pending.popleft() if self.pending else await self.receive()

    async def reject_request(self, message: JsonObject) -> bool:
        if "method" not in message or "id" not in message:
            return False
        await self.send(
            {"id": message["id"], "error": {"code": -32601, "message": "This dashboard capability is unavailable."}}
        )
        return True

    async def respond_tool(self, request_id: str | int, result: JsonObject, *, success: bool) -> None:
        await self.send(
            {
                "id": request_id,
                "result": {
                    "success": success,
                    "contentItems": [{"type": "inputText", "text": json.dumps(result, ensure_ascii=False)}],
                },
            }
        )


def _request_error(method: str) -> CoachRuntimeError:
    if method == "thread/resume":
        return CoachRuntimeError(
            "turn_failed", "Codex could not reopen this conversation. Try again or start a new chat."
        )
    if method == "account/login/start":
        return CoachRuntimeError("auth_required", "Codex could not start ChatGPT sign-in. Try again.")
    return CoachRuntimeError("turn_failed", "The local Codex App Server could not process this request. Try again.")
