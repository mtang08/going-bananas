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

        def python(env, op, *, at=NOW, **kw):
            return execute(
                [
                    sys.executable,
                    ROOT / "scripts/rewrite/coaching/lifecycle_reference.py",
                ],
                env,
                dict(op=op, now=at, **kw),
            )

        def native(op, id=None, body=None, failure=False, revision=None):
            args = [binary, op, "-repo", ROOT, "-now", NOW]
            if id:
                args += ["-id", id]
            if revision:
                args += ["-revision", str(revision)]
            return execute(args, go, body, failure)

        def document(env, operation="proceed_or_modify_today", at=NOW):
            seed = python(env, "seed", operation=operation, at=at)
            return {
                "schema_version": "coach_proposal.v2",
                "operation": operation,
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
        snap = native("snapshot", gdoc["snapshot_id"])
        assert (
            snap["current"]
            and snap["snapshot"]["source_fingerprint"]
            == snap["persisted_fingerprint"]
            == snap["current_fingerprint"]
        )

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
        selection = dict(
            expected_revision=1,
            expected_head=0,
            idempotency_key="synthetic-selection",
            accept_change_ids=["c1"],
            reject_change_ids=[],
        )
        prepared = native("prepare", gid, selection)
        sys.path.insert(0, str(ROOT / "backend"))
        from app.services.decision_inputs import digest

        assert prepared["decision_hash"] == digest(
            dict(
                proposal_id=gid,
                revision=1,
                accept_change_ids=["c1"],
                reject_change_ids=[],
                accept_anchor_changes=[],
                accept_block_change=False,
            )
        )
        assert prepared["changes"]["c1"]["after"]["kind"] == "rest"
        assert (
            native("prepare", gid, {**selection, "accept_change_ids": []}, True)["code"]
            == "decision_incomplete"
        )
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
        assert not native("snapshot", gdoc["snapshot_id"])["current"]
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
        again = native("submit", body={**gdoc, "headline": "Second draft"})
        assert again == new, (again, new)
        rnew = python(ref, "submit", document={**rdoc, "headline": "Second draft"})
        for key in ("reject-1", "reject-1", "reject-2"):
            rejection = python(
                ref,
                "decide",
                id=rnew["proposal_id"],
                request=dict(
                    idempotency_key=key,
                    expected_head=0,
                    expected_revision=1,
                    accept_change_ids=[],
                    reject_change_ids=["c1"],
                ),
            )
            assert rejection["status"] == "rejected"
        subprocess.run(
            [
                "go",
                "test",
                "-count=1",
                "-run",
                "^TestRejectDecisionLedger$",
                "./internal/coaching/drafts",
            ],
            cwd=ROOT / "backend-go",
            check=True,
            env={
                **go,
                "COACHING_DECISION_TEST_URL": go["DATABASE_URL"].replace(
                    "postgresql+psycopg://", "postgresql://"
                ),
                "COACHING_DECISION_TEST_ID": new["proposal_id"],
                "COACHING_DECISION_TEST_NOW": NOW,
            },
        )

        def receipts(conn):
            return conn.execute(
                "SELECT idempotency_key,result FROM coach_decision_keys ORDER BY idempotency_key"
            ).fetchall()

        assert receipts(refdb) == receipts(godb) and len(receipts(godb)) == 2
        for conn in (refdb, godb):
            assert conn.execute(
                "SELECT calendar_head_version FROM app_state WHERE id=1"
            ).fetchone() == (0,)
        for head, accept, reject in [(0, ["c1"], ["c2"]), (1, ["c1", "c2"], [])]:

            def make_pending(env):
                doc = document(env)
                c = doc["changes"][0]
                doc.update(
                    base_calendar_version=head,
                    headline=f"Decision {head}",
                    changes=[
                        c,
                        {
                            **c,
                            "change_id": "c2",
                            "after": {
                                **c["after"],
                                "slot": 1,
                                "intent": "Optional rest",
                            },
                        },
                    ],
                )
                res = python(env, "submit", document=doc)
                assert res["status"] == "pending", res
                return res["proposal_id"]

            pid, gid = make_pending(ref), make_pending(go)
            request = dict(
                expected_head=head,
                expected_revision=1,
                idempotency_key=f"accept-{head}-test",
                accept_change_ids=accept,
                reject_change_ids=reject,
            )
            expected = python(ref, "decide", id=pid, request=request)
            assert expected.get("calendar_version") == head + 1, expected
            subprocess.run(
                [
                    "go",
                    "test",
                    "-count=1",
                    "-run",
                    "^TestAcceptDecisionLedger$",
                    "./internal/coaching/drafts",
                ],
                cwd=ROOT / "backend-go",
                check=True,
                env={
                    **go,
                    "COACHING_DECISION_TEST_URL": go["DATABASE_URL"].replace(
                        "postgresql+psycopg://", "postgresql://"
                    ),
                    "COACHING_DECISION_TEST_ID": gid,
                    "COACHING_DECISION_TEST_NOW": NOW,
                    "COACHING_DECISION_TEST_REQUEST": json.dumps(request),
                },
            )

            def state(conn, id):
                return (
                    conn.execute(
                        "SELECT calendar_head_version,data_revision FROM app_state"
                    ).fetchall(),
                    conn.execute(
                        "SELECT number,parent_number,kind,actor,reason FROM calendar_versions ORDER BY number"
                    ).fetchall(),
                    conn.execute(
                        "SELECT revision,calendar_version_number,deleted,slot,local_date,kind,intent,certainty FROM calendar_session_revisions ORDER BY calendar_version_number,slot"
                    ).fetchall(),
                    conn.execute(
                        "SELECT change_id,decision,session_uid IS NOT NULL FROM coach_proposal_changes WHERE proposal_id=%s ORDER BY change_id",
                        (id,),
                    ).fetchall(),
                    conn.execute(
                        "SELECT status,decision_result - 'stale_proposals',jsonb_array_length(decision_result->'stale_proposals') FROM coach_proposals WHERE id=%s",
                        (id,),
                    ).fetchall(),
                )

            assert state(refdb, pid) == state(godb, gid), (
                state(refdb, pid),
                state(godb, gid),
            )
        from runpy import run_path

        block_fields = run_path(
            str(ROOT / "backend/tests/integration/test_proposals.py")
        )["_block_fields"]("2026-12-28", "2026-12-20")
        for conn in (refdb, godb):
            for day in ("2026-11-17", "2026-11-20"):
                conn.execute(
                    "INSERT INTO calendar_session_revisions(id,session_uid,revision,calendar_version_number,local_date,kind,intent,certainty) VALUES (%s,%s,1,2,%s,'strength','Synthetic lift','committed')",
                    (uuid4(), uuid4(), day),
                )
        for kind in ["anchor", "block", "continue"]:
            case_req = dict(
                expected_head=2,
                expected_revision=1,
                idempotency_key=f"planning-{kind}",
                accept_change_ids=[],
                reject_change_ids=[],
            )

            def planning_proposal(env, conn):
                doc = document(
                    env,
                    "recalibrate_intensity"
                    if kind == "anchor"
                    else "review_training_block",
                )
                doc.update(base_calendar_version=2, changes=[])
                if kind == "anchor":
                    doc["anchor_changes"] = [
                        dict(
                            kind="hr_threshold_lower",
                            value_low=165,
                            unit="bpm",
                            protocol="manual",
                            confidence="moderate",
                            calibrated_at=NOW,
                        )
                    ]
                    case_req["accept_anchor_changes"] = [
                        "hr_threshold_lower-2026-11-16"
                    ]
                else:
                    active = conn.execute(
                        "SELECT block_uid,id FROM block_versions ORDER BY version DESC LIMIT 1"
                    ).fetchone()
                    if active:
                        doc["base_block_version_id"] = str(active[1])
                    doc["block_change"] = dict(
                        decision="continue" if active else "start",
                        block_uid=str(active[0]) if active else None,
                        version_fields=block_fields,
                    )
                    case_req["accept_block_change"] = True
                prop = python(env, "submit", document=doc)
                assert prop["status"] == "pending", prop
                return prop["proposal_id"]

            pid, gid = planning_proposal(ref, refdb), planning_proposal(go, godb)
            expected = python(ref, "decide", id=pid, request=case_req)
            assert expected.get("status") == "accepted", expected
            subprocess.run(
                [
                    "go",
                    "test",
                    "-count=1",
                    "-run",
                    "^TestAcceptDecisionLedger$",
                    "./internal/coaching/drafts",
                ],
                cwd=ROOT / "backend-go",
                check=True,
                env={
                    **go,
                    "COACHING_DECISION_TEST_URL": go["DATABASE_URL"].replace(
                        "postgresql+psycopg://", "postgresql://"
                    ),
                    "COACHING_DECISION_TEST_ID": gid,
                    "COACHING_DECISION_TEST_NOW": NOW,
                    "COACHING_DECISION_TEST_REQUEST": json.dumps(case_req),
                },
            )
            for query in [
                "SELECT data_revision,calendar_head_version FROM app_state",
                "SELECT anchor_key,value_low,calibrated_at,review_after,status FROM intensity_anchors ORDER BY anchor_key",
                "SELECT version,why,benchmark,objective,build_outline FROM block_versions ORDER BY version",
                "SELECT decision,from_version,to_version,rationale FROM block_decisions ORDER BY to_version",
            ]:
                assert (
                    refdb.execute(query).fetchall() == godb.execute(query).fetchall()
                ), query
        views = Path(scratch) / "http-views.json"
        with views.open("w") as f:
            subprocess.run(
                [sys.executable, ROOT / "scripts/rewrite/coaching/http_reference.py"],
                env=go,
                cwd=ROOT,
                stdout=f,
                check=True,
            )
        subprocess.run(
            [
                "go",
                "test",
                "-count=1",
                "-run",
                "^TestReferenceViews$",
                "./internal/proposalhttp",
            ],
            cwd=ROOT / "backend-go",
            env={
                **go,
                "COACHING_HTTP_REFERENCE": str(views),
                "COACHING_DECISION_TEST_URL": go["DATABASE_URL"].replace(
                    "postgresql+psycopg://", "postgresql://"
                ),
            },
            check=True,
        )
    print(
        "Passed Python-created draft revision, no-duplicate retry, drift, rollback, concurrent edits, discard and native submit."
    )


if __name__ == "__main__":
    main()
