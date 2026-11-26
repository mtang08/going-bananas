"""Mode-scoped chat state and a process lease for one model turn at a time."""

from __future__ import annotations

import fcntl
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ChatProblem(BaseModel):
    code: str
    message: str


class ChatMessage(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    text: str
    client_message_id: UUID | None = None


class ChatReview(BaseModel):
    id: UUID | None = None
    status: Literal["idle", "running", "cancelled", "failed"] = "idle"
    messages: list[ChatMessage] = Field(default_factory=list)
    error: ChatProblem | None = None
    proposal_id: UUID | None = None
    codex_thread_id: str | None = None
    active_turn: UUID | None = None
    snapshot_ids: set[UUID] = Field(default_factory=set)
    observed_proposal: UUID | None = None
    read_active_proposal: bool = False


class ChatState(BaseModel):
    review: ChatReview = Field(default_factory=ChatReview)
    receipts: dict[UUID, str] = Field(default_factory=dict)


class ChatView(BaseModel):
    id: UUID | None
    status: Literal["idle", "running", "cancelled", "failed"]
    messages: list[ChatMessage]
    error: ChatProblem | None
    proposal_id: UUID | None
    proposal_revision: int | None = None


class ChatStore:
    def __init__(self, private_dir: Path, mode: str) -> None:
        self.directory = private_dir / "coach-chat" / mode
        self.path = self.directory / "state.json"

    def _open_lock(self, name: str) -> BinaryIO:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        return os.fdopen(os.open(self.directory / name, os.O_CREAT | os.O_RDWR, 0o600), "r+b")

    def lease(self) -> BinaryIO | None:
        lock = self._open_lock("turn.lock")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            return None
        except BaseException:
            lock.close()
            raise
        return lock

    def _read(self) -> ChatState:
        try:
            return ChatState.model_validate_json(self.path.read_bytes())
        except FileNotFoundError:
            return ChatState()

    def _recover(self, review: ChatReview) -> None:
        if review.status == "running" and (lease := self.lease()) is not None:
            lease.close()
            review.status = "failed"
            review.active_turn = None
            review.error = ChatProblem(code="interrupted", message="The coach stopped before finishing. Try again.")

    @contextmanager
    def transaction(self) -> Iterator[ChatState]:
        with self._open_lock("state.lock") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self._read()
            before = state.model_dump_json()
            self._recover(state.review)
            yield state
            after = state.model_dump_json()
            if after != before:
                self._write_file(self.path, after)

    def read(self) -> ChatReview:
        with self._open_lock("state.lock") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            review = self._read().review
            self._recover(review)
            return review

    def archive(self, review: ChatReview) -> None:
        if not review.id or not review.messages:
            return
        directory = self.directory / "reviews"
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / f"{review.id}.json"
        self._write_file(path, review.model_dump_json())

    @staticmethod
    def _write_file(path: Path, data: str) -> None:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".chat-", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(data.encode())
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
