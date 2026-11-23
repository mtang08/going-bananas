"""One-time omissions visible to subsequent reviews of the same dates."""

from collections import Counter
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision
from app.coach_v2_models import CoachProposal, CoachProposalChange


def accepted_strength_omissions(session: Session, start: date, end: date, schedule: list[dict]) -> list[dict]:
    # Per-change decisions and the original material flags are stored separately.
    change = CoachProposalChange
    day = func.coalesce(change.before["local_date"].astext, change.after["local_date"].astext)
    flagged_change = func.jsonb_build_object(
        "change_id", change.change_id, "material_flags", func.jsonb_build_array("strength_omission")
    )
    rows = session.execute(
        select(change, CoachProposal.base_calendar_version)
        .join_from(change, CoachProposal, change.proposal_id == CoachProposal.id)
        .where(
            change.decision == "accepted",
            CoachProposal.status.in_(("accepted", "partially_accepted")),
            day.between(start.isoformat(), end.isoformat()),
            CoachProposal.payload["changes"].contains(func.jsonb_build_array(flagged_change)),
        )
        .order_by(CoachProposal.decided_at, CoachProposal.id)
    ).all()
    if not rows:
        return []

    # Reinstating a lift (including undo) retires its old exception, even if
    # that lift subsequently moves or is removed again without an explanation.
    revision = CalendarSessionRevision
    first_monday = start - timedelta(days=start.weekday())
    last_sunday = end + timedelta(days=6 - end.weekday())
    by_date: dict[date, int] = {}
    by_slot: dict[tuple[date, str], int] = {}
    for day_value, slot_id, version in session.execute(
        select(revision.local_date, revision.strength_slot_id, func.max(revision.calendar_version_number))
        .where(
            revision.kind == "strength",
            revision.deleted.is_(False),
            revision.local_date.between(first_monday, last_sunday),
        )
        .group_by(revision.local_date, revision.strength_slot_id)
    ):
        by_date[day_value] = max(by_date.get(day_value, 0), version)
        if slot_id:
            slot_key = (day_value - timedelta(days=day_value.weekday()), str(slot_id))
            by_slot[slot_key] = max(by_slot.get(slot_key, 0), version)

    expected = {date.fromisoformat(item["local_date"]): item.get("strength_slot_id") for item in schedule}
    weekly_slots = Counter((day - timedelta(days=day.weekday()), slot) for day, slot in expected.items() if slot)
    omissions = {}
    for row, base_version in rows:
        lift = row.before or row.after
        assert lift is not None  # Flagged deletes have a before image, flagged adds an after image.
        local_date = lift["local_date"]
        omitted_day = date.fromisoformat(local_date)
        slot = lift.get("strength_slot_id")
        if row.op == "add" and (omitted_day not in expected or (slot and slot != expected[omitted_day])):
            continue
        last_version = by_date.get(omitted_day, 0)
        if slot:
            key = (omitted_day - timedelta(days=omitted_day.weekday()), slot)
            if weekly_slots[key] == 1:
                last_version = max(last_version, by_slot.get(key, 0))
        if last_version <= base_version:
            omissions[local_date] = {
                "local_date": local_date,
                "intent": lift["intent"],
                "reason": row.reason,
                **({"strength_slot_id": lift["strength_slot_id"]} if lift.get("strength_slot_id") else {}),
            }
    return [omissions[key] for key in sorted(omissions)]
