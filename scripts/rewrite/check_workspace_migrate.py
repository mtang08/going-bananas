"""Compare native baseline and historical upgrades with Alembic in disposable test schemas."""

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
from check_gcal_replay import test_url
from psycopg import sql
from test_proposal_slice import BACKEND, MODULE, ROOT

OLD = "0019_lap_intensity_end"
PG_DUMP = shutil.which("pg_dump") or "/opt/homebrew/opt/postgresql@17/bin/pg_dump"


@contextmanager
def schema(db, url, directory):
    name = "go_parity_" + uuid4().hex
    private = directory / name
    private.mkdir()
    env = dict(
        os.environ,
        APP_MODE="test",
        PRIVATE_DIR=str(private),
        DATABASE_URL=url.render_as_string(hide_password=False),
        PGOPTIONS="-csearch_path=" + name,
        PGDATABASE=url.database,
        PGUSER=url.username,
        PGPASSWORD=url.password or "",
        PGHOST=url.host,
        PGPORT=str(url.port),
        PYTHON=sys.executable,
    )
    ident = sql.Identifier(name)
    db.execute(sql.SQL("CREATE SCHEMA {}").format(ident))
    try:
        yield name, env
    finally:
        db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(ident))


def alembic(env, target):
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=BACKEND,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def pg_conn(env):
    url = test_url().set(drivername="postgresql").render_as_string(hide_password=False)
    return psycopg.connect(url, options=env["PGOPTIONS"], autocommit=True)


def snapshot(name, env):
    text = subprocess.check_output(
        [PG_DUMP, "--schema-only", "--no-owner", "--no-privileges", "--schema", name],
        env=env,
        text=True,
    )
    ddl = "\n".join(
        line.replace(name, "fixture_schema")
        for line in text.splitlines()
        if not line.startswith(("\\restrict ", "\\unrestrict "))
    )

    # A dump/restore can distribute an array cast over literal varchar elements.
    # Compare the same expression tree spelling; preserve each element and its order.
    def array_cast(match):
        values = match[1].split(", ")
        return "ARRAY[" + ", ".join(f"({v})::text" for v in values) + "]"

    ddl = re.sub(
        r"\(ARRAY\[((?:'[A-Za-z_0-9]+'::character varying)(?:, '[A-Za-z_0-9]+'::character varying)*)\]\)::text\[\]",
        array_cast,
        ddl,
    )
    data = {}
    sequences = {}
    with pg_conn(env) as db:
        for (
            table,
            kind,
        ) in db.execute("""SELECT relname,relkind FROM pg_class WHERE relnamespace=current_schema()::regnamespace
            AND relkind IN ('r','S') ORDER BY relname""").fetchall():
            ident = sql.Identifier(table)
            if kind == "S":
                sequences[table] = db.execute(
                    sql.SQL("SELECT last_value,is_called FROM {}").format(ident)
                ).fetchone()
            else:
                data[table] = db.execute(
                    sql.SQL("SELECT to_jsonb(t) FROM {} t ORDER BY to_jsonb(t)").format(
                        ident
                    )
                ).fetchall()
    return ddl, data, sequences


def same(a, b):
    left, data, seq = a
    right, other, otherseq = b
    if left != right:
        raise AssertionError(
            "\n".join(difflib.unified_diff(left.splitlines(), right.splitlines(), n=2))
        )
    assert seq == otherseq, (seq, otherseq)
    assert data.keys() == other.keys()
    for table, rows in data.items():
        assert rows == other[table], (table, rows, other[table])


def migrate(binary, env, *, success=True):
    proc = subprocess.run(
        [binary, "--backend-dir", BACKEND],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=90,
        check=False,
    )
    if not success:
        assert proc.returncode != 0, "migration unexpectedly succeeded"
        return None
    if proc.returncode:
        raise AssertionError("native migration failed: " + proc.stderr[-2000:])
    return json.loads(proc.stdout.splitlines()[-1])


