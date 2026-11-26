"""The opt-in macOS login preference for the configured real dashboard."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from app.api.responses import Envelope
from app.config import AppMode, settings
from app.errors import fail

PATH = "/settings/login-startup"
ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "scripts" / "dashboard-login.py"
router = APIRouter(tags=["settings"])


class LoginStartup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["enabled", "disabled", "unsupported", "other_checkout", "unavailable"]
    enabled: StrictBool | None
    message: str | None


class StartupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool


def run_login_startup(enabled: bool | None) -> LoginStartup:
    if sys.platform != "darwin":
        return LoginStartup(status="unsupported", enabled=None, message="Login startup is available on macOS.")
    if settings.app_mode != AppMode.REAL:
        return LoginStartup(
            status="unsupported", enabled=None, message="Open the configured real dashboard to change login startup."
        )
    action = {None: "status", True: "enable", False: "disable"}[enabled]
    try:
        result = subprocess.run(
            [sys.executable, str(LAUNCHER), f"login-startup-{action}"],
            cwd=ROOT,
            env={"LC_ALL": "C"},
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=20,
        )
        return LoginStartup.model_validate_json(result.stdout)
    except (OSError, subprocess.SubprocessError, ValidationError):
        return LoginStartup(
            status="unavailable", enabled=None, message="The dashboard could not check login startup. Try again."
        )


def _envelope(data: LoginStartup) -> Envelope[LoginStartup]:
    return {"schema_version": "v1", "mode": AppMode(settings.app_mode), "data_revision": 0, "data": data}


@router.get(PATH)
def get_login_startup() -> Envelope[LoginStartup]:
    return _envelope(run_login_startup(None))


@router.put(PATH)
def put_login_startup(body: StartupInput) -> Envelope[LoginStartup]:
    startup = run_login_startup(body.enabled)
    if startup.enabled != body.enabled:
        fail(
            f"login_startup_{startup.status}",
            startup.message or "macOS did not confirm the login startup setting. Try again.",
            503 if startup.status == "unavailable" else 409,
        )
    return _envelope(startup)
