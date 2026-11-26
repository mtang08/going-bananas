"""Run the Python reference operations for the isolated pending-draft comparison."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))


def main():
    from app.api.coach import resolve_kb
    from app.db import SessionLocal
    from app.services.proposals.lifecycle import (
        RevisionRequest,
        discard_proposal,
        revise_proposal,
        submit_proposal,
    )
    from app.services.proposals.schema import DecisionError
    from app.services.snapshot.build import build_snapshot

    if os.environ.get("APP_MODE") != "test":
        raise ValueError("requires test mode")
    from app.services import derived

    derived.install()
    req = json.load(sys.stdin)
    now = datetime.fromisoformat(req["now"])
    with SessionLocal.begin() as s:
        name, schema = s.execute(
            text("SELECT current_database(), current_schema()")
        ).one()
        if name != "garmin_test" or not schema.startswith("go_drafts_"):
            raise ValueError("requires isolated schema")
        op = req["op"]
        if op == "seed":
            day = now.astimezone(ZoneInfo("America/New_York")).date()
            result = build_snapshot(s, "proceed_or_modify_today", day, now=now)
            print(
                json.dumps(
                    {"snapshot_id": result["snapshot_id"], "day": day.isoformat()}
                )
            )
            return
        try:
            if op == "decide":
                from dataclasses import asdict
                from app.services.proposals.decision import (
                    DecisionRequest,
                    decide_proposal,
                )

                from unittest.mock import patch
                from app.services import calendar

                # Pin the calendar writer's separate wall-clock day to the same
                # synthetic reference instant supplied to proposal validation.
                day = calendar.calendar_today(s, now)
                with patch.object(calendar, "calendar_today", return_value=day):
                    decision = decide_proposal(
                        s,
                        UUID(req["id"]),
                        DecisionRequest.model_validate(req["request"]),
                        now=now,
                        resolve_kb=resolve_kb,
                    )
                print(json.dumps(asdict(decision), default=str))
                return
            if op == "submit":
                r = submit_proposal(s, req["document"], now=now, resolve_kb=resolve_kb)
            elif op == "revise":
                r = revise_proposal(
                    s,
                    UUID(req["id"]),
                    RevisionRequest.model_validate(req["request"]),
                    now=now,
                    resolve_kb=resolve_kb,
                )
            else:
                r = discard_proposal(s, UUID(req["id"]), req["revision"], now=now)
            print(
                json.dumps(
                    {
                        "proposal_id": str(r.proposal_id),
                        "revision": r.revision,
                        "status": r.status,
                        "issues": [i.to_json() for i in r.issues],
                    }
                )
            )
        except DecisionError as exc:
            print(json.dumps({"code": exc.code}))
            s.rollback()


if __name__ == "__main__":
    main()
