"""Verify exception routes and persisted edits against captured synthetic cases."""

import json
import subprocess
import tempfile
from pathlib import Path

import psycopg
from training_fixture import conn, id
from check_exception_view import FIXTURES, NOW, populate
from check_gcal_replay import test_url
from test_proposal_slice import MODULE, ROOT, migrated_schema


def snapshot(env):
    with conn(env) as db:
        return [
            db.execute(
                "SELECT rule_code,entity_key,status,version,closed_at,close_note FROM exception_findings ORDER BY 1,2"
            ).fetchall(),
            db.execute(
                "SELECT id,status,version,resolved_at,resolved_by,resolution_note FROM exception_patches ORDER BY id"
            ).fetchall(),
            db.execute("SELECT data_revision FROM app_state WHERE id=1").fetchall(),
        ]


def main():
    url = test_url()
    with (
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
        migrated_schema(db, url, Path(tmp) / "go", "5173") as env,
    ):
        populate(env)
        with conn(env) as connection:
            connection.execute(
                "UPDATE exception_findings SET evidence_at='2026-01-01', last_seen_at='2026-01-01' WHERE id=%s",
                (id(342),),
            )
        subprocess.run(
            [
                "go",
                "test",
                "-race",
                "-count=1",
                "-run",
                "^TestExceptionHTTPReference$",
                "./internal/httpapi",
            ],
            cwd=MODULE,
            env={
                **env,
                "EXCEPTION_HTTP_REFERENCE": str(FIXTURES / "http-cases.json"),
                "EXCEPTION_HTTP_NOW": NOW.isoformat(),
            },
            check=True,
        )
        expected = json.loads((FIXTURES / "http-state.json").read_text())
        actual = json.loads(json.dumps(snapshot(env), default=str))
        assert actual == expected, (actual, expected)
        with conn(env) as connection:
            assert connection.execute(
                "SELECT status FROM exception_findings WHERE id=%s", (id(342),)
            ).fetchone() == ("expired",)
        print(
            "PASS exception HTTP reads, validation, versioned dismissal/escalation/resolution, linked findings and revisions"
        )


if __name__ == "__main__":
    main()
