"""Exercise native versioned goal edits on a disposable synthetic schema."""

import json
import re
from contextlib import ExitStack, closing
from http.client import HTTPConnection

import psycopg
from sqlalchemy.engine import make_url

GOAL = "00000000-0000-0000-0000-000000000041"
MISSING = "00000000-0000-0000-0000-000000000042"
METRIC = "00000000-0000-0000-0000-000000000043"


def connect_fixture(stack, env):
    url = make_url(env["DATABASE_URL"])
    if (
        env["APP_MODE"] != "test"
        or url.database != "garmin_test"
        or url.host not in {"localhost", "127.0.0.1"}
    ):
        raise ValueError("goal command check requires a local garmin_test database")
    conn = stack.enter_context(
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            options=env["PGOPTIONS"],
            autocommit=True,
        )
    )
    name, schema = conn.execute(
        "SELECT current_database(), current_schema()"
    ).fetchone()
    if name != "garmin_test" or not re.fullmatch(r"go_[a-z_]+[0-9a-f]{32}", schema):
        raise ValueError("goal command check requires an isolated synthetic schema")
    # A fallback table in public must never be used if a migration is missing.
    if not conn.execute("""
        SELECT bool_and(c.relnamespace = current_schema()::regnamespace)
        FROM pg_class c WHERE c.oid IN ('goals'::regclass, 'app_state'::regclass, 'metric_results'::regclass)
    """).fetchone()[0]:
        raise ValueError("expected migrated tables in the isolated schema")
    return conn, schema


def seed(conn):
    with conn.transaction():
        counts = conn.execute("""
            SELECT (SELECT count(*) FROM goals), (SELECT count(*) FROM metric_results),
                   data_revision, calendar_head_version FROM app_state WHERE id = 1
        """).fetchone()
        if counts != (0, 0, 0, 0):
            raise ValueError("goal command check requires fresh migrated schemas")
        conn.execute(
            "INSERT INTO goals (id, text, horizon, priority, status, version) VALUES (%s, 'Initial', 'season', 1, 'active', 1)",
            (GOAL,),
        )
        conn.execute(
            """
            INSERT INTO metric_results(id, metric_id, method_version, subject_type, subject_key, status, value,
                source_refs, config_hash, calculated_at, dependency_hash, timezone)
            VALUES (%s, 'fixture_metric', 'v1', 'report', 'fixture', 'available', '{"minutes":27}',
                '[]', 'fixture', '2026-01-01T00:00:00Z', 'fixture', 'UTC')
        """,
            (METRIC,),
        )


def state(conn):
    row = conn.execute("SELECT to_jsonb(g) FROM goals g").fetchall()
    if len(row) != 1:
        raise AssertionError(f"expected one persisted goal, got {len(row)}")
    revision, head = conn.execute(
        "SELECT data_revision, calendar_head_version FROM app_state WHERE id = 1"
    ).fetchone()
    metrics = conn.execute(
        "SELECT to_jsonb(m) FROM metric_results m ORDER BY id"
    ).fetchall()
    return row[0][0], revision, head, metrics


def send_goal(port, vite_port, body, goal, headers):
    fields = {
        "X-Local-Request": "1",
        "Content-Type": "application/json",
        "Origin": f"http://127.0.0.1:{vite_port}",
    }
    fields.update(headers)
    with closing(HTTPConnection("127.0.0.1", int(port), timeout=10)) as client:
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        client.request(
            "PATCH" if goal is not None else "POST",
            f"/api/v1/goals/{goal}" if goal is not None else "/api/v1/goals",
            payload,
            {k: v for k, v in fields.items() if v is not None},
        )
        with client.getresponse() as response:
            raw = response.read()
            if response.getheader("Content-Type") != "application/json" or int(
                response.getheader("Content-Length")
            ) != len(raw):
                raise AssertionError("incorrect JSON response headers")
            document = json.loads(raw)
            header_id = response.getheader("X-Request-ID")
            cache = response.getheader("Cache-Control")
            if header_id is not None and not re.fullmatch(r"[0-9a-f]{16}", header_id):
                raise AssertionError("invalid request ID header")
            if "error" in document:
                error_id = document["error"]["request_id"]
                if not re.fullmatch(r"[0-9a-f]{16}", error_id) or (
                    header_id is not None and error_id != header_id
                ):
                    raise AssertionError("error body and request ID header disagree")
                document["error"]["request_id"] = "<request-id>"
            return response.status, document, header_id is not None, cache


