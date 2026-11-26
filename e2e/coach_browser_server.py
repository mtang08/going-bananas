"""Serve a disposable demo database and a scripted coach for Browser E2E."""

from __future__ import annotations

import os
import sys
from pathlib import Path


if os.getenv("APP_MODE") != "demo" or os.getenv("GB_COACH_BROWSER_TEST") != "1":
    raise SystemExit("The scripted browser coach requires an explicitly enabled demo server.")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "tests" / "fixtures"))

from app.api.coach_chat import get_chat_gateway  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from coach_chat_script import ScriptedCoachRuntime  # noqa: E402
from fastapi import APIRouter  # noqa: E402

runtime = ScriptedCoachRuntime(mode=settings.app_mode, repo_root=ROOT, signed_in=False)
get_chat_gateway().runtime = runtime
fixtures = APIRouter(prefix="/api/v1/__test/coach")


@fixtures.get("/state")
async def scripted_coach_state():
    return {"turns": len(runtime.started_turns), "resumes": len(runtime.resumed_threads)}


@fixtures.post("/sign-in")
async def complete_scripted_sign_in():
    runtime.sign_in_finished.set()
    return {"ok": True}


@fixtures.post("/release")
async def release_scripted_reply():
    runtime.held_turn.set()
    return {"ok": True}


app.router.routes[:0] = fixtures.routes


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=settings.port)
