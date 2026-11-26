#!/usr/bin/env python3
"""Open the local dashboard or manage its optional macOS login agent."""

from __future__ import annotations

import http.client
import json
import os
import plistlib
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[1]
PRIVATE = ROOT / "private"
LOG = PRIVATE / "dashboard-launch.log"
LABEL = "com.local.going-bananas.dashboard"
URL = "http://127.0.0.1:8000"
LAUNCHCTL = "/bin/launchctl"
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
    pass


def agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def domain() -> str:
    return f"gui/{os.getuid()}"


def serve_command() -> list[str]:
    return [
        "/bin/bash",
        str(ROOT / "scripts" / "run"),
        sys.executable,
        str(SCRIPT),
        "serve",
    ]


def launchctl(*args: str) -> bool:
    return (
        subprocess.run([LAUNCHCTL, *args], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        == 0
    )


def agent_running() -> bool:
    return launchctl("print", f"{domain()}/{LABEL}")


def owns_agent(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        job = plistlib.loads(path.read_bytes())
    except (ValueError, OSError, plistlib.InvalidFileException) as exc:
        raise LaunchError("The existing Going Bananas login agent could not be read.") from exc
    args = job.get("ProgramArguments", []) if isinstance(job, dict) else []
    if not isinstance(job, dict) or job.get("Label") != LABEL or len(args) != 5 or args[-2:] != [str(SCRIPT), "serve"]:
        raise LaunchError("A login agent already points to another Going Bananas checkout. Manage it there.")
    return True


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


def require_checkout() -> None:
    if not (ROOT / ".env").is_file() or not (ROOT / "frontend" / "dist" / "index.html").is_file():
        raise LaunchError("Finish local database setup and build the app before launching this checkout.")
    PRIVATE.mkdir(mode=0o700, exist_ok=True)


def enable_agent() -> None:
    require_checkout()
    path = agent_path()
    installed = owns_agent(path)
    if agent_running():
        if not installed:
            raise LaunchError("A Going Bananas login process is already registered for this Mac account.")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
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
        plistlib.dump(job, output)
        staging = Path(output.name)
    staging.replace(path)
    launchctl("enable", f"{domain()}/{LABEL}")
    if not launchctl("bootstrap", domain(), str(path)):
        if not installed:
            path.unlink(missing_ok=True)
        raise LaunchError("macOS could not enable the Going Bananas login agent.")


def disable_agent() -> None:
    path = agent_path()
    if not owns_agent(path):
        return
    if agent_running() and not launchctl("bootout", f"{domain()}/{LABEL}"):
        raise LaunchError("macOS could not stop the Going Bananas login agent.")
    path.unlink()


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
    if owns_agent(agent_path()) and agent_running():
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
    enabled = owns_agent(agent_path())
    status = "Start at Login is enabled." if enabled else "Start at Login is disabled."
    return show_dialog(
        'button returned of (display dialog (item 1 of argv) with title "Going Bananas" '
        'buttons {"Disable at Login", "Enable at Login", "Open"} default button "Open")',
        status,
    )


def main() -> int:
    os.umask(0o077)
    if sys.platform != "darwin":
        print("Use make start on this platform.", file=sys.stderr)
        return 1
    os.environ["PATH"] = PATH + ":" + os.environ.get("PATH", "")
    interactive = len(sys.argv) == 1
    try:
        action = choose() if interactive else sys.argv[1]
        if action in {"Open", "open"}:
            open_dashboard(interactive=interactive)
        elif action in {"Enable at Login", "enable"}:
            enable_agent()
            if interactive:
                show_dialog(
                    'display dialog (item 1 of argv) with title "Going Bananas" buttons {"OK"}',
                    "Going Bananas will start at login. Choose Open to launch the dashboard in your browser.",
                )
        elif action in {"Disable at Login", "disable"}:
            disable_agent()
        elif action == "status":
            print("Start at Login is enabled." if owns_agent(agent_path()) else "Start at Login is disabled.")
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
