"""Link a reviewed prescription to recorded execution without interpreting the athlete's response."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, CalendarVersion
from app.coach_v2_models import CoachProposal, CoachProposalChange
from app.domain.calendar_structure import StructureError, expand_structure
from app.read.workout_feedback import load_workout_feedback


def _accepted_dose(accepted: CalendarSessionRevision) -> dict:
    duration, distance = accepted.planned_duration_s, accepted.planned_distance_m
    steps: list[dict]
    try:
        steps = expand_structure(accepted.structure) if isinstance(accepted.structure, list) else []
    except StructureError:
        steps = []
    if steps and duration is None and all(s["duration_type"] == "time" for s in steps):
        duration = sum(s["duration_value"] for s in steps)
    if steps and distance is None and all(s["duration_type"] == "distance" for s in steps):
        distance = sum(s["duration_value"] for s in steps)
    return {
        "local_date": accepted.local_date.isoformat(),
        "intent": accepted.intent,
        "duration_s": duration,
        "distance_m": distance,
        "effort": (accepted.brief or {}).get("effort"),
    }


def weekly_follow_up(
    session: Session, rows: list[dict], revisions: dict[str, int], today: date, now: datetime
) -> dict | None:
    due = {
        UUID(row["session_uid"]): row
        for row in rows
        if row["kind"] == "run" and row["local_date"] <= today.isoformat() and row["outcome"] != "planned"
    }
    if not due:
        return None
    rev, change, proposal, version = CalendarSessionRevision, CoachProposalChange, CoachProposal, CalendarVersion
    statement = (
        select(rev, change.op, change.reason, proposal.id, proposal.next_check)
        .select_from(change)
        .join(proposal, proposal.id == change.proposal_id)
        .join(version, version.proposal_id == proposal.id)
        .join(rev, and_(rev.calendar_version_number == version.number, rev.session_uid == change.session_uid))
        .where(
            change.session_uid.in_(due),
            change.decision == "accepted",
            change.op.in_(("add", "move", "modify")),
            proposal.status.in_(("accepted", "partially_accepted")),
            proposal.decided_at <= now,
            rev.kind == "run",
            rev.deleted.is_(False),
            rev.placeholder.is_(False),
        )
    )
    # Start with the newest implemented decision. Within a batch prefer an adjustment,
    # then a key workout, then the most recently scheduled run. Unknown outcomes remain eligible.
    selected = max(
        session.execute(statement).tuples(),
        key=lambda item: (
            item[0].calendar_version_number,
            item[1] != "add",
            due[item[0].session_uid]["key"],
            due[item[0].session_uid]["local_date"],
            str(item[0].session_uid),
        ),
        default=None,
    )
    if selected is None:
        return None
    accepted, op, reason, proposal_id, next_check = selected
    uid = str(accepted.session_uid)
    row = due[accepted.session_uid]
    actual = row["actual"]
    feedback = None
    if actual and actual["subject"] == "activity":
        activity_id = UUID(actual["id"])
        feedback = load_workout_feedback(session, [activity_id], now).get(activity_id)
    return {
        "proposal_id": str(proposal_id),
        "session_uid": uid,
        "op": op,
        "reason": reason,
        "accepted": _accepted_dose(accepted),
        "edited_since": revisions[uid] != accepted.revision,
        "outcome": row["outcome"],
        "modification_reason": row["modification_reason"],
        "actual": {k: actual[k] for k in ("id", "subject", "local_date", "duration_s", "distance_m", "rpe")}
        if actual
        else None,
        "response": {
            "observed_at": feedback["observed_at"].isoformat() if feedback["observed_at"] else None,
            "hours_after_end": feedback["hours_after_end"],
            "pain_reported": feedback["pain_reported"],
            "gait_change": feedback["gait_change"],
            "symptoms": feedback["symptoms"],
        }
        if feedback and feedback["checkin_id"]
        else None,
        "next_check": next_check,
    }
