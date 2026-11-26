"""Record the Python API response for each step of a synthetic proposal workflow."""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from app.api.coach import resolve_kb
from app.db import SessionLocal
from app.main import app
from app.services.proposals.lifecycle import submit_proposal


def main():
    docs = json.load(sys.stdin)
    doc = docs["document"]
    client = TestClient(app)
    headers = {"X-Local-Request": "1"}
    cases = []
    proposal_id = None
    for method, path, body in [
        ("POST", "", "document"),
        ("POST", "", "document"),
        (
            "POST",
            "/ID/revise",
            dict(
                expected_revision=1,
                reason="Change headline",
                document={**doc, "headline": "HTTP revision"},
            ),
        ),
        (
            "POST",
            "/ID/revise",
            dict(
                expected_revision=1,
                reason="Change headline",
                document={**doc, "headline": "HTTP revision"},
            ),
        ),
        (
            "POST",
            "/ID/revise",
            dict(
                expected_revision=1,
                reason="Different edit",
                document={**doc, "headline": "Conflict"},
            ),
        ),
        (
            "POST",
            "/ID/decision",
            dict(
                expected_revision=2,
                expected_head=2,
                idempotency_key="http-reject",
                accept_change_ids=[],
                reject_change_ids=["c1"],
            ),
        ),
        (
            "POST",
            "/ID/decision",
            dict(
                expected_revision=2,
                expected_head=2,
                idempotency_key="http-reject",
                accept_change_ids=[],
                reject_change_ids=["c1"],
            ),
        ),
        ("DELETE", "/ID?expected_revision=2", None),
        ("POST", "", "second"),
        ("DELETE", "/ID?expected_revision=1", None),
        ("DELETE", "/ID?expected_revision=1", None),
        ("POST", "/ID/revise", dict(reason="", expected_revision=0, document=[])),
        ("POST", "/ID/decision", dict(expected_head=0)),
    ]:
        if not path:
            authored = (
                {**doc, "headline": "HTTP discarded"} if body == "second" else doc
            )
            with SessionLocal.begin() as s:
                name, schema = s.execute(
                    text("SELECT current_database(),current_schema()")
                ).one()
                if (
                    os.environ.get("APP_MODE") != "test"
                    or name != "garmin_test"
                    or not schema.startswith("go_drafts_")
                ):
                    raise ValueError("expects isolated schema")
                res = submit_proposal(
                    s, authored, now=datetime.now(UTC), resolve_kb=resolve_kb
                )
                proposal_id = str(res.proposal_id)
                expected = dict(
                    data=dict(
                        proposal_id=proposal_id,
                        revision=res.revision,
                        status=res.status,
                        errors=[i.to_json() for i in res.issues],
                    ),
                    schema_version="v1",
                    mode="test",
                    data_revision=s.scalar(text("SELECT data_revision FROM app_state")),
                )
            status = 200
            body = authored
        else:
            response = client.request(
                method,
                "/api/v1/coach/proposals" + path.replace("ID", proposal_id),
                json=body,
                headers=headers,
            )
            status = response.status_code
            expected = response.json()
        if "error" in expected:
            expected["error"].pop("request_id")
        if isinstance(expected.get("data"), dict) and "proposal_id" in expected["data"]:
            expected["data"]["proposal_id"] = "ID"
        if isinstance(body, dict):
            target = body.get("document", body)
            if isinstance(target, dict) and "snapshot_id" in target:
                target = {
                    **target,
                    "snapshot_id": docs["candidate"]["snapshot_id"],
                    "base_block_version_id": docs["candidate"]["base_block_version_id"],
                }
                body = {**body, "document": target} if "document" in body else target
        cases.append(
            dict(method=method, path=path, body=body, status=status, expected=expected)
        )
    print(json.dumps(cases))


if __name__ == "__main__":
    main()