def historical_setup(env):
    alembic(env, OLD)
    with pg_conn(env) as db:
        db.execute("UPDATE app_state SET data_revision=397 WHERE id=1")
        db.execute("""INSERT INTO events(id,name,event_date,priority,status) VALUES
            ('bc70b034-b193-4908-9a2a-9f9cf4a4929a','Synthetic historical event','2025-01-01','target','planned')""")
        db.execute("""INSERT INTO manual_sessions(id,version,date,kind,duration_s,note,recorded_at)
            VALUES('4ca13a61-1f33-4b80-a010-b820152f6b9a',2,'2025-01-01','run',300,'Synthetic historical session','2025-01-01T16:00:00Z')""")


def exercise(db, url, directory):
    binary = directory / "workspace-migrate"
    subprocess.run(
        ["go", "build", "-o", binary, "./cmd/workspace-migrate"], cwd=MODULE, check=True
    )
    with ExitStack() as stack:

        def create():
            return stack.enter_context(schema(db, url, directory))

        refname, ref = create()
        alembic(ref, "head")
        reference = snapshot(refname, ref)
        head = reference[1]["alembic_version"][0][0]["version_num"]
        freshname, fresh = create()
        no_python = {**fresh, "PYTHON": str(directory / "nonexistent-python")}
        with ThreadPoolExecutor(max_workers=4) as workers:
            receipts = list(workers.map(lambda _: migrate(binary, no_python), range(4)))
        assert sorted(r["action"] for r in receipts) == [
            "baseline",
            "current",
            "current",
            "current",
        ], receipts
        assert all(r["head"] == head for r in receipts)
        same(reference, snapshot(freshname, fresh))
        assert migrate(binary, no_python) == {"action": "current", "head": head}
        same(reference, snapshot(freshname, fresh))

        oldrefname, oldref = create()
        oldname, old = create()
        for env in (oldref, old):
            historical_setup(env)
        same(snapshot(oldrefname, oldref), snapshot(oldname, old))
        alembic(oldref, "head")
        assert migrate(binary, old) == {"action": "historical", "head": head}
        expected = snapshot(oldrefname, oldref)
        same(expected, snapshot(oldname, old))
        assert (
            expected[1]["events"] == []
            and expected[1]["manual_sessions"][0][0]["version"] == 2
        )
        assert expected[1]["app_state"][0][0]["data_revision"] == 397
        assert (
            migrate(binary, {**old, "PYTHON": no_python["PYTHON"]})["action"]
            == "current"
        )
        same(expected, snapshot(oldname, old))

        badname, bad = create()
        with pg_conn(bad) as c:
            c.execute("CREATE TABLE sentinel (value text)")
            c.execute("INSERT INTO sentinel VALUES ('synthetic data')")
        for kind in ("unstamped", "empty_stamp", "unknown_stamp"):
            with pg_conn(bad) as c:
                if kind == "empty_stamp":
                    c.execute(
                        "CREATE TABLE alembic_version(version_num varchar(32) PRIMARY KEY)"
                    )
                if kind == "unknown_stamp":
                    c.execute(
                        "INSERT INTO alembic_version VALUES ('future_unrecognized')"
                    )
            before = snapshot(badname, bad)
            migrate(binary, bad, success=False)
            same(before, snapshot(badname, bad))

        failname, failenv = create()
        historical_setup(failenv)
        with pg_conn(failenv) as c:
            c.execute("""INSERT INTO daily_guidance(id,local_date,engine,decision,rationale,input_hash)
                VALUES ('0a865d02-b786-408b-ac1f-17d0b13be842','2025-01-01','fixture','rest','synthetic blocker','fixture')""")
        before = snapshot(failname, failenv)
        migrate(binary, failenv, success=False)
        same(before, snapshot(failname, failenv))
        print(
            f"PASS baseline and historical upgrades matched Alembic at {head} across {len(reference[1])} tables and {len(reference[2])} sequences; four simultaneous starts, replay, refusal, rollback"
        )


def main():
    url = test_url()
    with (
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as db,
    ):
        exercise(db, url, Path(tmp))


if __name__ == "__main__":
    main()
