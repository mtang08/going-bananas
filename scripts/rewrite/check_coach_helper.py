"""Exercise the packaged helper through separate native CLI and HTTP processes."""

import json
import os
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

import psycopg
from coach_dashboard_process import exercise_chat, install_fake
from coach_recovery_process import capture, recover, recovery_source
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from test_proposal_slice import ROOT, migrated_schema


def fixture_repo(scratch):
    # Keep helper files, persisted documents, the knowledge package and external
    # provider profiles under a scratch root. Build the actual checkout's Go code.
    root = scratch / "repo"
    shutil.copytree(
        ROOT / ".codex/skills/going-bananas-coach",
        root / ".codex/skills/going-bananas-coach",
    )
    shutil.copytree(ROOT / "running_coach_kb", root / "running_coach_kb")
    (root / "scripts").mkdir()
    for name in ("with-mode", "env.sh", "coach-cli"):
        shutil.copy2(ROOT / "scripts" / name, root / "scripts" / name)
    (root / "backend-go").symlink_to(ROOT / "backend-go", target_is_directory=True)
    return root


@contextmanager
def native_server(executable, root, env):
    cmd = [str(executable), "serve", "--listen", "127.0.0.1:0", "--repo", str(root)]
    with subprocess.Popen(
        cmd,
        env=env,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    ) as p:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(p.stdout, selectors.EVENT_READ)
                assert selector.select(25), "native HTTP server startup timed out"
                address = p.stdout.readline().strip()
            assert re.fullmatch(r"127\.0\.0\.1:\d+", address), (
                "native HTTP server did not start"
            )
            yield "http://" + address
        finally:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()


def exercise(root, env, base):
    from coach_chat_script import _plan

    helper = root / ".codex/skills/going-bananas-coach/scripts/coach_app.py"

    def run(*args, read_only=False, expected=0):
        command = [
            sys.executable,
            str(helper),
            "--repo",
            str(root),
            "--mode",
            "test",
            "--base-url",
            base,
        ]
        if read_only:
            command.append("--read-only")
        p = subprocess.run(
            command + list(args),
            check=False,
            env=env,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=200,
        )
        # The helper prints safe, structured protocol errors and private artifacts' paths.
        raw = p.stdout.strip() or p.stderr.strip()
        assert p.returncode == expected, (
            f"helper {args[0]} returned {p.returncode}: {raw[:750]}"
        )
        return json.loads(raw)

    def snapshot():
        saved = run(
            "snapshot",
            "--operation",
            "review_rolling_plan",
            "--save-response",
            read_only=True,
        )
        response = Path(saved["response_file"])
        assert (
            response.parent == root / "private/test/coach/responses"
            and response.stat().st_mode & 0o777 == 0o600
        )
        return json.loads(response.read_bytes())

    schema = run("schema", read_only=True)
    assert (
        schema["protocol"] == "coach_proposal.v2" and schema["activation"] == "manual"
    )
    assert (
        schema["required_authority"] == "calendar"
        and "proposal" in schema
        and "revision" in schema
    )
    assert run("active-proposal", read_only=True)["data"] == {"proposal": None}
    assert isinstance(
        run("exceptions", "--include", "recent", read_only=True)["data"]["findings"],
        list,
    )
    head = run("history", read_only=True)["data"]["items"][0]["number"]
    assert head == 1
    packet = snapshot()
    assert (
        packet["kb"]["excerpts"]
        and packet["payload"]["snapshot_meta"]["source_fingerprint"]
    )
    diff = run(
        "query", "calendar_diff", "--from", "0", "--to", str(head), read_only=True
    )
    assert diff["query"] == "calendar_diff" and len(diff["data"]["changes"]) == 5
    document, duration = _plan(packet)
    assert duration == 2100
    source = root / "private/athlete-approved.json"
    source.write_text(json.dumps(document))
    assert (
        run("submit", "--file", str(source), read_only=True, expected=2)["error"]
        == "read_only_command_required"
    )
    pending = run("submit", "--file", str(source))
    uid = pending["proposal_id"]
    assert pending["revision"] == 1 and pending["status"] == "pending"
    assert pending["review_url"] == base + "/#proposal/" + uid
    assert run("history", read_only=True)["data"]["items"][0]["number"] == head
    assert run("active-proposal", read_only=True)["data"]["proposal"]["id"] == uid
    current = run("proposal", uid, "--document", read_only=True)["data"]
    assert current["is_current"] and current["revision"] == 1
    updated = current["document"]
    updated["headline"] = "Keep the easy-run progression"
    updated["changes"][0]["after"]["planned_duration_s"] = 2160
    source.write_text(json.dumps(updated))
    revise = [
        "revise",
        uid,
        "--expected-revision",
        "1",
        "--reason",
        "Athlete requested one more easy minute.",
        "--file",
        str(source),
    ]
    revised = run(*revise)
    assert (
        revised["proposal_id"] == uid
        and revised["revision"] == 2
        and revised["status"] == "pending"
    )
    old = run("proposal", uid, "--document", "--revision", "1", read_only=True)["data"]
    assert old["document"]["changes"][0]["after"]["planned_duration_s"] == 2100
    assert run(*revise) == revised
    updated["changes"][0]["after"]["planned_duration_s"] = 2220
    source.write_text(json.dumps(updated))
    conflict = run(*revise, expected=2)
    assert conflict["error"] == "proposal_revision_conflict", conflict
    assert run("history", read_only=True)["data"]["items"][0]["number"] == head
    assert len(list((root / "private/test/coach/proposals").glob("*.json"))) == 4

    # This request models the athlete's separate, explicit review page action.
    decision = {
        "expected_head": head,
        "expected_revision": 2,
        "idempotency_key": "synthetic-helper-explicit-accept",
        "accept_change_ids": ["c1"],
        "reject_change_ids": [],
    }
    req = Request(
        base + f"/api/v1/coach/proposals/{uid}/decision",
        method="POST",
        data=json.dumps(decision).encode(),
        headers={"Content-Type": "application/json", "X-Local-Request": "1"},
    )
    with build_opener(ProxyHandler({})).open(req, timeout=60) as res:
        assert json.load(res)["data"]["status"] == "accepted"
    assert run("proposal", uid, read_only=True)["data"]["status"] == "accepted"
    assert run("active-proposal", read_only=True)["data"] == {"proposal": None}
    assert run("history", read_only=True)["data"]["items"][0]["number"] == head + 1
    after = snapshot()["payload"]["calendar"]["sessions"]
    target = document["changes"][0]["session_uid"]
    assert (
        next(s["planned_duration_s"] for s in after if s["session_uid"] == target)
        == 2160
    )
    run(
        "undo",
        "--expected-head",
        str(head + 1),
        "--target-version",
        str(head),
        "--reason",
        "Synthetic athlete explicitly requested undo.",
    )
    undone = snapshot()["payload"]["calendar"]["sessions"]
    assert (
        next(s["planned_duration_s"] for s in undone if s["session_uid"] == target)
        == 1800
    )
    assert run("history", read_only=True)["data"]["items"][0]["number"] == head + 2
    return uid


