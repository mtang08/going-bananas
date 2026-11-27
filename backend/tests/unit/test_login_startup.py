"""Exercise the Finder login launcher against a simulated launchd."""

from __future__ import annotations

import importlib.util
import plistlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def launchd(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("dashboard_login", ROOT / "scripts" / "dashboard-login.py")
    assert spec is not None and spec.loader is not None
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    root = tmp_path / "checkout"
    private = root / "private"
    dist = root / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").touch()
    (root / ".env").touch()
    agent = tmp_path / "home" / "Library" / "LaunchAgents" / f"{launcher.LABEL}.plist"
    state = SimpleNamespace(disabled=False, registered=False, offline=False, ignore_write=False, calls=[])

    def fake_run(args, **kwargs):
        assert args[0] == "/bin/launchctl"
        method, target = args[1:]
        state.calls.append(method)
        domain = launcher.domain()
        if method == "print-disabled":
            assert target == domain
            output = f'disabled services = {{\n  "{launcher.LABEL}" => {str(state.disabled).lower()}\n}}'
            return subprocess.CompletedProcess(args, int(state.offline), stdout=output)
        assert target == f"{domain}/{launcher.LABEL}"
        if method == "print":
            return subprocess.CompletedProcess(args, int(not state.registered))
        if method in {"enable", "disable"}:
            if not state.ignore_write:
                state.disabled = method == "disable"
            return subprocess.CompletedProcess(args, 0)
        pytest.fail(f"An unexpected launchctl command would have run: {method}")

    monkeypatch.setattr(launcher, "sys", SimpleNamespace(platform="darwin", executable=sys.executable))
    monkeypatch.setattr(launcher, "ROOT", root)
    monkeypatch.setattr(launcher, "SCRIPT", root / "scripts" / "dashboard-login.py")
    monkeypatch.setattr(launcher, "PRIVATE", private)
    monkeypatch.setattr(launcher, "LOG", private / "dashboard-launch.log")
    monkeypatch.setattr(launcher, "agent_path", lambda: agent)
    monkeypatch.setattr(launcher, "supports_login_startup", lambda: True)
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    return launcher, agent, state


def test_enable_and_disable_next_login_without_stopping_current_service(launchd):
    launcher, agent, state = launchd
    assert launcher.login_startup_status()["status"] == "disabled"
    assert not agent.parent.exists()
    first = launcher.set_login_startup(True)
    assert first == {"status": "enabled", "enabled": True, "message": None}
    installed = agent.read_bytes()
    props = plistlib.loads(installed)
    assert props["RunAtLoad"] is True
    assert props["WorkingDirectory"] == str(launcher.ROOT)
    assert props["ProgramArguments"][-2:] == [str(launcher.SCRIPT), "serve"]
    assert agent.stat().st_mode & 0o777 == 0o600

    state.registered = True
    assert launcher.set_login_startup(True) == first
    assert launcher.set_login_startup(False)["status"] == "disabled"
    assert launcher.set_login_startup(False)["enabled"] is False
    assert state.registered
    assert agent.read_bytes() == installed
    assert launcher.login_startup_status()["enabled"] is False
    assert launcher.set_login_startup(True)["enabled"] is True
    assert [call for call in state.calls if call not in {"print-disabled", "print"}] == ["disable", "enable"]


def test_external_disable_is_reported_and_unconfirmed_change_fails(launchd):
    launcher, agent, state = launchd
    launcher.set_login_startup(True)
    saved = agent.read_bytes()
    state.disabled = True
    assert launcher.login_startup_status()["enabled"] is False
    assert agent.read_bytes() == saved
    state.ignore_write = True
    assert launcher.set_login_startup(True)["status"] == "unavailable"
    assert launcher.login_startup_status()["enabled"] is False


def test_missing_gui_session_is_unavailable_without_creating_launch_file(launchd):
    launcher, agent, state = launchd
    state.offline = True
    assert launcher.login_startup_status()["status"] == "unavailable"
    assert launcher.set_login_startup(True)["status"] == "unavailable"
    assert not agent.parent.exists()
    assert state.calls == ["print-disabled", "print-disabled"]


def test_explicit_enable_repairs_owned_nonstarting_plist(launchd):
    launcher, agent, _ = launchd
    assert launcher.set_login_startup(True)["enabled"] is True
    changed = {**plistlib.loads(agent.read_bytes()), "Disabled": True}
    agent.write_bytes(plistlib.dumps(changed))
    assert launcher.login_startup_status()["enabled"] is False
    assert plistlib.loads(agent.read_bytes()) == changed
    assert launcher.set_login_startup(True)["enabled"] is True
    assert "Disabled" not in plistlib.loads(agent.read_bytes())


@pytest.mark.parametrize("drift", ["missing", "malformed", "malformed_xml", "other_checkout"])
def test_drift_is_reported_without_replacing_or_stopping_existing_job(launchd, drift):
    launcher, agent, state = launchd
    assert launcher.set_login_startup(True)["enabled"] is True
    state.registered = True
    if drift == "missing":
        agent.unlink()
    elif drift == "malformed":
        agent.write_text("not a plist")
    elif drift == "malformed_xml":
        agent.write_text('<?xml version="1.0"?><plist><dict></plist>')
    else:
        props = plistlib.loads(agent.read_bytes())
        props["WorkingDirectory"] = str(launcher.ROOT.parent / "other-checkout")
        agent.write_bytes(plistlib.dumps(props))
    state.calls.clear()
    before = agent.read_bytes() if agent.exists() else None
    status = "other_checkout" if drift == "other_checkout" else "unavailable"
    assert launcher.login_startup_status()["status"] == status
    assert launcher.set_login_startup(False)["status"] == status
    assert launcher.set_login_startup(True)["status"] == status
    assert state.registered and set(state.calls) <= {"print-disabled", "print"}
    assert (agent.read_bytes() if agent.exists() else None) == before
