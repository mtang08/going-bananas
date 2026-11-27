"""Check guarded exception routes and persisted edits in two disposable migrated schemas."""

import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import psycopg
from check_assessment_db import conn, id
from check_exception_view import NOW, populate
from check_gcal_replay import test_url
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema


def requests():
    finding = lambda n: f"/api/v1/exceptions/{id(n)}/dismiss"
    patch = lambda n: f"/api/v1/exception-patches/{id(n)}/resolve"
    index = "/api/v1/exceptions"
    return [
        ("GET", index + "?include=all", None),
        (
            "POST",
            finding(340).replace(id(340), "xyz"),
            {"expected_version": 0, "note": 3, "extra": None},
        ),
        ("POST", patch(320), {"status": "other", "note": "é" * 501}),
        ("POST", finding(999), {"expected_version": "1"}),
        ("POST", patch(999), {"expected_version": True, "status": "escalated"}),
        ("POST", finding(340), {"expected_version": 2}),
        ("POST", finding(340), {"expected_version": 3, "note": "  synthetic note  "}),
        ("POST", finding(340), {"expected_version": 3}),
        ("POST", finding(340), {"expected_version": 4}),
        ("POST", finding(345), {"expected_version": 3}),
        ("POST", patch(320), {"expected_version": 1, "status": "escalated"}),
        (
            "POST",
            patch(320),
            {"expected_version": 2, "status": "escalated", "note": "escalate"},
        ),
        ("POST", patch(320), {"expected_version": 3, "status": "escalated"}),
        (
            "POST",
            patch(320),
            {"expected_version": 3, "status": "resolved", "note": "resolved"},
        ),
        ("POST", patch(320), {"expected_version": 4, "status": "resolved"}),
        (
            "POST",
            patch(321),
            {"expected_version": 2, "status": "resolved", "note": None},
        ),
        ("GET", index, None),
        ("GET", index + "?include=active&include=recent", None),
    ]


def reference(target):
    from app.api import exceptions as routes
    from app.main import app
    from fastapi.testclient import TestClient

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    routes.datetime = Clock
    cases = []
    with TestClient(app) as client:
        for method, path, body in requests():
            resp = client.request(
                method, path, json=body, headers={"X-Local-Request": "1"}
            )
            value = resp.json()
            if "error" in value:
                del value["error"]["request_id"]
            cases.append(
                {
                    "method": method,
                    "path": path,
                    "body": body,
                    "status": resp.status_code,
                    "expected": value,
                }
            )
    target.write_text(json.dumps(cases))


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
        migrated_schema(db, url, Path(tmp) / "python", "5173") as py,
        migrated_schema(db, url, Path(tmp) / "go", "5173") as go,
    ):
        for env in [py, go]:
            populate(env)
            with conn(env) as connection:
                connection.execute(
                    "UPDATE exception_findings SET evidence_at='2026-01-01', last_seen_at='2026-01-01' WHERE id=%s",
                    (id(342),),
                )
        target = Path(tmp) / "cases.json"
        subprocess.run(
            [sys.executable, __file__, "reference", target],
            env={**py, "PYTHONPATH": str(BACKEND)},
            check=True,
        )
        subprocess.run(
            [
                "go",
                "test",
                "-race",
                "-count=1",
                "-run",
                "^TestExceptionHTTPPython$",
                "./internal/httpapi",
            ],
            cwd=MODULE,
            env={
                **go,
                "EXCEPTION_HTTP_REFERENCE": str(target),
                "EXCEPTION_HTTP_NOW": NOW.isoformat(),
            },
            check=True,
        )
        assert snapshot(py) == snapshot(go)
        with conn(go) as connection:
            assert connection.execute(
                "SELECT status FROM exception_findings WHERE id=%s", (id(342),)
            ).fetchone() == ("expired",)
        print(
            "PASS exception HTTP reads, validation, versioned dismissal/escalation/resolution, linked findings and revisions"
        )


if __name__ == "__main__":
    if sys.argv[1:2] == ["reference"]:
        reference(Path(sys.argv[2]))
    else:
        main()