def main():
    url = make_url(os.environ["DASHBOARD_TEST_DATABASE_URL"])
    assert (
        os.environ.get("APP_MODE") == "test"
        and url.database == "garmin_test"
        and url.host in {"localhost", "127.0.0.1"}
    )
    assert re.fullmatch(r"go_parity_[a-f0-9]{32}", url.query["search_path"])
    url = url.difference_update_query(["search_path"])
    sys.path[:0] = [
        str(ROOT / "backend"),
        str(ROOT / "backend/tests/fixtures"),
        str(ROOT / "backend-go/internal/coachdashboardhttp/testdata"),
    ]
    from native_fixture import seed

    with (
        tempfile.TemporaryDirectory(
            dir=ROOT / "private", prefix="native-helper-"
        ) as tmp,
        recovery_source(url) as url,
        psycopg.connect(
            url.render_as_string(hide_password=False), autocommit=True
        ) as db,
    ):
        scratch = Path(tmp)
        root = fixture_repo(scratch)
        binary = scratch / "going-bananas"
        subprocess.run(
            ["go", "build", "-o", str(binary), "./cmd/going-bananas"],
            cwd=ROOT / "backend-go",
            check=True,
        )
        with migrated_schema(
            db, url.set(drivername="postgresql+psycopg"), scratch / "app", "5173"
        ) as env:
            engine = create_engine(
                url.set(drivername="postgresql+psycopg"),
                connect_args={"options": env["PGOPTIONS"]},
            )
            try:
                schema = seed(engine, datetime.now(ZoneInfo("America/New_York")).date())
            finally:
                engine.dispose()
            read_only_url = url.set(drivername="postgresql+psycopg").update_query_dict(
                {"search_path": schema, "default_transaction_read_only": "on"}
            )
            env.update(
                APP_MODE="test",
                GB_REPO=str(scratch / "ignored-inherited-checkout"),
                PRIVATE_DIR=str(root / "private/test"),
                DATABASE_URL=read_only_url.render_as_string(hide_password=False),
            )
            env["PGOPTIONS"] += " -cdefault_transaction_read_only=on"
            install_fake(root, env)
            with native_server(binary, root, env) as base:
                uid = exercise(root, env, base)
                agreement = exercise_chat(base)
                proof = capture(base, uid, agreement)
            recover(scratch, root, binary, env, proof, native_server)
    print("Native skill helper lifecycle passed against synthetic PostgreSQL.")


if __name__ == "__main__":
    main()
