"""Verify Finder opens the supervised native dashboard without desktop side effects."""

import importlib.util
import json
import subprocess
from contextlib import ExitStack
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit


def exercise_finder(base: str, checkout: Path) -> None:
    target = urlsplit(base)
    assert target.hostname == "127.0.0.1" and target.port
    launcher_path = Path(__file__).resolve().parents[1] / "dashboard-login.py"
    spec = importlib.util.spec_from_file_location("finder_launcher", launcher_path)
    assert spec and spec.loader
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)

    # Native settings in a synthetic mode report unsupported; the native
    # handler must return before consulting any host launchd preference.
    conn = HTTPConnection(target.hostname, target.port, timeout=3)
    try:
        conn.request("GET", "/api/v1/settings/login-startup")
        response = conn.getresponse()
        packet = json.loads(response.read())
        assert response.status == 200 and packet["mode"] == "test"
        assert (
            packet["data"]["status"] == "unsupported"
            and packet["data"]["enabled"] is None
        )
    finally:
        conn.close()

    home = checkout.parent / "finder-home"
    plist = home / "Library" / "LaunchAgents" / f"{launcher.LABEL}.plist"
    (checkout / ".env").touch()
    dist = checkout / "frontend/dist"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").touch()
    calls = []
    started = False

    def connect(host, port, timeout):
        assert (host, port) == ("127.0.0.1", 8000)
        if not started:
            connection = Mock()
            connection.request.side_effect = ConnectionRefusedError()
            return connection
        return HTTPConnection(target.hostname, target.port, timeout=timeout)

    def start(command, **kwargs):
        nonlocal started
        assert command == launcher.serve_command() and kwargs["cwd"] == checkout
        assert kwargs["start_new_session"] and not started
        calls.append("start")
        started = True

    def process(command, **kwargs):
        if command == ["/usr/bin/open", launcher.URL]:
            assert started
            calls.append("open")
            return subprocess.CompletedProcess(command, 0)
        if command == [launcher.LAUNCHCTL, "print-disabled", launcher.domain()]:
            calls.append("preference")
            return subprocess.CompletedProcess(command, 0, stdout="")
        if command == [
            launcher.LAUNCHCTL,
            "print",
            f"{launcher.domain()}/{launcher.LABEL}",
        ]:
            calls.append("registered")
            return subprocess.CompletedProcess(command, 1)
        raise AssertionError(f"unexpected desktop command {command[0]}")

    with ExitStack() as stack:
        for attr, value in {
            "ROOT": checkout,
            "PRIVATE": checkout / "private",
            "LOG": checkout / "private/finder-test.log",
            "SCRIPT": checkout / "scripts/dashboard-login.py",
        }.items():
            stack.enter_context(patch.object(launcher, attr, value))
        stack.enter_context(patch.object(launcher, "agent_path", return_value=plist))
        stack.enter_context(
            patch.object(launcher, "supports_login_startup", return_value=True)
        )
        stack.enter_context(patch.object(launcher, "port_in_use", return_value=False))
        stack.enter_context(
            patch.object(launcher.http.client, "HTTPConnection", side_effect=connect)
        )
        stack.enter_context(
            patch.object(launcher.subprocess, "run", side_effect=process)
        )
        stack.enter_context(
            patch.object(launcher.subprocess, "Popen", side_effect=start)
        )
        launcher.open_dashboard()
        launcher.open_dashboard()
    assert calls == ["preference", "registered", "start", "open", "open"]
    assert not plist.parent.exists()
