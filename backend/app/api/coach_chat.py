"""Local dashboard chat, pending proposal links, and explicit ChatGPT sign-in."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Annotated, BinaryIO, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.orm import Session

from app.api.coach import active_proposal
from app.api.coach_chat_tools import TOOL_DEFINITIONS, call_coach_tool
from app.api.responses import Envelope, response_envelope
from app.coach_v2_models import CoachProposal
from app.config import settings
from app.db import SessionLocal, get_session
from app.errors import fail
from app.logs import exception_summary, get
from app.services.coach_chat_runtime import CoachChatRuntime, CoachRuntimeError, load_coach_instructions
from app.services.coach_chat_store import ChatMessage, ChatProblem, ChatReview, ChatStore, ChatView
from app.services.decision_inputs import digest

router = APIRouter(prefix="/coach/chat", tags=["coach"])
REPO_ROOT = Path(__file__).resolve().parents[3]
MAX_REPLY_CHARS = 60_000
AUTH_CACHE_SECONDS = 30


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: UUID | None = None


class MessageInput(ReviewInput):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
    client_message_id: UUID
    intent: Literal["sunday_review", "today_run"] | None = None


class AuthInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthView(BaseModel):
    status: Literal["idle", "waiting", "signed_out", "signed_in", "failed", "cancelled"] = "idle"
    url: str | None = None
    error: ChatProblem | None = None


@dataclass
class RunningTurn:
    id: UUID
    response_id: UUID = field(default_factory=uuid4)
    reply: str = ""
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


def _guard_review(body: ReviewInput, review: ChatReview) -> None:
    if "thread_id" in body.model_fields_set and body.thread_id != review.id:
        fail("chat_review_changed", "The coaching review changed. Refresh it before trying again.", 409)


def _problem(exc: Exception) -> ChatProblem:
    if isinstance(exc, CoachRuntimeError):
        return ChatProblem(code=exc.code, message=str(exc))
    get("coach_chat").error("dashboard coach failed %s", exception_summary(exc))
    return ChatProblem(code="turn_failed", message="The coach could not finish this request. Try again.")


def _message_text(body: MessageInput) -> str:
    match body.intent:
        case "sunday_review":
            return f"The athlete selected Sunday Review.\n\n{body.text}"
        case "today_run":
            return f"The athlete selected Review Today's Run.\n\n{body.text}"
        case _:
            return body.text


class CoachChatGateway:
    def __init__(
        self,
        store: ChatStore,
        runtime: CoachChatRuntime,
        *,
        session_factory: Callable[[], Session],
        instructions: Callable[[], str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.runtime = runtime
        self.session_factory = session_factory
        self.instructions = instructions
        self.clock = clock
        self.turn: RunningTurn | None = None
        self.auth = AuthView()
        self.auth_checked_at = -float("inf")
        self.auth_lock = asyncio.Lock()
        self.login_task: asyncio.Task[None] | None = None

    def view(self, session: Session) -> ChatView:
        review = self.store.read()
        messages = list(review.messages)
        turn = self.turn
        if turn and turn.id == review.active_turn and turn.reply:
            messages.append(ChatMessage(id=turn.response_id, role="assistant", text=turn.reply))
        proposal = active_proposal(session)
        if proposal is None and review.proposal_id is not None:
            proposal = session.get(CoachProposal, review.proposal_id)
        return ChatView(
            id=review.id,
            status=review.status,
            messages=messages,
            error=review.error,
            proposal_id=proposal.id if proposal else None,
            proposal_revision=proposal.revision if proposal else None,
        )

    def _enqueue(self, body: MessageInput, turn_id: UUID) -> tuple[BinaryIO, str | None] | None:
        receipt = digest({"text": body.text, "intent": body.intent})
        lease: BinaryIO | None = None
        try:
            with self.store.transaction() as state:
                previous = state.receipts.get(body.client_message_id)
                if previous is not None:
                    if previous != receipt:
                        fail("chat_message_conflict", "This message ID was already used for a different message.", 409)
                    return None
                review = state.review
                _guard_review(body, review)
                lease = self.store.lease()
                if lease is None:
                    fail("chat_running", "The coach is still finishing a turn. Wait or stop the turn first.", 409)
                thread_id = review.codex_thread_id
                review.id = review.id or uuid4()
                review.status = "running"
                review.error = None
                review.active_turn = turn_id
                review.messages.append(
                    ChatMessage(id=turn_id, role="user", text=body.text, client_message_id=body.client_message_id)
                )
                state.receipts[body.client_message_id] = receipt
            return lease, thread_id
        except BaseException:
            if lease is not None:
                lease.close()
            raise

    async def send(self, body: MessageInput) -> None:
        turn = RunningTurn(id=uuid4())
        queued = await asyncio.to_thread(self._enqueue, body, turn.id)
        if queued is not None:
            lease, thread_id = queued
            self.turn = turn
            turn.task = asyncio.create_task(self._run(turn, lease, thread_id, _message_text(body)))

    async def _watch_stop(self, turn: RunningTurn) -> None:
        while not turn.wake.is_set():
            review = await asyncio.to_thread(self.store.read)
            if review.status != "running" or review.active_turn != turn.id:
                return
            try:
                await asyncio.wait_for(turn.wake.wait(), timeout=0.35)
            except TimeoutError:
                pass

    async def _run(self, turn: RunningTurn, lease: BinaryIO, thread_id: str | None, message: str) -> None:
        async def save_thread(value: str) -> None:
            def persist() -> None:
                with self.store.transaction() as state:
                    if state.review.active_turn == turn.id:
                        state.review.codex_thread_id = value

            await asyncio.to_thread(persist)

        async def add_delta(value: str) -> None:
            turn.reply = (turn.reply + value)[:MAX_REPLY_CHARS]

        async def call_tool(name: str, arguments: dict) -> dict:
            call = asyncio.create_task(
                asyncio.to_thread(
                    call_coach_tool, self.store, self.session_factory, turn.id, name, arguments, now=self.clock()
                )
            )
            try:
                return await asyncio.shield(call)
            except asyncio.CancelledError:
                await asyncio.gather(call, return_exceptions=True)
                raise

        problem = None
        reply = ""
        tasks: list[asyncio.Task] = []
        try:
            review = await asyncio.to_thread(self.store.read)
            if turn.wake.is_set() or review.active_turn != turn.id:
                return
            instructions = self.instructions()
            runtime = asyncio.create_task(
                self.runtime.run_turn(
                    thread_id=thread_id,
                    message=message,
                    instructions=instructions,
                    tool_definitions=TOOL_DEFINITIONS,
                    call_tool=call_tool,
                    on_thread=save_thread,
                    on_delta=add_delta,
                )
            )
            stop = asyncio.create_task(self._watch_stop(turn))
            tasks.extend((runtime, stop))
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if runtime in done:
                reply = runtime.result()[:MAX_REPLY_CHARS]
                if not reply.strip():
                    raise CoachRuntimeError("turn_failed", "The coach returned an empty reply. Try again.")
            else:
                stop.result()
        except Exception as exc:
            problem = _problem(exc)
            if problem.code == "auth_required" and self.auth.status != "waiting":
                self.auth = AuthView(status="signed_out")
                self.auth_checked_at = monotonic()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await asyncio.to_thread(self._finish, turn, reply, problem)
            finally:
                lease.close()
                if self.turn is turn:
                    self.turn = None

    def _finish(self, turn: RunningTurn, reply: str, problem: ChatProblem | None) -> None:
        with self.store.transaction() as state:
            review = state.review
            if review.active_turn != turn.id:
                return
            review.active_turn = None
            if reply and problem is None:
                review.messages.append(ChatMessage(id=turn.response_id, role="assistant", text=reply))
                review.status = "idle"
            else:
                review.status = "failed"
                review.error = problem or ChatProblem(code="interrupted", message="The coach stopped before finishing.")

    async def cancel(self, body: ReviewInput) -> None:
        def mark_cancelled() -> UUID | None:
            with self.store.transaction() as state:
                review = state.review
                _guard_review(body, review)
                turn_id = review.active_turn
                if turn_id is not None:
                    review.status = "cancelled"
                    review.active_turn = None
                    review.error = None
                return turn_id

        turn_id = await asyncio.to_thread(mark_cancelled)
        turn = self.turn
        if turn and turn.id == turn_id and turn.task:
            turn.wake.set()
            await asyncio.shield(turn.task)

    def new(self, body: ReviewInput) -> None:
        with self.store.transaction() as state:
            _guard_review(body, state.review)
            if state.review.status == "running":
                fail("chat_running", "Stop the current turn before starting a new review.", 409)
            self.store.archive(state.review)
            state.review = ChatReview(id=uuid4())

    async def auth_status(self) -> AuthView:
        async with self.auth_lock:
            current = self.auth
            if current.status in ("idle", "signed_out", "signed_in") and (
                monotonic() - self.auth_checked_at >= AUTH_CACHE_SECONDS
            ):
                try:
                    signed_in = await self.runtime.auth_status()
                    status = AuthView(status="signed_in" if signed_in else "signed_out")
                except Exception as exc:
                    status = AuthView(status="failed", error=_problem(exc))
                if self.auth is current:
                    self.auth = status
                    self.auth_checked_at = monotonic()
            return self.auth

    def start_login(self) -> AuthView:
        if self.login_task is None and self.auth.status != "signed_in":
            self.auth = AuthView(status="waiting")
            self.login_task = asyncio.create_task(self._login())
        return self.auth

    async def _login(self) -> None:
        async def show_url(url: str) -> None:
            try:
                parsed = urlsplit(url)
                valid = (
                    parsed.scheme == "https"
                    and parsed.netloc == "auth.openai.com"
                    and parsed.path == "/oauth/authorize"
                    and not parsed.fragment
                )
            except ValueError:
                valid = False
            if not valid:
                raise CoachRuntimeError("auth_required", "Codex did not provide a valid ChatGPT sign-in link.")
            self.auth = AuthView(status="waiting", url=url)

        try:
            await self.runtime.run_login(on_url=show_url)
            self.auth = AuthView(status="signed_in")
            self.auth_checked_at = monotonic()
        except asyncio.CancelledError:
            self.auth = AuthView(status="cancelled")
            raise
        except Exception as exc:
            self.auth = AuthView(status="failed", error=_problem(exc))
        finally:
            self.login_task = None

    async def cancel_login(self) -> AuthView:
        task = self.login_task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if self.login_task is task:
                self.login_task = None
                self.auth = AuthView(status="cancelled")
        return self.auth

    async def shutdown(self) -> None:
        if (turn := self.turn) is not None and turn.task:
            turn.wake.set()
            await asyncio.gather(turn.task, return_exceptions=True)
        await self.cancel_login()


_gateway = CoachChatGateway(
    ChatStore(settings.private_dir, settings.app_mode),
    CoachChatRuntime(mode=settings.app_mode, repo_root=REPO_ROOT),
    session_factory=SessionLocal,
    instructions=lambda: load_coach_instructions(REPO_ROOT),
)


def get_chat_gateway() -> CoachChatGateway:
    return _gateway


def _view(session: Session, gateway: CoachChatGateway) -> Envelope[ChatView]:
    return response_envelope(session, gateway.view(session))


@router.get("")
def get_chat(
    session: Session = Depends(get_session), gateway: CoachChatGateway = Depends(get_chat_gateway)
) -> Envelope[ChatView]:
    return _view(session, gateway)


@router.post("/messages")
async def post_message(
    body: MessageInput, session: Session = Depends(get_session), gateway: CoachChatGateway = Depends(get_chat_gateway)
) -> Envelope[ChatView]:
    await gateway.send(body)
    return await asyncio.to_thread(_view, session, gateway)


@router.post("/cancel")
async def post_cancel(
    body: ReviewInput, session: Session = Depends(get_session), gateway: CoachChatGateway = Depends(get_chat_gateway)
) -> Envelope[ChatView]:
    await gateway.cancel(body)
    return await asyncio.to_thread(_view, session, gateway)


@router.post("/new")
def post_new_review(
    body: ReviewInput, session: Session = Depends(get_session), gateway: CoachChatGateway = Depends(get_chat_gateway)
) -> Envelope[ChatView]:
    gateway.new(body)
    return _view(session, gateway)


@router.get("/auth")
async def get_auth(
    session: Session = Depends(get_session), gateway: CoachChatGateway = Depends(get_chat_gateway)
) -> Envelope[AuthView]:
    return response_envelope(session, await gateway.auth_status())


@router.post("/auth/start")
async def post_auth_start(
    body: AuthInput, session: Session = Depends(get_session), gateway: CoachChatGateway = Depends(get_chat_gateway)
) -> Envelope[AuthView]:
    return response_envelope(session, gateway.start_login())


@router.post("/auth/cancel")
async def post_auth_cancel(
    body: AuthInput, session: Session = Depends(get_session), gateway: CoachChatGateway = Depends(get_chat_gateway)
) -> Envelope[AuthView]:
    return response_envelope(session, await gateway.cancel_login())
