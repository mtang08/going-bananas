"""Synthetic App Server messages shared by dashboard integration checks."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Any, cast
from uuid import uuid4

from app.services.coach_chat_runtime import EFFORT, MODEL, PERMISSIONS, TOOL_NAMESPACE, CoachChatRuntime
from app.services.coach_chat_runtime_protocol import AppServer

SIGN_IN_URL = "https://auth.openai.com/oauth/authorize?redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback"


def _plan(snapshot: dict) -> tuple[dict, int]:
    payload = snapshot["payload"]
    meta = payload["snapshot_meta"]
    as_of = date.fromisoformat(meta["as_of"])
    run = next(
        row
        for row in payload["calendar"]["sessions"]
        if row["kind"] == "run"
        and row["local_date"] > meta["as_of"]
        and not row.get("locked")
        and row["planned_duration_s"]
        and not row["completion_status"]
    )
    duration = run["planned_duration_s"] + 300
    document = {
        "schema_version": "coach_proposal.v2",
        "operation": meta["operation"],
        "snapshot_id": snapshot["snapshot_id"],
        "base_calendar_version": meta["calendar_version"],
        "base_block_version_id": meta["block_version_id"],
        "headline": "Add five easy minutes",
        "why": [{"kind": "inference", "text": "A small change to the existing aerobic run."}],
        "uncertainty": ["Response to the extra time is unknown."],
        "change_triggers": [{"when": "The run feels harder", "then": "Return to the original duration."}],
        "next_check": {"on": (as_of + timedelta(days=7)).isoformat(), "check": "Review effort after the run."},
        "confidence": {"decision": "moderate", "evidence": "moderate", "data": "moderate"},
        "changes": [
            {
                "change_id": "c1",
                "op": "modify",
                "session_uid": run["session_uid"],
                "after": {
                    "planned_duration_s": duration,
                    "brief": {
                        "effort": {"rpe_low": 3, "rpe_high": 4, "feel": "conversational"},
                        "focus": ["Keep your shoulders relaxed."],
                        "adjust_if": [{"when": "Effort rises", "then": "Finish at the original duration."}],
                        "why": "Build easy aerobic time gradually.",
                    },
                },
                "reason": "A short progression while keeping effort easy.",
            },
        ],
        "preserved": [],
        "evidence_ids": [],
        "policy_ids": [],
        "recipe_ids": [],
        "skill_version": "running-coach.v1",
    }
    return document, duration


class ScriptedCoachRuntime(CoachChatRuntime):
    def __init__(self, *args: Any, signed_in: bool = True, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.signed_in = signed_in
        self.sign_in_finished = asyncio.Event()
        self.started_turns: list[str] = []
        self.resumed_threads: list[str] = []
        self.login_starts = 0
        self.account_reads = 0
        self.draft_results: list[dict] = []
        self.held_turn = asyncio.Event()
        self.before_save: asyncio.Event | None = None
        self.save_ready = False
        self.interruptions = 0

    @asynccontextmanager
    async def _app_server(self) -> AsyncIterator[AppServer]:
        yield cast(AppServer, _ScriptedServer(self))


class _ScriptedServer:
    def __init__(self, runtime: ScriptedCoachRuntime) -> None:
        self.runtime = runtime
        self.thread_id = str(uuid4())
        self.turn_id = str(uuid4())
        self.response: dict = {}
        self.request_id = 0
        self.events: AsyncIterator[dict] | None = None

    async def request(self, method: str, params: dict) -> dict:
        if method == "account/read":
            self.runtime.account_reads += 1
            return {"account": {"type": "chatgpt"} if self.runtime.signed_in else None}
        if method == "account/login/start":
            self.runtime.login_starts += 1
            self.events = self._sign_in()
            return {"type": "chatgpt", "loginId": "synthetic-login", "authUrl": SIGN_IN_URL}
        if method == "account/login/cancel":
            return {"status": "cancelled"}
        if method == "model/list":
            return {"data": [{"model": MODEL, "supportedReasoningEfforts": [{"reasoningEffort": EFFORT}]}]}
        if method in ("thread/start", "thread/resume"):
            if method == "thread/resume":
                self.thread_id = params["threadId"]
                self.runtime.resumed_threads.append(self.thread_id)
            return {
                "model": MODEL,
                "reasoningEffort": EFFORT,
                "cwd": str(self.runtime.workspace),
                "modelProvider": "openai",
                "approvalPolicy": "never",
                "runtimeWorkspaceRoots": [],
                "instructionSources": [],
                "activePermissionProfile": {"id": PERMISSIONS, "extends": None},
                "sandbox": {"type": "readOnly", "networkAccess": False},
                "thread": {"id": self.thread_id, "ephemeral": False},
            }
        if method == "turn/start":
            text = params["input"][0]["text"]
            self.runtime.started_turns.append(text)
            self.events = self._turn(text)
            return {"turn": {"id": self.turn_id}}
        if method == "turn/interrupt":
            self.runtime.interruptions += 1
            self.events = self._completed("interrupted")
            return {}
        raise AssertionError(f"Unexpected protocol method {method}")

    async def _sign_in(self) -> AsyncIterator[dict]:
        await self.runtime.sign_in_finished.wait()
        self.runtime.signed_in = True
        yield {"method": "account/login/completed", "params": {"loginId": "synthetic-login", "success": True}}

    async def event(self) -> dict:
        assert self.events is not None
        return await anext(self.events)

    async def reject_request(self, event: dict) -> bool:
        return "id" in event

    async def respond_tool(self, request_id: int, result: dict, *, success: bool) -> None:
        assert request_id == self.request_id and success
        self.response = result

    def _notification(self, method: str, **params: Any) -> dict:
        return {"method": method, "params": {"threadId": self.thread_id, "turnId": self.turn_id, **params}}

    def _tool(self, name: str, arguments: dict | None = None) -> dict:
        self.request_id += 1
        return {
            "id": self.request_id,
            **self._notification("item/tool/call", namespace=TOOL_NAMESPACE, tool=name, arguments=arguments or {}),
        }

    async def _completed(self, status: str) -> AsyncIterator[dict]:
        yield self._notification("turn/completed", turn={"id": self.turn_id, "status": status})

    async def _turn(self, text: str) -> AsyncIterator[dict]:
        item = {"id": str(uuid4()), "type": "agentMessage", "phase": "final_answer"}
        if "hold this turn" in text.lower():
            yield self._notification("item/started", item=item)
            yield self._notification("item/agentMessage/delta", itemId=item["id"], delta="Checking the training log")
            await self.runtime.held_turn.wait()
        yield self._tool("active_proposal")
        active = self.response
        yield self._tool("review_findings")
        assert "review_recommended" in self.response
        yield self._tool("coaching_snapshot", {"operation": "review_rolling_plan"})
        snapshot = self.response
        assert snapshot["kb"]["excerpts"]
        lower = text.lower()
        if any(phrase in lower for phrase in ("looks good", "save it", "publish", "save a revision")):
            yield self._tool("proposal_schema")
            assert self.response["activation"] == "manual"
            document, _ = _plan(snapshot)
            arguments: dict = {"document": document}
            if active["proposal"] is not None:
                document["headline"] = "Keep the easy progression"
                arguments.update(
                    proposal_id=active["proposal_id"],
                    expected_revision=active["revision"],
                    reason="The athlete confirmed the updated draft.",
                )
            if self.runtime.before_save is not None:
                self.runtime.save_ready = True
                await self.runtime.before_save.wait()
            yield self._tool("save_pending_proposal", arguments)
            self.runtime.draft_results.append(self.response)
            if self.response.get("status") != "pending":
                reply = "The draft did not pass validation."
            else:
                reply = f"Pending your review; nothing applied. [Review the draft]({self.response['review_path']})"
        else:
            _, duration = _plan(snapshot)
            reply = f"I would extend the next easy run to {duration // 60} minutes at conversational effort."
        yield self._notification("item/completed", item={**item, "text": reply})
        yield self._notification("turn/completed", turn={"id": self.turn_id, "status": "completed"})
