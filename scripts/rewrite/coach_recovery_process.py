"""Rehearse a native backup and restart of the completed synthetic coaching journey."""

import hashlib
import json
import os
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url
from test_proposal_slice import MODULE


def connect(url, **kwargs):
    # The HTTP pool accepts startup parameters in the query. libpq takes those
    # settings through options instead.
    dsn = url.set(drivername="postgresql", query={})
    return psycopg.connect(dsn.render_as_string(hide_password=False), **kwargs)


@contextmanager
def recovery_source(url):
    if (
        os.getenv("APP_MODE") != "test"
        or url.database != "garmin_test"
        or url.host not in {"localhost", "127.0.0.1"}
    ):
        raise ValueError("recovery requires an isolated loopback test cluster")
    name = "coach_recovery_" + uuid4().hex + "_test"
    with connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            yield url.set(database=name)
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def request(base, route, body=None):
    req = Request(
        base + "/api/v1" + route,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Local-Request": "1"},
    )
    with build_opener(ProxyHandler({})).open(req, timeout=15) as response:
        return json.load(response)["data"]


def capture(base, uid, agreement):
    review = request(base, "/coach/chat")
    assert UUID(review["id"]) == UUID(agreement["thread_id"])
    assert UUID(review["proposal_id"]) != UUID(uid)
    paths = [
        "/calendar/versions",
        f"/coach/proposals/{uid}/revisions/1",
        f"/coach/proposals/{uid}/revisions/2",
        f"/coach/proposals/{uid}/document",
        f"/coach/proposals/{review['proposal_id']}/document",
    ]
    views = {path: request(base, path) for path in paths}
    assert views[paths[3]]["status"] == "accepted"
    assert views[paths[4]]["status"] == "pending"
    return {"agreement": agreement, "review": review, "views": views}


def calendar_rows(url):
    schema = url.query["search_path"]
    assert re.fullmatch(r"go_parity_[0-9a-f]{32}", schema)
    with connect(
        url, options=f"-csearch_path={schema} -cdefault_transaction_read_only=on"
    ) as db:
        versions = db.execute(
            "SELECT id,number FROM calendar_versions ORDER BY number"
        ).fetchall()
        sessions = db.execute(
            "SELECT id,session_uid,revision,calendar_version_number FROM calendar_session_revisions "
            "ORDER BY session_uid,revision"
        ).fetchall()
    assert len(versions) >= 3 and len(sessions) >= 7
    return versions, sessions


def recover(scratch, root, binary, env, proof, native_server):
    source = make_url(env["DATABASE_URL"])
    assert source.host in {"127.0.0.1", "localhost"}
    assert re.fullmatch(r"coach_recovery_[0-9a-f]{32}_test", source.database)
    rows = calendar_rows(source)
    backup = scratch / "workspace-backup"
    subprocess.run(
        ["go", "build", "-o", backup, "./cmd/workspace-backup"], cwd=MODULE, check=True
    )
    raw = Path(env["PRIVATE_DIR"]) / "raw" / "synthetic-recovery.bin"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(b"Generated coaching recovery fixture\x00" + uuid4().bytes)
    checksum = hashlib.sha256(raw.read_bytes()).digest()
    archive = scratch / "coach.tar.gz"
    private = scratch / "recovered-private"
    target = "coach_restored_" + uuid4().hex + "_test"
    # Restore creates a database and imports the dump. Its provisioning connection
    # is writable; the restarted HTTP process keeps the original pool defaults.
    provision = {**env, "PGOPTIONS": ""}
    subprocess.run([backup, "backup", archive], env=provision, check=True)
    subprocess.run(
        [
            backup,
            "restore",
            archive,
            "--target-database-name",
            target,
            "--target-private-dir",
            private,
        ],
        env=provision,
        check=True,
    )
    try:
        assert (
            hashlib.sha256((private / "raw" / raw.name).read_bytes()).digest()
            == checksum
        )
        restored = source.set(database=target)
        assert calendar_rows(restored) == rows
        restarted = {
            **env,
            "PRIVATE_DIR": str(private),
            "PGDATABASE": target,
            "DATABASE_URL": restored.render_as_string(hide_password=False),
        }
        with native_server(binary, root, restarted) as base:
            assert request(base, "/coach/chat") == proof["review"]
            assert (
                request(base, "/coach/chat/messages", proof["agreement"])
                == proof["review"]
            )
            for route, previous in proof["views"].items():
                assert request(base, route) == previous, route
        assert calendar_rows(restored) == rows
    finally:
        with connect(source, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(target)))
    print(
        "Native restore preserved raw checksum, review receipt, proposal revisions and calendar history."
    )