def check_goals(port, env):
    with ExitStack() as stack:
        conn, _ = connect_fixture(stack, env)
        seed(conn)
        expected_goal, revision, head, metrics = state(conn)

        def check_edit(
            label, body, status, code=None, *, goal=GOAL, headers=None, changes=None
        ):
            nonlocal revision
            actual, document, has_header, cache = send_goal(port, env["VITE_PORT"], body, goal, headers or {})
            assert actual == status, (label, actual, status, document)
            if status in (403, 415, 500):
                if has_header or cache:
                    raise AssertionError(
                        f"{label}: unexpected application headers on early error"
                    )
            elif not has_header or cache != "no-store":
                raise AssertionError(f"{label}: missing cache policy or request ID")
            if code:
                if document["error"]["code"] != code:
                    raise AssertionError(f"{label}: unexpected error {document!r}")
            else:
                revision += 1
                expected_goal.update(changes or {})
                expected_goal["version"] += 1
                expected = {
                    "schema_version": "v1",
                    "mode": "test",
                    "data_revision": revision,
                    "data": expected_goal,
                }
                if document != expected:
                    raise AssertionError(f"{label}: unexpected success {document!r}")
            if state(conn) != (expected_goal, revision, head, metrics):
                raise AssertionError(
                    f"{label}: persisted goal, revisions, or unrelated metric changed unexpectedly"
                )
            print(f"PASS {status} PATCH goal: {label}", flush=True)

        check_edit(
            "missing local header",
            {},
            403,
            "csrf_header_required",
            headers={"X-Local-Request": None},
        )
        check_edit(
            "foreign origin",
            {},
            403,
            "invalid_origin",
            headers={"Origin": "http://foreign.example"},
        )
        check_edit(
            "non-JSON media type",
            {},
            415,
            "json_required",
            headers={"Content-Type": "text/plain"},
        )
        check_edit("invalid JSON", b'{"text":}', 422, "validation_error")
        check_edit(
            "missing version and extra fields",
            {"text": "  ", "priority": 0, "status": "bad", "extra": True},
            422,
            "validation_error",
        )
        check_edit(
            "null field on missing goal",
            {"expected_version": 1, "status": None},
            404,
            "goal_not_found",
            goal=MISSING,
        )
        check_edit(
            "null field on outdated version",
            {"expected_version": 99, "status": None},
            409,
            "version_conflict",
        )
        check_edit(
            "explicit null",
            {"expected_version": 1, "priority": None},
            422,
            "invalid_goal",
        )
        check_edit(
            "edit all fields",
            {
                "expected_version": "1",
                "text": "  Winter goal  ",
                "horizon": "long_term",
                "status": "paused",
                "priority": 2.0,
            },
            200,
            changes={
                "text": "Winter goal",
                "horizon": "long_term",
                "status": "paused",
                "priority": 2,
            },
        )
        check_edit(
            "retry stale edit",
            {"expected_version": 1, "text": "retry"},
            409,
            "version_conflict",
        )
        check_edit("unchanged value", {"expected_version": 2, "text": "Winter goal"}, 200)
        check_edit("version only", {"expected_version": 3}, 200)
        check_edit(
            "edit status only",
            {"expected_version": 4, "status": "done"},
            200,
            changes={"status": "done"},
        )
        # Force the later revision UPDATE to fail after the goal UPDATE.
        conn.execute("ALTER TABLE app_state ADD CONSTRAINT fixture_revision_limit CHECK (data_revision <= 4)")
        check_edit(
            "rollback on revision failure",
            {"expected_version": 5, "text": "rollback"},
            500,
            "internal_error",
        )
        sample = {"text": "  Autumn goal  ", "horizon": "season", "priority": "3.0"}
        for label, body, status in [
            ("revision failure", sample, 500),
            ("missing fields", {}, 422),
            ("required nulls", dict.fromkeys(sample), 422),
            ("invalid and extra", {**sample, "priority": -1, "horizon": "bad", "status": "paused"}, 422),
            ("invalid JSON", b'{"text":}', 422),
            ("smallint overflow", {**sample, "priority": 40000}, 500),
            ("normalized input", sample, 201),
        ]:
            if label == "missing fields":
                conn.execute("ALTER TABLE app_state DROP CONSTRAINT fixture_revision_limit")
            result = send_goal(port, env["VITE_PORT"], body, None, {})
            assert result[0] == status, (label, result[0])
            row_count = conn.execute("SELECT count(*) FROM goals").fetchone()[0]
            data_revision = conn.execute("SELECT data_revision FROM app_state WHERE id=1").fetchone()[0]
            assert (row_count, data_revision) == (1 + (status == 201), revision + (status == 201))
            if status == 201:
                item = result[1]["data"]
                saved = conn.execute(
                    "SELECT text, horizon, priority, status, version FROM goals WHERE id=%s", (item["id"],)
                ).fetchone()
                assert saved == ("Autumn goal", "season", 3, "active", 1)
            print(f"PASS {status} POST goal: {label}", flush=True)
