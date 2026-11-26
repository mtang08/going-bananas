#!/usr/bin/env python3
"""Open the local dashboard or manage its optional macOS login agent."""

from __future__ import annotations

import fcntl
import http.client
import json
import os
import plistlib
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Literal, TypedDict
from urllib.parse import urlsplit
from xml.parsers.expat import ExpatError

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[1]
PRIVATE = ROOT / "private"
LOG = PRIVATE / "dashboard-launch.log"
LABEL = "com.local.going-bananas.dashboard"
URL = "http://127.0.0.1:8000"
LAUNCHCTL = "/bin/launchctl"
STARTUP_ACTIONS = {
    "login-startup-status": None,
    "login-startup-enable": True,
    "login-startup-disable": False,
}
PATH = ":".join(
    (
        "/opt/homebrew/opt/postgresql@17/bin",
        "/opt/homebrew/bin",
        "/usr/local/bin",
        str(Path.home() / ".local" / "bin"),
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    )
)


class LaunchError(Exception):
    def __init__(self, message: str, *, other_checkout: bool = False) -> None:
        super().__init__(message)
        self.other_checkout = other_checkout


class LoginStartup(TypedDict):
    status: Literal["enabled", "disabled", "unsupported", "other_checkout", "unavailable"]
    enabled: bool | None
    message: str | None


def agent_path() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def domain() -> str:
    return f"gui/{os.getuid()}"


def serve_command() -> list[str]:
    return [
        "/bin/bash",
        str(ROOT / "scripts" / "run"),
        shutil.which("python3", path=PATH) or sys.executable,
        str(SCRIPT),
        "serve",
    ]


def launchctl(*args: str) -> bool:
    return (
        subprocess.run(
            [LAUNCHCTL, *args],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).returncode
        == 0
    )


def agent_running() -> bool:
    return launchctl("print", f"{domain()}/{LABEL}")


def installed_agent(path: Path) -> dict | None:
    if path.is_symlink():
        raise LaunchError("The existing Going Bananas login item is a symbolic link. Check it before changing startup.")
    try:
        job = plistlib.loads(path.read_bytes())
    except FileNotFoundError:
        return None
    except (ValueError, OSError, ExpatError, plistlib.InvalidFileException) as exc:
        raise LaunchError("The existing Going Bananas login agent could not be read.") from exc
    if not isinstance(job, dict) or job.get("Label") != LABEL:
        raise LaunchError("The existing Going Bananas login item is malformed. Check it before changing startup.")
    args = job.get("ProgramArguments")
    if not isinstance(args, list) or len(args) != 5 or not all(isinstance(arg, str) for arg in args):
        raise LaunchError("The existing Going Bananas login item is malformed. Check it before changing startup.")
    command = serve_command()
    if args[:2] != command[:2] or args[-2:] != command[-2:] or job.get("WorkingDirectory") != str(ROOT):
        raise LaunchError(
            "A login agent already points to another Going Bananas checkout. Manage it there.",
            other_checkout=True,
        )
    return job


def launchd_disabled() -> bool:
    result = subprocess.run(
        [LAUNCHCTL, "print-disabled", domain()],
        check=False,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=3,
    )
    if result.returncode != 0:
        raise LaunchError("macOS could not read login startup. Open Going Bananas from your Mac desktop session.")
    for line in result.stdout.splitlines():
        name, marker, state = line.partition("=>")
        if not marker or name.strip().strip('"') != LABEL:
            continue
        state = state.strip().rstrip(",;")
        if state in {"enabled", "disabled", "true", "false"}:
            return state in {"disabled", "true"}
        raise LaunchError("macOS returned an unreadable login startup status.")
    return False


def _startup_state(path: Path) -> tuple[dict | None, bool]:
    job = installed_agent(path)
    disabled = launchd_disabled()
    if job is None and agent_running():
        raise LaunchError(
            "A Going Bananas login agent is registered but its settings file is missing. Sign out and in to reset it."
        )
    return job, disabled


def _starts_at_login(job: dict | None) -> bool:
    return job is not None and job.get("RunAtLoad") is True and job.get("Disabled") is not True


def _describe_startup(job: dict | None, disabled: bool) -> LoginStartup:
    enabled = _starts_at_login(job) and not disabled
    if job is None and not checkout_ready():
        return {
            "status": "unavailable",
            "enabled": None,
            "message": "Finish local setup and build Going Bananas before enabling login startup.",
        }
    return {
        "status": "enabled" if enabled else "disabled",
        "enabled": enabled,
        "message": None,
    }


