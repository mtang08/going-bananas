"""Regenerate the launchd reference on any OS with the backend test environment."""

import json
import plistlib
import runpy
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from pytest import MonkeyPatch

BACKEND = Path(__file__).resolve().parents[4] / "backend"
sys.path.insert(0, str(BACKEND))
launchd = runpy.run_path(str(BACKEND / "tests/unit/test_login_startup.py"))["launchd"]


def http_reference():
    from app.api import login_startup
    from app.main import app
    from fastapi.testclient import TestClient

    output = []
    with MonkeyPatch.context() as patch:
        patch.setattr(
            login_startup,
            "run_login_startup",
            lambda enabled: login_startup.LoginStartup(
                status="enabled" if enabled else "disabled",
                enabled=bool(enabled),
                message=None,
            ),
        )
        for method, body, guard in [
            ("GET", "", ""),
            ("PUT", '{"enabled":true}', ""),
            ("PUT", '{"enabled":false}', ""),
            ("PUT", "{}", ""),
            ("PUT", '{"enabled":"true","path":1}', ""),
            ("PUT", '{"enabled":null}', ""),
            ("PUT", "[]", ""),
            ("PUT", "null", ""),
            ("PUT", "{", ""),
            ("PUT", "", ""),
            ("PUT", "{}", "csrf"),
            ("PUT", "{}", "type"),
            ("GET", "", "remote"),
            ("GET", "", "cross"),
            ("GET", "", "origin"),
            ("PUT", '{"enabled":true}', "unavailable"),
            ("PUT", '{"enabled":true}', "other_checkout"),
        ]:
            if guard in {"unavailable", "other_checkout"}:
                patch.setattr(
                    login_startup,
                    "run_login_startup",
                    lambda value, status=guard: login_startup.LoginStartup(
                        status=status, message="Fixture error", enabled=None
                    ),
                )
            peer = "192.0.2.1" if guard == "remote" else "127.0.0.1"
            headers = {
                "Content-Type": "text/plain" if guard == "type" else "application/json"
            }
            if guard != "csrf":
                headers["X-Local-Request"] = "1"
            if guard == "cross":
                headers["Sec-Fetch-Site"] = "cross-site"
            if guard == "origin":
                headers["Origin"] = "https://example.invalid"
            with TestClient(app, client=(peer, 12345)) as client:
                resp = client.request(
                    method,
                    "/api/v1/settings/login-startup",
                    content=body,
                    headers=headers,
                )
            wire = resp.json()
            if "error" in wire:
                del wire["error"]["request_id"]
            output.append(
                {
                    "method": method,
                    "body": body,
                    "guard": guard,
                    "headers": headers,
                    "peer": peer,
                    "status": resp.status_code,
                    "wire": wire,
                }
            )
    Path(__file__).with_name("http.json").write_text(
        json.dumps(output, indent=2) + "\n"
    )


def main():
    path = Path(__file__).with_name("reference.json")
    with TemporaryDirectory() as tmp, MonkeyPatch.context() as patch:
        launcher, agent, state = launchd.__wrapped__(Path(tmp), patch)
        patch.setattr(launcher, "PATH", "/usr/bin:/bin")
        patch.setattr(launcher, "domain", lambda: "gui/4321")
        output = []
        for action, change in [
            (None, ""),
            (True, ""),
            (True, "registered"),
            (False, ""),
            (False, ""),
            (None, ""),
            (True, ""),
            (True, "ignore-enable"),
            (None, ""),
            (True, "repair"),
            (None, "binary"),
            (None, "foreign"),
            (False, ""),
            (True, "malformed"),
            (None, "missing"),
            (True, "offline"),
            (True, "symlink"),
        ]:
            if change == "registered":
                state.registered = True
            if change == "ignore-enable":
                state.disabled = state.ignore_write = True
            if change == "repair":
                state.ignore_write = False
                job = plistlib.loads(agent.read_bytes())
                job["Disabled"] = True
                agent.write_bytes(plistlib.dumps(job))
            if change in {"binary", "foreign"}:
                job = plistlib.loads(agent.read_bytes())
                if change == "foreign":
                    job["WorkingDirectory"] = str(Path(tmp) / "elsewhere")
                agent.write_bytes(plistlib.dumps(job, fmt=plistlib.FMT_BINARY))
            if change == "malformed":
                agent.write_bytes(b"not a plist")
            if change == "missing":
                agent.unlink()
            if change == "offline":
                state.offline = True
            if change == "symlink":
                agent.symlink_to(Path(tmp) / "absent")
            before = agent.read_bytes() if agent.is_file() else None
            state.calls.clear()
            result = (
                launcher.login_startup_status()
                if action is None
                else launcher.set_login_startup(action)
            )
            after = agent.read_bytes() if agent.is_file() else None
            output.append(
                {
                    "action": action,
                    "change": change,
                    "result": result,
                    "calls": list(state.calls),
                    "rewritten": after != before,
                }
            )
        path.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
    http_reference()
