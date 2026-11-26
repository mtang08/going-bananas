"""Compare persisted Go draft edits to Python on isolated, independently migrated PostgreSQL schemas."""

import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[3]
NOW = "2026-11-16T15:00:00+00:00"


def execute(args, env, body=None, failure=False):
    p = subprocess.run(
        args,
        check=False,
        cwd=ROOT,
        env=env,
        input=json.dumps(body),
        text=True,
        capture_output=True,
    )
    if p.returncode and not failure:
        raise RuntimeError(p.stderr)
    return json.loads(p.stderr if p.returncode else p.stdout)


def main():
    env = os.environ.copy()
    url = make_url(env["DATABASE_URL"])
    if (
        env.get("APP_MODE") != "test"
        or url.database != "garmin_test"
        or url.host not in {"localhost", "127.0.0.1"}
    ):
        raise ValueError("requires an isolated loopback garmin_test database")
    pg = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with (
        tempfile.TemporaryDirectory(dir=ROOT / "private") as scratch,
        ExitStack() as stack,
    ):
        binary = Path(scratch) / "coaching"
        subprocess.run(
            ["go", "build", "-o", binary, "./cmd/coaching"],
            cwd=ROOT / "backend-go",
            check=True,
        )
        db = stack.enter_context(psycopg.connect(pg, autocommit=True))
        assert db.execute("SELECT current_database()").fetchone() == ("garmin_test",)
        targets = []
        for _ in range(2):
            schema = "go_drafts_" + uuid4().hex
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            stack.callback(
                db.execute,
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)),
            )
            dest = dict(
                env,
                PGOPTIONS="-csearch_path=" + schema,
                PRIVATE_DIR=scratch,
                PYTHONPATH=str(ROOT / "backend"),
            )
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=ROOT / "backend",
                env=dest,
                check=True,
            )
            conn = stack.enter_context(
                psycopg.connect(pg, options=dest["PGOPTIONS"], autocommit=True)
            )
            assert conn.execute("SELECT current_schema()").fetchone() == (schema,)
            targets.append((dest, conn))
        (ref, refdb), (go, godb) = targets

        def python(env, op, **kw):
            return execute(
                [
                    sys.executable,
                    ROOT / "scripts/rewrite/coaching/lifecycle_reference.py",
                ],
                env,
                dict(op=op, now=NOW, **kw),
            )

        def native(op, id=None, body=None, failure=False, revision=None):
            args = [binary, op, "-repo", ROOT, "-python", sys.executable, "-now", NOW]
            if id:
                args += ["-id", id]
            if revision:
                args += ["-revision", str(revision)]
            return execute(args, go, body, failure)

        def document(env):
            seed = python(env, "seed")
            return {
                "schema_version": "coach_proposal.v2",
                "operation": "proceed_or_modify_today",
                "snapshot_id": seed["snapshot_id"],
                "base_calendar_version": 0,
                "base_block_version_id": None,
                "headline": "Easy day",
                "why": [{"kind": "observation", "text": "Synthetic session"}],
                "uncertainty": ["Synthetic uncertainty"],
                "change_triggers": [{"when": "Energy drops", "then": "Rest"}],
                "next_check": {"on": seed["day"], "check": "Review response"},
                "confidence": {
                    "decision": "moderate",
                    "evidence": "moderate",
                    "data": "moderate",
                },
                "changes": [
                    {
                        "change_id": "c1",
                        "op": "add",
                        "after": {
                            "local_date": seed["day"],
                            "kind": "rest",
                            "intent": "Recovery",
                        },
                        "reason": "Recovery day",
                    }
                ],
                "evidence_ids": [],
                "policy_ids": [],
                "recipe_ids": [],
                "skill_version": "running-coach.v1",
            }

        rdoc, gdoc = document(ref), document(go)

        def assert_result(r, g, status, rev):
            assert (
                r["status"] == g["status"] == status
                and r["revision"] == g["revision"] == rev
            ), (r, g)
            assert r.get("issues", []) == g.get("issues", [])

        # An actual Python-created draft on both sides verifies cross-language revision and persisted hash replay.
        r, g = python(ref, "submit", document=rdoc), python(go, "submit", document=gdoc)
        assert_result(r, g, "pending", 1)
        rid, gid = r["proposal_id"], g["proposal_id"]
        assert native("load", gid)["changes"]["c1"]["op"] == "add"
        assert native("submit", body=gdoc)["proposal_id"] == gid

        def request(doc, rev, title):
            edited = {
                **doc,
                "headline": title,
                "changes": [{**doc["changes"][0], "reason": title}],
            }
            return {
                "expected_revision": rev,
                "reason": " Athlete requested an edit ",
                "document": edited,
            }

        rreq, greq = (
            request(rdoc, 1, "Revised draft"),
            request(gdoc, 1, "Revised draft"),
        )
        for _ in range(2):
            r, g = (
                python(ref, "revise", id=rid, request=rreq),
                native("revise", gid, greq),
            )
            assert_result(r, g, "pending", 2)
            assert (r["proposal_id"], g["proposal_id"]) == (rid, gid)
        stale = native("revise", gid, request(gdoc, 1, "Different edit"), True)
        assert stale["code"] == "proposal_revision_conflict"
        for conn, id in ((refdb, rid), (godb, gid)):
            rows = conn.execute(
                "SELECT revision,reason,changed_change_ids,changed_fields FROM coach_proposal_revisions WHERE proposal_id=%s ORDER BY revision",
                (id,),
            ).fetchall()
            assert rows == [
                (1, "Original proposal", [], []),
                (2, "Athlete requested an edit", ["c1"], ["headline"]),
            ], rows
            conn.execute(
                "INSERT INTO goals(id,text,horizon,priority,status,version) VALUES (%s,'Updated goal','season',1,'active',1)",
                (uuid4(),),
            )
        r = python(ref, "revise", id=rid, request=request(rdoc, 2, "Stale evidence"))
        g = native("revise", gid, request(gdoc, 2, "Stale evidence"), True)
        assert r["code"] == g["error"]["code"] == "stale_evidence", (r, g)
        for conn in (refdb, godb):
            conn.execute("DELETE FROM goals WHERE text='Updated goal'")
        # A final receipt write fails after replacement of the proposal and changes. Nothing may leak.
        godb.execute("ALTER TABLE coach_proposal_revisions ADD CHECK(revision<=2)")
        try:
            native("revise", gid, request(gdoc, 2, "Must roll back"))
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected injected write failure")
        saved = native("load", gid)
        assert (
            saved["revision"] == 2
            and saved["payload"]["headline"] == "Revised draft"
            and saved["changes"]["c1"]["reason"] == "Revised draft"
        )
        godb.execute(
            "ALTER TABLE coach_proposal_revisions DROP CONSTRAINT coach_proposal_revisions_revision_check"
        )
        with ThreadPoolExecutor(2) as pool:
            results = list(
                pool.map(
                    lambda title: native("revise", gid, request(gdoc, 2, title), True),
                    ["Edit A", "Edit B"],
                )
            )
        assert sorted(r.get("code", r.get("status")) for r in results) == [
            "pending",
            "proposal_revision_conflict",
        ], results
        assert native("discard", gid, revision=3)["status"] == "discarded"
        assert python(ref, "discard", id=rid, revision=2)["status"] == "discarded"
        # A distinct submission now exercises native insertion rather than original-hash replay.
        new = native("submit", body={**gdoc, "headline": "Second draft"})
        assert new["status"] == "pending" and new["proposal_id"] != gid, new
        again=native("submit", body={**gdoc,"headline":"Second draft"})
        assert again==new,(again,new)
        for conn in (refdb, godb):
            assert conn.execute(
                "SELECT calendar_head_version FROM app_state WHERE id=1"
            ).fetchone() == (0,)
    print(
        "Passed Python-created draft revision, no-duplicate retry, drift, rollback, concurrent edits, discard and native submit."
    )


if __name__ == "__main__":
    main()
