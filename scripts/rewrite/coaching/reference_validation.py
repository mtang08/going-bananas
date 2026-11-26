"""Read-only reference adapter for the synthetic Go draft command."""

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))


def rules(data):
    from app.db import SessionLocal
    from app.services.decision_inputs import VerifiedKnowledge, collect_decision_inputs
    from app.services.proposals.context import load_context
    from app.services.proposals.schema import ProposalDoc
    from app.services.proposals.validation import _rules
    from sqlalchemy import text

    export = data["snapshot"]
    if not re.fullmatch(r"[0-9A-F]+-[0-9A-F]+-[0-9]+", export):
        raise ValueError("invalid exported snapshot identifier")
    doc = ProposalDoc.model_validate(data["document"])
    now = datetime.fromisoformat(data["now"])
    k, i = data["knowledge"], data["index"]
    kb = VerifiedKnowledge(
        k["digest"],
        tuple(k["selection"] or []),
        tuple(k["selected_records"]),
        frozenset(i["PolicyIDs"]),
        frozenset(i["RecipeIDs"]),
        frozenset(i["EvidenceIDs"]),
    )
    with SessionLocal() as session:
        session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )
        session.execute(text(f"SET TRANSACTION SNAPSHOT '{export}'"))
        ctx = load_context(session, doc.snapshot_id, now=now, kb=kb)
        facts = collect_decision_inputs(
            session, ctx.snapshot.operation, ctx.snapshot.as_of, now=now, kb=kb
        )
        issues = _rules(doc, ctx)
        changes = []
        for c in doc.changes:
            before = ctx.head_sessions.get(c.session_uid)
            after = (
                c.after.model_dump(mode="json", exclude_unset=True) if c.after else None
            )
            if c.is_unplanned_strength_omission and after and after.get("local_date"):
                slot = ctx.confirmed_strength_slot_ids.get(
                    date.fromisoformat(after["local_date"])
                )
                if slot:
                    after["strength_slot_id"] = str(slot)
            changes.append(
                {
                    "change_id": c.change_id,
                    "op": c.op,
                    "session_uid": c.session_uid,
                    "before": vars(before) if before else None,
                    "after": after,
                    "reason": c.reason,
                }
            )
        return {
            "current": {
                "today": ctx.today,
                "head": ctx.head_version,
                "block_id": ctx.active_block.version_id if ctx.active_block else None,
                "sources": facts["source_versions"],
            },
            "issues": [x.to_json() for x in issues],
            "changes": changes,
        }


def main():
    from app.services.proposals.schema import parse_document

    if os.environ.get("APP_MODE") not in {"demo", "test"}:
        raise ValueError("requires synthetic mode")
    data = json.load(sys.stdin)
    if sys.argv[1] == "parse":
        doc, issues = parse_document(data)
        out = {"issues": [i.to_json() for i in issues]}
        if doc:
            out.update(
                document=doc.model_dump(mode="json"),
                payload=doc.model_dump(mode="json", exclude_unset=True),
            )
    elif sys.argv[1] == "rules":
        out = rules(data)
    else:
        raise ValueError("invalid reference operation")

    def wire(v):
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        if isinstance(v, UUID):
            return str(v)
        raise TypeError(type(v).__name__)

    json.dump(out, sys.stdout, default=wire, allow_nan=False)


if __name__ == "__main__":
    main()
