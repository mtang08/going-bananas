"""Read-only reference adapter for the synthetic Go draft command."""

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))


def rule_inputs(doc, ctx):
    return {
        "rule_context": {
            "today": ctx.today,
            "timezone": str(ctx.tz),
            "guard": ctx.current_safety_guard,
            "interruption": ctx.running_interruption.model_dump(mode="json")
            if ctx.running_interruption
            else None,
            "restriction": ctx.running_restriction.model_dump(mode="json")
            if ctx.running_restriction
            else None,
            "eligible_recipes": ctx.active_block.eligible_recipe_ids
            if ctx.active_block
            else [],
            "cycle_anchor": ctx.cycle_anchor,
            "review_date": ctx.active_block.review_date if ctx.active_block else None,
            "confirmed_dates": {str(x): True for x in ctx.confirmed_strength_dates},
            "omitted_dates": {
                str(x): True for x in ctx.accepted_strength_omission_dates
            },
            "confirmed_slots": {
                str(k): str(v) for k, v in ctx.confirmed_strength_slot_ids.items()
            },
            "omitted_slots": {
                str(k): str(v)
                for k, v in ctx.accepted_strength_omission_slot_ids.items()
            },
            "block_uid": str(ctx.active_block.block_uid) if ctx.active_block else "",
            "head_sessions": {
                str(uid): vars(row) for uid, row in ctx.head_sessions.items()
            },
            "findings": {str(k): v for k, v in ctx.findings.items()},
            "patches": {str(k): v for k, v in ctx.patches.items()},
            "events": {
                str(k): {
                    "status": v[0],
                    "day": v[1],
                    "rank": v[2] if len(v) > 2 else None,
                }
                for k, v in ctx.events.items()
            },
            "open_rule_codes": sorted(ctx.open_rule_codes),
            "benchmark": {
                k: getattr(ctx.benchmark, k, None)
                for k in ("status", "activity_id", "event_id", "local_date")
            }
            if ctx.benchmark
            else None,
            "last_benchmark_date": ctx.last_benchmark_date,
        },
    }


def rules(data):
    from app.db import SessionLocal
    from app.services.decision_inputs import VerifiedKnowledge, collect_decision_inputs
    from app.services.proposals.context import load_context
    from app.services.proposals.schema import ProposalDoc
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
            **rule_inputs(doc, ctx),
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
