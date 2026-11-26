"""Read a persisted synthetic draft in Go and compare discard receipts and durable state."""

import json
import os
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[3]
DRAFT_ID = UUID("00000000-0000-0000-0000-000000000033")


def main():
    env = os.environ.copy()
    url = make_url(env["DATABASE_URL"])
    if (
        env.get("APP_MODE") != "test"
        or url.database != "garmin_test"
        or url.host not in {"127.0.0.1", "localhost"}
    ):
        raise ValueError(
            "requires a dedicated loopback garmin_test database in test mode"
        )
    pg = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with (
        tempfile.TemporaryDirectory(dir=ROOT / "private") as scratch,
        ExitStack() as cleanup,
    ):
        binary = Path(scratch) / "coaching"
        subprocess.run(
            ["go", "build", "-o", binary, "./cmd/coaching"],
            cwd=ROOT / "backend-go",
            check=True,
        )
        db = cleanup.enter_context(psycopg.connect(pg, autocommit=True))
        assert db.execute("SELECT current_database()").fetchone() == ("garmin_test",)
        targets = []
        for name in ("reference", "candidate"):
            schema = "go_drafts_" + uuid4().hex
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cleanup.callback(
                db.execute,
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)),
            )
            options = "-csearch_path=" + schema
            dest = dict(
                env,
                PGOPTIONS=options,
                PRIVATE_DIR=scratch,
                PYTHONPATH=str(ROOT / "backend"),
            )
            subprocess.run(
                [os.sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=ROOT / "backend",
                env=dest,
                check=True,
            )
            conn = cleanup.enter_context(
                psycopg.connect(pg, options=options, autocommit=True)
            )
            assert conn.execute("SELECT current_schema()").fetchone() == (schema,)
            conn.execute(
                (ROOT / "backend/tests/fixtures/proposal-list.sql").read_text()
            )
            # Both backends read a persisted change added to the synthetic draft.
            conn.execute(
                """INSERT INTO coach_proposal_changes (id,proposal_id,change_id,op,reason,decision)
                            VALUES (%s,%s,'c1','add','Fixture','pending')""",
                (uuid4(), DRAFT_ID),
            )
            targets.append((dest, conn))
        (ref, ref_db), (go, go_db) = targets

        def command(env, *args, ok=True):
            r = subprocess.run(args, env=env, text=True, capture_output=True, check=ok)
            return json.loads(r.stdout if ok else r.stderr)

        loaded = command(go, binary, "load", "-id", str(DRAFT_ID))
        assert (
            loaded["revision"] == 1
            and loaded["status"] == "pending"
            and loaded["changes"]["c1"]["op"] == "add"
        )
        assert (
            command(
                go, binary, "discard", "-id", str(DRAFT_ID), "-revision", "2", ok=False
            )["code"]
            == "proposal_revision_conflict"
        )
        python = (
            """from datetime import datetime,UTC
import json,uuid
from app.db import SessionLocal
from app.services.proposals.lifecycle import discard_proposal
with SessionLocal.begin() as session:
 r=discard_proposal(session,uuid.UUID('%s'),1,now=datetime.now(UTC))
 print(json.dumps({'proposal_id':str(r.proposal_id),'revision':r.revision,'status':r.status}))
"""
            % DRAFT_ID
        )
        for _ in range(2):
            assert command(ref, os.sys.executable, "-c", python) == command(
                go, binary, "discard", "-id", str(DRAFT_ID), "-revision", "1"
            )
        query = """SELECT p.revision,p.status,p.discarded_at IS NOT NULL,s.data_revision,s.calendar_head_version
                 FROM coach_proposals p CROSS JOIN app_state s WHERE p.id=%s AND s.id=1"""
        assert (
            ref_db.execute(query, (DRAFT_ID,)).fetchone()
            == go_db.execute(query, (DRAFT_ID,)).fetchone()
            == (1, "discarded", True, 17, 0)
        )
    print(
        "Matched load, revision conflict, discard, replay and unchanged calendar/revision on two migrated schemas."
    )


if __name__ == "__main__":
    main()