def _startup_error(exc: Exception) -> LoginStartup:
    if isinstance(exc, LaunchError):
        status = "other_checkout" if exc.other_checkout else "unavailable"
        return {"status": status, "enabled": None, "message": str(exc)}
    return {
        "status": "unavailable",
        "enabled": None,
        "message": "macOS could not update login startup. Try again.",
    }


def supports_login_startup() -> bool:
    return sys.platform == "darwin" and os.getuid() != 0


def login_startup_status() -> LoginStartup:
    if not supports_login_startup():
        return {
            "status": "unsupported",
            "enabled": None,
            "message": "Login startup requires a macOS user session.",
        }
    try:
        return _describe_startup(*_startup_state(agent_path()))
    except (LaunchError, OSError, KeyError, subprocess.SubprocessError) as exc:
        return _startup_error(exc)


def health(check: str) -> dict:
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=0.5)
    try:
        connection.request("GET", f"/api/v1/health/{check}")
        response = connection.getresponse()
        if response.status != 200:
            return {}
        payload = json.loads(response.read(4096))
        if (
            isinstance(payload, dict)
            and payload.get("schema_version") == "v1"
            and payload.get("mode") in ("real", "demo", "test")
            and isinstance(payload.get("data"), dict)
        ):
            return payload
    except (OSError, ValueError, http.client.HTTPException):
        pass
    finally:
        connection.close()
    return {}


def has_coach(status: dict) -> bool:
    return status.get("data", {}).get("dashboard_coach") is True


def ready() -> bool:
    return has_coach(health("live")) and bool(health("ready"))


def port_in_use() -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", 8000)) == 0


def checkout_ready() -> bool:
    return (ROOT / ".env").is_file() and (ROOT / "frontend" / "dist" / "index.html").is_file()


def require_checkout() -> None:
    if not checkout_ready():
        raise LaunchError("Finish local database setup and build the app before launching this checkout.")
    PRIVATE.mkdir(mode=0o700, exist_ok=True)


def write_agent(path: Path) -> None:
    job = {
        "Label": LABEL,
        "ProgramArguments": serve_command(),
        "WorkingDirectory": str(ROOT),
        "EnvironmentVariables": {"PATH": PATH},
        "RunAtLoad": True,
        "StandardOutPath": str(LOG),
        "StandardErrorPath": str(LOG),
    }
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        staging = Path(output.name)
        try:
            plistlib.dump(job, output)
            output.flush()
            os.fsync(output.fileno())
            staging.replace(path)
        finally:
            staging.unlink(missing_ok=True)


def set_login_startup(enabled: bool) -> LoginStartup:
    if not supports_login_startup():
        return login_startup_status()
    try:
        path = agent_path()
        before = _describe_startup(*_startup_state(path))
        if before["enabled"] == enabled or before["status"] == "unavailable":
            return before
        if not path.parent.resolve().is_relative_to(path.parents[2].resolve()):
            raise LaunchError("The LaunchAgents directory points outside the macOS user's home.")
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.parent / f".{LABEL}.lock"
        with os.fdopen(os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), "r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return _change_startup(path, enabled)
    except (LaunchError, OSError, KeyError, subprocess.SubprocessError) as exc:
        return _startup_error(exc)


def _change_startup(path: Path, enabled: bool) -> LoginStartup:
    job, disabled = _startup_state(path)
    before = _describe_startup(job, disabled)
    if before["enabled"] == enabled or before["status"] == "unavailable":
        return before
    target = f"{domain()}/{LABEL}"
    if enabled:
        require_checkout()
        if disabled and not launchctl("enable", target):
            raise LaunchError("macOS could not enable the Going Bananas login agent.")
        if not _starts_at_login(job):
            write_agent(path)
    elif not launchctl("disable", target):
        raise LaunchError("macOS could not disable the Going Bananas login agent.")
    after = _describe_startup(*_startup_state(path))
    if after["enabled"] != enabled:
        raise LaunchError("macOS did not confirm the login startup setting. Try again.")
    return after


