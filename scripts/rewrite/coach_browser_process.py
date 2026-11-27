"""Run the athlete-facing coach browser journey through Vite's native API proxy."""

import os
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from test_proposal_slice import ROOT


def available_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return str(sock.getsockname()[1])


def exercise_browser(api, env):
    frontend = ROOT / "frontend"
    port = env["VITE_PORT"]
    base = f"http://127.0.0.1:{port}"
    output = os.path.join(env["PRIVATE_DIR"], "browser-output")
    env = dict(
        {
            key: env[key]
            for key in ("PATH", "HOME", "TMPDIR", "LANG", "PLAYWRIGHT_BROWSERS_PATH")
            if key in env
        },
        APP_PORT=str(urlsplit(api).port),
        PLAYWRIGHT_BASE_URL=base,
        GB_NATIVE_COACH_BROWSER="1",
        NODE_PATH=str(frontend / "node_modules"),
    )
    with subprocess.Popen(
        [
            frontend / "node_modules/.bin/vite",
            "--host",
            "127.0.0.1",
            "--port",
            port,
            "--strictPort",
        ],
        cwd=frontend,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) as vite:
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if vite.poll() is not None:
                    raise RuntimeError("Vite exited during startup")
                try:
                    with urlopen(base, timeout=1) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                raise TimeoutError("Vite did not start")
            subprocess.run(
                [
                    frontend / "node_modules/.bin/playwright",
                    "test",
                    "coach-native.spec.ts",
                    "--output",
                    output,
                ],
                cwd=frontend,
                env=env,
                check=True,
            )
        finally:
            vite.terminate()
