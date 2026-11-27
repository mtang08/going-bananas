"""Verify native startup against the Python metric pass in fresh migrated schemas."""
import os
import sys
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

from check_assessment_db import conn
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema


def oracle():
    from app.db import SessionLocal
    from app.services.derived import refresh_today

    with SessionLocal.begin() as session:
        session.info["metrics_now"] = datetime(2026, 11, 23, 2, tzinfo=timezone.utc)
        result = refresh_today(session)
        assert result["as_of"] == "2026-11-22"
        print(result["new_results"])


def rows(env):
    with conn(env) as db:
        return db.execute("""SELECT metric_id, subject_key, status, value, config_hash
                             FROM metric_results ORDER BY metric_id,subject_key""").fetchall()


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
        with (
            migrated_schema(db, url, directory / "ref", "5173") as py,
            migrated_schema(db, url, directory / "go", "5173") as go,
        ):
            expected = subprocess.check_output(
                [sys.executable, __file__, "oracle"], env=dict(py, PYTHONPATH=str(BACKEND)),
                cwd=BACKEND, text=True,
            ).strip().splitlines()[-1]
            subprocess.run(
                ["go", "test", "-race", "-count=1", "./internal/health"],
                cwd=MODULE, env=dict(go, HEALTH_EXPECT_NEW=expected), check=True,
            )
            assert rows(py) == rows(go)
            print("PASS health probes, startup metric values and identities, retry and rollback")


if __name__ == "__main__":
    if sys.argv[1:] == ["oracle"]:
        oracle()
    else:
        main()
