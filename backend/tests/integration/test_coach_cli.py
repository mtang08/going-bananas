"""CLI source snapshots and pending proposal submission, using synthetic state."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.coach_v2_models import CoachProposal, CoachSnapshot
from app.models import AppState
from app.services import calendar

NOW = datetime(2026, 11, 16, 15, tzinfo=UTC)
TODAY = date(2026, 11, 16)


def _doc(snapshot: CoachSnapshot, uid: uuid.UUID) -> dict:
    return {
        "schema_version": "coach_proposal.v1",
        "operation": snapshot.operation,
        "snapshot_id": str(snapshot.id),
        "base_calendar_version": snapshot.calendar_version_number,
        "base_block_version_id": None,
        "summary": "Add easy time",
        "rationale": "Ready for a small increase",
        "confidence": {"decision": "moderate", "evidence": "moderate", "data": "moderate"},
        "changes": [
            {
                "change_id": "c1",
                "op": "modify",
                "session_uid": str(uid),
                "after": {"planned_duration_s": 2400},
                "reason": "Progression",
            }
        ],
        "preserved": [],
        "evidence_ids": ["E-AER-01"],
        "policy_ids": ["P001"],
        "recipe_ids": ["REC001"],
        "skill_version": "running-coach.v1",
    }


@pytest.fixture
def cli_db(proposal_session, monkeypatch, capsys):
    import json
    import sys

    from sqlalchemy.orm import sessionmaker

    from app import cli

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(cli, "datetime", Clock)
    factory = sessionmaker(
        bind=proposal_session.bind,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
        info={"metrics_now": NOW},
    )
    monkeypatch.setattr(cli, "SessionLocal", factory)

    def run(*args):
        monkeypatch.setattr(sys, "argv", ["app.cli", "coach", *args])
        status = cli.main()
        captured = capsys.readouterr()
        return status, json.loads(captured.out) if captured.out else None, captured.err

    return run, proposal_session


def snapshot_doc(run, session):
    code, result, error = run("snapshot", "--operation", "review_rolling_plan")
    assert code == 0, error
    snapshot = session.get(CoachSnapshot, uuid.UUID(result["snapshot_id"]))
    uid = next(
        row["session_uid"]
        for row in calendar.state_at(session, snapshot.calendar_version_number)
        if row["kind"] == "run"
    )
    return result, _doc(snapshot, uid)


def write_doc(tmp_path, document):
    import json

    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(document))
    return str(path)


def test_snapshot_twice_same_payload_hash(cli_db):
    run, session = cli_db
    before = session.get(AppState, 1).data_revision
    first, _ = snapshot_doc(run, session)
    second, _ = snapshot_doc(run, session)
    a = session.get(CoachSnapshot, uuid.UUID(first["snapshot_id"]))
    b = session.get(CoachSnapshot, uuid.UUID(second["snapshot_id"]))
    assert a.id != b.id and a.payload_sha256 == b.payload_sha256
    assert session.get(AppState, 1, populate_existing=True).data_revision == before
    assert first["payload"]["snapshot_meta"]["source_fingerprint"] == a.source_fingerprint
    assert first["kb"]["excerpts"]


def test_resubmit_same_file_idempotent(cli_db, tmp_path):
    run, session = cli_db
    _, document = snapshot_doc(run, session)
    path = write_doc(tmp_path, document)
    code, first, error = run("submit", "--file", path)
    assert code == 0, (first, error)
    code, second, error = run("submit", "--file", path)
    assert code == 0 and first == second
    assert session.scalar(select(func.count()).select_from(CoachProposal)) == 1
    assert first["status"] == "pending"
    assert first["revision"] == 1
    assert session.get(AppState, 1, populate_existing=True).calendar_head_version == 1


def test_revise_same_id_and_retry(cli_db, tmp_path):
    run, session = cli_db
    _, document = snapshot_doc(run, session)
    code, first, error = run("submit", "--file", write_doc(tmp_path, document))
    assert code == 0, (first, error)
    document["rationale"] = "Updated coaching context"
    path = write_doc(tmp_path, document)
    command = (
        "revise",
        first["proposal_id"],
        "--expected-revision",
        "1",
        "--reason",
        "Clarify context",
        "--file",
        path,
    )
    code, second, error = run(*command)
    assert code == 0, (second, error)
    assert second["proposal_id"] == first["proposal_id"] and second["revision"] == 2
    code, retry, error = run(*command)
    assert code == 0 and retry == second, (retry, error)
    assert session.scalar(select(func.count()).select_from(CoachProposal)) == 1
    assert session.get(AppState, 1, populate_existing=True).calendar_head_version == 1
    document["rationale"] = "Different context"
    code, conflict, error = run(
        "revise",
        first["proposal_id"],
        "--expected-revision",
        "1",
        "--reason",
        "Try older version",
        "--file",
        write_doc(tmp_path, document),
    )
    assert code == 2 and conflict["error"] == "proposal_revision_conflict", (conflict, error)


def test_submit_invalid_exit_2_nothing_written(cli_db, tmp_path):
    run, session = cli_db
    _, document = snapshot_doc(run, session)
    document["extra_field"] = 1
    code, result, error = run("submit", "--file", write_doc(tmp_path, document))
    assert code == 2 and result["status"] == "invalid"
    assert result["proposal_id"] is None and result["errors"][0]["code"] == "V1.schema"
    assert session.scalar(select(func.count()).select_from(CoachProposal)) == 0


def test_manual_edit_stales_pending_proposal(cli_db, tmp_path):
    run, session = cli_db
    _, document = snapshot_doc(run, session)
    code, submitted, error = run("submit", "--file", write_doc(tmp_path, document))
    assert code == 0, (submitted, error)
    result = calendar.apply_edits(
        session,
        1,
        [
            {
                "op": "modify",
                "session_uid": uuid.UUID(document["changes"][0]["session_uid"]),
                "fields": {"intent": "Athlete change"},
            }
        ],
        "User edit",
    )
    session.commit()
    assert uuid.UUID(submitted["proposal_id"]) in result["stale_proposals"]
    assert session.get(CoachProposal, uuid.UUID(submitted["proposal_id"]), populate_existing=True).status == "stale"


def test_submit_stale_exit_3(cli_db, tmp_path):
    run, session = cli_db
    _, document = snapshot_doc(run, session)
    calendar.apply_edits(
        session,
        1,
        [
            {
                "op": "modify",
                "session_uid": uuid.UUID(document["changes"][0]["session_uid"]),
                "fields": {"intent": "Athlete change"},
            }
        ],
        "User edit",
    )
    session.commit()
    code, result, error = run("submit", "--file", write_doc(tmp_path, document))
    assert code == 3 and result["status"] == "stale"


def test_query_commands_and_schema(cli_db):
    run, session = cli_db
    code, schema, _ = run("schema")
    assert code == 0 and schema["activation"] == "manual" and schema["required_authority"] == "calendar"
    code, data, error = run("query", "calendar_diff", "--from", "0", "--to", "1")
    assert code == 0, error
    assert "changes" in data["data"]
    code, data, error = run("query", "activity_execution")
    assert code == 2 and "missing_argument" in error
    code, data, error = run("query", "activity_execution", "--activity-id", str(uuid.uuid4()))
    assert code == 4 and "activity_not_found" in error


def test_coach_router_and_structured_fields(cli_db):
    import asyncio
    import json

    from fastapi import HTTPException
    from starlette.requests import Request

    from app.main import app, handle_http

    assert "/api/v1/coach/proposals" in app.openapi()["paths"]
    response = asyncio.run(
        handle_http(
            Request({"type": "http"}),
            HTTPException(
                422,
                detail={
                    "code": "proposal_invalid_subset",
                    "message": "Invalid subset",
                    "fields": [{"code": "V9.strength_count", "path": "changes.1", "message": "Preserve strength"}],
                },
            ),
        )
    )
    assert json.loads(response.body)["error"]["fields"][0]["path"] == "changes.1"


def test_snapshot_kb_integrity_exit_4(cli_db, tmp_path, monkeypatch):
    import shutil

    from app.services import knowledge

    run, session = cli_db
    _, document = snapshot_doc(run, session)
    before = session.scalar(select(func.count()).select_from(CoachSnapshot))
    kb = tmp_path / "kb"
    shutil.copytree(knowledge.DEFAULT_ROOT, kb)
    workflow = kb / "workflows" / "weekly_review.md"
    workflow.write_bytes(workflow.read_bytes() + b" ")
    monkeypatch.setattr(knowledge, "DEFAULT_ROOT", kb)
    for args in [
        ("snapshot", "--operation", "review_rolling_plan"),
        ("submit", "--file", write_doc(tmp_path, document)),
    ]:
        code, result, error = run(*args)
        assert code == 4 and result is None and "knowledge_unavailable" in error
    assert session.scalar(select(func.count()).select_from(CoachSnapshot)) == before
    assert session.scalar(select(func.count()).select_from(CoachProposal)) == 0
    from app.api.metrics import recovery_nights

    assert recovery_nights(session, TODAY - timedelta(days=1), TODAY)["end"] == TODAY


def test_snapshot_excludes_checkin_notes(cli_db):
    from app.checkin_models import Checkin, SymptomReport

    run, session = cli_db
    checkin = Checkin(
        idempotency_key=str(uuid.uuid4()),
        kind="exception",
        observed_at=NOW - timedelta(hours=30),
        context_tags=[],
        note="cli-private-canary",
        gait_change="no",
    )
    session.add(checkin)
    session.flush()
    session.add(SymptomReport(checkin_id=checkin.id, site="ankle", side="left", severity=2, timing="next_morning"))
    session.commit()
    code, result, error = run("snapshot", "--operation", "review_rolling_plan")
    assert code == 0, error
    assert "cli-private-canary" not in str(result)
    assert any(report["severity"] == 2 for report in result["payload"]["symptoms"]["reports"])


@pytest.mark.parametrize("operation", ["exception_review", "post_event_review"])
def test_snapshot_new_review_operations(cli_db, operation):
    run, session = cli_db
    code, result, error = run("snapshot", "--operation", operation)
    assert code == 0, error
    meta = result["payload"]["snapshot_meta"]
    assert meta["operation"] == operation
    assert meta["scope"] == {"start": "2026-11-16", "end": "2026-11-22"}
    assert session.get(CoachSnapshot, uuid.UUID(result["snapshot_id"])).operation == operation
    assert result["kb"]["excerpts"]


def test_snapshot_refreshes_findings_and_sections(cli_db):
    from app.checkin_models import Checkin

    run, session = cli_db
    session.add(
        Checkin(
            idempotency_key=str(uuid.uuid4()),
            kind="exception",
            observed_at=NOW - timedelta(hours=1),
            context_tags=[],
            gait_change="no",
            fatigue=8,
        )
    )
    session.commit()
    code, result, error = run("snapshot", "--operation", "exception_review")
    assert code == 0, error
    assert any(f["rule_code"] == "FATIGUE_HIGH" for f in result["payload"]["exceptions"]["open_findings"])
    code, result, error = run("snapshot", "--operation", "review_rolling_plan")
    assert code == 0, error
    assert any(f["rule_code"] == "FATIGUE_HIGH" for f in result["payload"]["exception_summary"]["findings"])
    code, result, error = run("snapshot", "--operation", "post_event_review")
    assert code == 0, error
    assert result["payload"]["event"] is None
