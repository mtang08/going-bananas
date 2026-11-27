"""Build an approved proposal document from a synthetic coaching snapshot."""

from datetime import date, timedelta


def synthetic_proposal(snapshot: dict) -> tuple[dict, int]:
    payload = snapshot["payload"]
    meta = payload["snapshot_meta"]
    as_of = date.fromisoformat(meta["as_of"])
    run = next(
        row
        for row in payload["calendar"]["sessions"]
        if row["kind"] == "run"
        and row["local_date"] > meta["as_of"]
        and not row.get("locked")
        and row["planned_duration_s"]
        and not row["completion_status"]
    )
    duration = run["planned_duration_s"] + 300
    document = {
        "schema_version": "coach_proposal.v2",
        "operation": meta["operation"],
        "snapshot_id": snapshot["snapshot_id"],
        "base_calendar_version": meta["calendar_version"],
        "base_block_version_id": meta["block_version_id"],
        "headline": "Add five easy minutes",
        "why": [
            {"kind": "inference", "text": "A small change to the existing aerobic run."}
        ],
        "uncertainty": ["Response to the extra time is unknown."],
        "change_triggers": [
            {"when": "The run feels harder", "then": "Return to the original duration."}
        ],
        "next_check": {
            "on": (as_of + timedelta(days=7)).isoformat(),
            "check": "Review effort after the run.",
        },
        "confidence": {
            "decision": "moderate",
            "evidence": "moderate",
            "data": "moderate",
        },
        "changes": [
            {
                "change_id": "c1",
                "op": "modify",
                "session_uid": run["session_uid"],
                "after": {
                    "planned_duration_s": duration,
                    "brief": {
                        "effort": {
                            "rpe_low": 3,
                            "rpe_high": 4,
                            "feel": "conversational",
                        },
                        "focus": ["Keep your shoulders relaxed."],
                        "adjust_if": [
                            {
                                "when": "Effort rises",
                                "then": "Finish at the original duration.",
                            }
                        ],
                        "why": "Build easy aerobic time gradually.",
                    },
                },
                "reason": "A short progression while keeping effort easy.",
            },
        ],
        "preserved": [],
        "evidence_ids": [],
        "policy_ids": [],
        "recipe_ids": [],
        "skill_version": "running-coach.v1",
    }
    return document, duration
