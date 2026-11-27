"""Exercise startup, readiness, and recovery from a failed metric refresh."""

import subprocess
import tempfile
from pathlib import Path

import psycopg

from check_gcal_replay import test_url
from test_proposal_slice import MODULE, ROOT, migrated_schema


def run_database_test(package, seed=None):
    url = test_url()
    with (
        psycopg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False), autocommit=True) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as directory,
        migrated_schema(db, url, Path(directory) / "workspace", "5173") as env,
    ):
        if seed is not None:
            seed(env)
        subprocess.run(["go", "test", "-race", "-count=1", package], cwd=MODULE, env=env, check=True)


if __name__ == "__main__":
    run_database_test("./internal/health")