def open_dashboard(*, interactive: bool = False) -> None:
    live = health("live")
    if live:
        if not has_coach(live):
            raise LaunchError(
                "The running dashboard predates this Coach update. Stop it from the session that launched it, "
                "then choose Open again."
            )
        if not health("ready"):
            raise LaunchError(f"The dashboard is running but unavailable. See {LOG} for startup details.")
        mode = live["mode"]
        if mode != "real":
            print(f"Opening the running dashboard in {mode} mode.")
            if (
                interactive
                and show_dialog(
                    'button returned of (display dialog (item 1 of argv) with title "Going Bananas" '
                    'buttons {"Cancel", "Open"} default button "Open" cancel button "Cancel")',
                    f"The dashboard running on port 8000 uses {mode} mode. Open this workspace?",
                )
                != "Open"
            ):
                return
        subprocess.run(["/usr/bin/open", URL], check=True)
        return
    if port_in_use():
        raise LaunchError("Port 8000 is already in use. Check the local dashboard or the other service and try again.")
    require_checkout()
    if login_startup_status()["enabled"] is True and agent_running():
        if not launchctl("kickstart", f"{domain()}/{LABEL}"):
            raise LaunchError("macOS could not start the Going Bananas login agent.")
    else:
        with LOG.open("a") as journal:
            subprocess.Popen(
                serve_command(),
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=journal,
                stderr=journal,
                start_new_session=True,
            )
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if ready():
            subprocess.run(["/usr/bin/open", URL], check=True)
            return
        time.sleep(0.5)
    raise LaunchError(f"The dashboard is still unavailable. See {LOG} for details.")


def serve() -> None:
    if port_in_use():
        print("Port 8000 is occupied. Skipping startup.", flush=True)
        return
    require_checkout()
    database = urlsplit(os.environ.get("DATABASE_URL", ""))
    if database.hostname in {"127.0.0.1", "localhost", "::1"} and database.port == 55432:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "local-db.py"), "start-existing"],
            cwd=ROOT,
            check=True,
            start_new_session=True,
        )
    os.execv(sys.executable, [sys.executable, str(ROOT / "scripts" / "serve.py")])


def show_dialog(script: str, message: str) -> str:
    result = subprocess.run(
        [
            "/usr/bin/osascript",
            "-e",
            "on run argv",
            "-e",
            script,
            "-e",
            "end run",
            message,
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def choose() -> str:
    return show_dialog(
        'button returned of (display dialog (item 1 of argv) with title "Going Bananas" '
        'buttons {"Disable at Login", "Enable at Login", "Open"} default button "Open")',
        startup_message(login_startup_status()),
    )


def startup_message(startup: LoginStartup) -> str:
    if startup["message"]:
        return startup["message"]
    return "Start at Login is enabled." if startup["enabled"] else "Start at Login is disabled."


def main() -> int:
    os.umask(0o077)
    if len(sys.argv) == 2 and sys.argv[1] in STARTUP_ACTIONS:
        enabled = STARTUP_ACTIONS[sys.argv[1]]
        print(json.dumps(login_startup_status() if enabled is None else set_login_startup(enabled)))
        return 0
    if sys.platform != "darwin":
        print("Use make start on this platform.", file=sys.stderr)
        return 1
    os.environ["PATH"] = PATH + ":" + os.environ.get("PATH", "")
    interactive = len(sys.argv) == 1
    try:
        action = choose() if interactive else sys.argv[1]
        if action in {"Open", "open"}:
            open_dashboard(interactive=interactive)
        elif action in {"Enable at Login", "enable", "Disable at Login", "disable"}:
            enabled = action in {"Enable at Login", "enable"}
            startup = set_login_startup(enabled)
            if startup["enabled"] != enabled:
                raise LaunchError(startup_message(startup))
            if interactive:
                show_dialog(
                    'display dialog (item 1 of argv) with title "Going Bananas" buttons {"OK"}',
                    "Going Bananas will start at your next login."
                    if enabled
                    else "Going Bananas will stay closed at your next login. The current dashboard can keep running.",
                )
        elif action == "status":
            print(startup_message(login_startup_status()))
            live = health("live")
            if live and not has_coach(live):
                print(f"The running dashboard is in {live['mode']} mode and predates the Coach update.")
            elif live and health("ready"):
                print(f"Dashboard is ready in {live['mode']} mode.")
            else:
                print("Dashboard is unavailable.")
        elif action == "serve":
            serve()
        elif action:
            raise LaunchError("Use open, enable, disable, or status.")
        return 0
    except (LaunchError, OSError, subprocess.CalledProcessError) as exc:
        message = str(exc) if isinstance(exc, LaunchError) else f"Going Bananas could not start. See {LOG} for details."
        if interactive:
            with suppress(OSError):
                show_dialog(
                    'display dialog (item 1 of argv) with title "Going Bananas" buttons {"OK"}',
                    message,
                )
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
