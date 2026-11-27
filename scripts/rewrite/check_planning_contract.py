"""Validate actual Go and FastAPI planning responses against the public contract."""

import json
import os
import subprocess
import tempfile
from http.client import HTTPConnection
from pathlib import Path

import psycopg
from check_planning_commands import BLOCK, EVENT, MISSING, RUN, seed
from sqlalchemy.engine import make_url
from test_proposal_slice import MODULE, ROOT, migrated_schema, servers


def exercise(port):
    samples = []

    def call(method, pattern, body=None, status=200, **params):
        client = HTTPConnection("127.0.0.1", int(port), timeout=30)
        try:
            client.request(
                method,
                "/api/v1" + pattern.format(**params),
                None if body is None else json.dumps(body),
                headers={
                    "Content-Type": "application/json",
                    "X-Local-Request": "1",
                    "Origin": f"http://127.0.0.1:{port}",
                },
            )
            res = client.getresponse()
            data = json.loads(res.read())
            assert res.status == status, (method, pattern, res.status, data)
            samples.append(
                {
                    "method": method,
                    "path": pattern,
                    "body": body,
                    "status": status,
                    "response": data,
                }
            )
            return data.get("data")
        finally:
            client.close()

    profile = dict(call("GET", "/profile"))
    version = profile.pop("version")
    saved = call("PUT", "/profile", dict(profile, expected_version=version))
    call(
        "PUT",
        "/running-interruption",
        {
            "expected_version": saved["version"],
            "interruption": {
                "reason": "travel",
                "starts_on": "2026-11-16",
                "return_on": "2026-12-01",
            },
        },
    )
    call("GET", "/running-interruption")
    call(
        "POST",
        "/anchors",
        {
            "kind": "hr_aerobic_upper",
            "unit": "bpm",
            "value_low": 143,
            "protocol": "manual",
            "confidence": "moderate",
            "calibrated_at": "2026-11-15T14:00:00Z",
            "valid_from": "2026-11-16",
        },
    )
    call("GET", "/anchors")
    call("GET", "/strength-routine")
    call(
        "PUT",
        "/strength-routine",
        {
            "expected_version": 0,
            "slots": [
                {"label": "Core", "default_weekday": 1, "lower_body_cost": "low"}
            ],
        },
    )
    call("GET", "/events")
    event = call(
        "POST",
        "/events",
        {"name": "Synthetic race", "event_date": "2099-04-03", "purpose": "pr"},
        status=201,
    )
    call(
        "PATCH",
        "/events/{event_id}",
        {"expected_version": event["version"], "name": "Revised race"},
        event_id=event["id"],
    )
    call(
        "PUT", "/events/order", {"items": [{"id": event["id"], "expected_version": 2}]}
    )
    call("GET", "/blocks/active")
    call("GET", "/blocks/benchmarks")
    call("GET", "/blocks/{block_uid}/history", block_uid=BLOCK)
    call("GET", "/blocks/{block_uid}/history", block_uid=MISSING, status=404)
    call("GET", "/events/{event_id}/blocks", event_id=EVENT)
    call(
        "PUT",
        "/blocks/{block_uid}/benchmark-activity",
        {"activity_id": RUN},
        block_uid=BLOCK,
    )
    call(
        "PATCH",
        "/events/{event_id}",
        {"expected_version": 1, "name": "Stale"},
        event_id=event["id"],
        status=409,
    )
    call("PUT", "/running-interruption", {}, status=422)
    subprocess.run(
        ["node", ROOT / "scripts/rewrite/check_planning_contract.mjs"],
        input=json.dumps(samples),
        text=True,
        check=True,
    )
    return len(samples)


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
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
    ):
        scratch = Path(tmp)
        binary = scratch / "going-bananas"
        subprocess.run(
            ["go", "build", "-o", binary, "./cmd/going-bananas"], cwd=MODULE, check=True
        )
        with (
            migrated_schema(db, url, scratch / "py", "5173") as py,
            migrated_schema(db, url, scratch / "go", "5173") as go,
        ):
            for env in (py, go):
                seed(env)
            with servers(py, dict(go, GB_MODE_ROOT=str(ROOT)), binary) as ports:
                for port in ports:
                    count = exercise(port)
    print(
        f"PASS {count} real planning responses per backend against all 17 contract operations"
    )


if __name__ == "__main__":
    main()
