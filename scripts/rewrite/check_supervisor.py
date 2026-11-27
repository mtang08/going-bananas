"""Run the normal built and Vite supervisors in an isolated PostgreSQL schema."""
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from http.client import HTTPConnection
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

from test_proposal_slice import ROOT, migrated_schema


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def exercise(env, target):
    api = free_port()
    ui = free_port()
    while ui == api:
        ui = free_port()
    env = dict(env, APP_PORT=str(api), VITE_PORT=str(ui), GB_MODE_ROOT=str(ROOT))
    with subprocess.Popen(["make", target], cwd=ROOT, env=env, start_new_session=True) as proc:
        try:
            ui_port = ui if target == "dev" else api
            for _ in range(300):
                if proc.poll() is not None:
                    raise RuntimeError(f"make {target} exited before serving")
                client = HTTPConnection("127.0.0.1", ui_port, timeout=2)
                try:
                    client.request("GET", "/api/v1/health/ready")
                    response = client.getresponse()
                    if response.status == 200 and b'"database":true' in response.read():
                        break
                except OSError:
                    pass
                finally:
                    client.close()
                time.sleep(.1)
            else:
                raise TimeoutError(f"make {target} did not become ready")
            subprocess.run(["node", ROOT/"scripts/rewrite/supervisor-smoke.mjs", str(ui_port)],
                           cwd=ROOT, env=env, check=True, timeout=60)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=20)
        # Make exits on SIGTERM first. The supervisor releases its lock after reaping children.
        for _ in range(100):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", api)) != 0:
                    break
            time.sleep(.1)
        else:
            raise RuntimeError("supervisor left the API listening")


def main():
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if (
        os.environ.get("APP_MODE") != "test"
        or url.database != "garmin_test"
        or url.host not in {"127.0.0.1", "localhost"}
        or url.query
        or os.environ["DATABASE_URL"] != os.environ["TEST_DATABASE_URL"]
        or str(url.port) != os.environ["TEST_DATABASE_PORT"]
    ):
        raise SystemExit("requires isolated test runner")
    with (
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as temp,
    ):
        directory = Path(temp)
        with migrated_schema(db, url, directory / "supervisor", "5173") as env:
            env["GB_MODE_ROOT"] = str(ROOT)
            subprocess.run(["make", "build"], cwd=ROOT, env=env, check=True)
            for target in ("start", "dev"):
                exercise(env, target)
    print("PASS make build/start/dev, loopback health, Chrome goal creation and persistence")


if __name__ == "__main__":
    main()
