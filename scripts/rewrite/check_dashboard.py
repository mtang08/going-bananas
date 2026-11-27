"""Exercise dashboard turns against a private synthetic PostgreSQL schema and fake transport."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

from test_proposal_slice import MODULE, ROOT, migrated_schema


def main():
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if (os.environ.get("APP_MODE") != "test" or url.database != "garmin_test"
            or url.host not in {"127.0.0.1", "localhost"} or url.query
            or str(url.port) != os.environ.get("TEST_DATABASE_PORT")
            or os.environ.get("DATABASE_URL") != os.environ["TEST_DATABASE_URL"]):
        raise SystemExit("Use scripts/test-db.py dashboard with the isolated test cluster.")
    pg_url = url.set(drivername="postgresql")
    with psycopg.connect(pg_url.render_as_string(hide_password=False), autocommit=True) as db:
        with tempfile.TemporaryDirectory(dir=ROOT / "private") as scratch:
            with migrated_schema(db, url, Path(scratch) / "dashboard", "0") as env:
                with psycopg.connect(env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"]) as fixture:
                    schema, = fixture.execute("SELECT current_schema()").fetchone()
                env["DASHBOARD_TEST_DATABASE_URL"] = pg_url.update_query_dict(
                    {"search_path": schema}
                ).render_as_string(hide_password=False)
                env["DASHBOARD_REFERENCE_PYTHON"] = sys.executable
                subprocess.run(["go", "test", "-p", "1", "-race", "-count=1", "-v", "./internal/coachdashboard", "./internal/coachdashboardhttp", "./internal/coaching/snapshotreads",
                                "./internal/weeklydigest", "./internal/weeklyprojection", "./internal/httpapi",
                                "./internal/returnplan", "./internal/coaching/snapshots", "./internal/coaching/drilldowns"],
                               cwd=MODULE, env=env, check=True)


if __name__ == "__main__":
    main()
