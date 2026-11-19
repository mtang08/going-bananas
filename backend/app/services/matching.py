"""Deterministic plan to actual matching; callers own the transaction."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, date, datetime, timedelta
from itertools import permutations
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.domain.calendar_structure import StructureError, expand_structure
from app.domain.local_time import date_in_zone
from app.fit_models import ActivityWorkoutStep
from app.metrics.engine import load_runs
from app.models import Activity, ManualSession
from app.read.calendar import head_version, latest_revision, latest_revisions
from app.services.timezone import athlete_tz
from app.strong_models import StrongWorkoutRow

EXTRA_NAMESPACE = UUID("e35269d4-74b0-53bf-8a74-f01b3ef69218")
PROTECTED_METHODS = {"explicit", "user_marked", "confirmed_move"}
ELIGIBLE_KINDS = {"run", "strength"}
MATCHING_RULES = {
    "fragment_timer_s": 300,
    "fragment_distance_m": 400,
    "margin": math.log(1.5),
    "structure_mismatch_cost": 0.5,
}


def sessions_at_head(session: Session, start: date, end_excl: date) -> list[CalendarSessionRevision]:
    rows = latest_revisions(session).values()
    return sorted(
        (r for r in rows if not r.deleted and start <= r.local_date < end_excl),
        key=lambda r: (r.local_date, r.kind, r.slot, str(r.session_uid)),
    )


def _subject_key(row: dict) -> str | None:
    if row.get("subject_key"):
        return str(row["subject_key"])
    for field, prefix in (("activity_id", ""), ("strong_workout_id", "strong:"), ("manual_session_id", "manual:")):
        if row.get(field):
            return prefix + str(row[field])
    return None


def _day(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _kind(row: dict) -> str:
    if row.get("kind") in ELIGIBLE_KINDS:
        return str(row["kind"])
    return "strength" if str(_subject_key(row)).startswith(("strong:", "manual:")) else "run"


def _fragment(subject: dict) -> bool:
    timer, distance = subject.get("timer_s"), subject.get("distance_m")
    return _kind(subject) == "run" and (
        (timer is not None and timer < MATCHING_RULES["fragment_timer_s"])
        or (distance is not None and distance < MATCHING_RULES["fragment_distance_m"])
    )


def _pair_cost(plan: dict, subject: dict) -> float:
    cost = 0.0
    for actual_key, planned_key in (("timer_s", "planned_duration_s"), ("distance_m", "planned_distance_m")):
        actual, planned = subject.get(actual_key), plan.get(planned_key)
        if actual is not None and planned is not None and actual > 0 and planned > 0:
            cost += abs(math.log(actual / planned))
    planned_work, recorded_steps = plan.get("has_work_steps"), subject.get("has_workout_steps")
    if planned_work is not None and recorded_steps is not None and planned_work != recorded_steps:
        cost += MATCHING_RULES["structure_mismatch_cost"]
    return cost


def _day_choice(
    plans: list[dict], subjects: list[dict], kind: str
) -> tuple[list[tuple[dict, dict]], list[list[float]]]:
    if len(plans) == len(subjects) == 1:
        return [(plans[0], subjects[0])], []
    if kind != "run" or not (1 <= len(plans) <= 2 and 2 <= len(subjects) <= 3):
        return [], []
    costs = [[_pair_cost(plan, subject) for subject in subjects] for plan in plans]
    # Subject positions follow start order, with the subject key breaking equal start times.
    scores = sorted(
        (sum(costs[i][j] for i, j in enumerate(order)), order)
        for order in permutations(range(len(subjects)), len(plans))
    )
    (best, assignment), (second, _) = scores[:2]
    if second - best >= MATCHING_RULES["margin"]:
        return [(plan, subjects[j]) for plan, j in zip(plans, assignment, strict=True)], []
    return [], costs


def _candidate(subject: dict, reason: str) -> dict:
    return {
        "subject_key": _subject_key(subject),
        "local_date": _day(subject["local_date"]).isoformat(),
        "kind": _kind(subject),
        "reason": reason,
    }


def plan_matches(
    days: list[date],
    planned: list[dict],
    runs: list[dict],
    completions: list[dict],
    *,
    context_days: list[date] | None = None,
) -> dict:
    """Return only unambiguous links; candidate lists explain every unresolved plan."""
    day_scope = set(days)
    context = set(context_days or days) | day_scope
    plans = [
        p
        for p in planned
        if p.get("kind") in ELIGIBLE_KINDS
        and not p.get("deleted")
        and not p.get("skipped")
        and _day(p["local_date"]) in context
    ]
    plans.sort(key=lambda p: (_day(p["local_date"]), p["kind"], str(p["session_uid"])))
    context_subjects = [r for r in runs if _subject_key(r) and _day(r["local_date"]) in context]
    subjects = [
        r for r in context_subjects if r.get("eligible", True) and r.get("resolution_state", "resolved") == "resolved"
    ]
    plan_by_uid = {str(p["session_uid"]): p for p in plans}
    subject_by_key = {_subject_key(r): r for r in context_subjects}
    eligible_keys = {_subject_key(r) for r in subjects}
    protected_uids = set()
    protected_subjects = set()
    recheck_auto = {}
    delete_auto = set()
    existing_extra_subjects = set()
    for completion in completions:
        uid = str(completion["session_uid"])
        key = _subject_key(completion)
        method = completion.get("match_method")
        if method == "user_marked" and completion.get("status") == "completed_as_planned" and not key:
            continue  # A later import can supply the recording for a self-report.
        if method in PROTECTED_METHODS or completion.get("status") == "skipped":
            protected_uids.add(uid)
            if key:
                protected_subjects.add(key)
        elif method == "auto_same_day":
            plan, subject = plan_by_uid.get(uid), subject_by_key.get(key)
            if plan is not None and subject is not None and _day(plan["local_date"]) in day_scope:
                if (
                    key not in eligible_keys
                    or _fragment(subject)
                    or _day(plan["local_date"]) != _day(subject["local_date"])
                    or plan["kind"] != _kind(subject)
                ):
                    delete_auto.add(uid)
                else:
                    recheck_auto[uid] = key
            else:
                protected_uids.add(uid)
                if key:
                    protected_subjects.add(key)
        elif completion.get("status") == "extra" and key:
            subject = subject_by_key.get(key)
            if subject is not None and _day(subject["local_date"]) in day_scope:
                existing_extra_subjects.add(key)
    available_plans = [p for p in plans if str(p["session_uid"]) not in protected_uids]
    fragments = [r for r in subjects if _subject_key(r) not in protected_subjects and _fragment(r)]
    available_subjects = [r for r in subjects if _subject_key(r) not in protected_subjects and not _fragment(r)]
    links: list[dict] = []
    candidates: dict[str, list[dict]] = {}
    winners: dict[str, str | None] = {}
    plan_scores: dict[str, list[float]] = {}
    for day in sorted(context):
        for kind in ("run", "strength"):
            day_plans = [p for p in available_plans if _day(p["local_date"]) == day and p["kind"] == kind]
            day_subjects = [r for r in available_subjects if _day(r["local_date"]) == day and _kind(r) == kind]
            chosen, costs = _day_choice(day_plans, day_subjects, kind)
            for plan, subject in chosen:
                uid, key = str(plan["session_uid"]), _subject_key(subject)
                winners[uid] = key
                if day in day_scope and recheck_auto.get(uid) != key:
                    links.append({"session_uid": uid, "subject_key": key, "match_method": "auto_same_day"})
            for plan, scores in zip(day_plans, costs):
                plan_scores[str(plan["session_uid"])] = scores
    delete_auto.update(uid for uid, key in recheck_auto.items() if winners.get(uid) != key)
    linked_subjects = set(winners.values())
    for day in sorted(day_scope):
        for kind in ("run", "strength"):
            day_plans = [p for p in available_plans if _day(p["local_date"]) == day and p["kind"] == kind]
            day_subjects = [
                r
                for r in available_subjects
                if _day(r["local_date"]) == day and _kind(r) == kind and _subject_key(r) not in linked_subjects
            ]
            for plan in day_plans:
                uid = str(plan["session_uid"])
                if uid in winners:
                    continue
                if uid in plan_scores:
                    scored = sorted(zip(plan_scores[uid], day_subjects, strict=True), key=lambda pair: pair[0])
                    same = [{**_candidate(r, "AMBIGUOUS_MATCH"), "cost": round(cost, 3)} for cost, r in scored]
                else:
                    reason = "AMBIGUOUS_MATCH" if len(day_plans) > 1 or len(day_subjects) > 1 else "SAME_DAY_CANDIDATE"
                    same = [_candidate(r, reason) for r in day_subjects]
                    if kind == "run" and not same:
                        same = [
                            _candidate(r, "MOVE_CANDIDATE")
                            for r in available_subjects
                            if _kind(r) == "run"
                            and _subject_key(r) not in linked_subjects
                            and abs((_day(r["local_date"]) - day).days) == 1
                        ]
                    same.sort(key=lambda c: (c["local_date"], c["kind"], c["subject_key"]))
                if kind == "run":
                    same.extend(_candidate(r, "FRAGMENT_CANDIDATE") for r in fragments if _day(r["local_date"]) == day)
                candidates[uid] = same
    extras = []
    for subject in available_subjects:
        key = _subject_key(subject)
        if key is None or key in linked_subjects:
            continue
        day = _day(subject["local_date"])
        if day not in day_scope or any(
            p["kind"] == _kind(subject) and abs((_day(p["local_date"]) - day).days) <= 1 for p in plans
        ):
            continue
        extras.append(
            {
                "session_uid": str(uuid.uuid5(EXTRA_NAMESPACE, f"extra:{key}")),
                "subject_key": key,
                "match_method": "none",
            }
        )
    extras.sort(key=lambda e: e["subject_key"])
    # Existing extra rows may need replacement once a planned match becomes possible.
    delete_extra = sorted(existing_extra_subjects - {e["subject_key"] for e in extras})
    return {
        "delete_auto_session_uids": sorted(delete_auto),
        "delete_extra_subject_keys": delete_extra,
        "links": links,
        "extras": extras,
        "candidates": candidates,
    }


def _completion_dict(row: SessionCompletion) -> dict:
    return {
        "session_uid": row.session_uid,
        "activity_id": row.activity_id,
        "strong_workout_id": row.strong_workout_id,
        "manual_session_id": row.manual_session_id,
        "status": row.status,
        "match_method": row.match_method,
    }


def _subject_columns(key: str) -> dict:
    if key.startswith("strong:"):
        return {"strong_workout_id": UUID(key[7:])}
    if key.startswith("manual:"):
        return {"manual_session_id": UUID(key[7:])}
    return {"activity_id": UUID(key)}


def _matching_plan(plan: CalendarSessionRevision) -> dict:
    has_work_steps = False
    if plan.structure:
        try:
            has_work_steps = any(step["type"] == "work" for step in expand_structure(cast(list[dict], plan.structure)))
        except StructureError:
            pass
    return {
        "session_uid": plan.session_uid,
        "local_date": plan.local_date,
        "kind": plan.kind,
        "planned_duration_s": plan.planned_duration_s,
        "planned_distance_m": plan.planned_distance_m,
        "has_work_steps": has_work_steps,
    }


def _matching_runs(session: Session, start: date, end: date) -> list[dict]:
    runs = load_runs(session, start, end)
    if not runs:
        return []
    ids = [run.activity_id for run in runs]
    with_steps = set(
        session.scalars(
            select(ActivityWorkoutStep.activity_id).where(ActivityWorkoutStep.activity_id.in_(ids)).distinct()
        )
    )
    return [
        {
            "subject_key": str(run.activity_id),
            "local_date": run.local_date,
            "kind": "run",
            "timer_s": run.timer_s,
            "distance_m": run.distance_m,
            "has_workout_steps": run.activity_id in with_steps,
        }
        for run in runs
    ]


def rematch_dates(session: Session, dates: set[date]) -> set[UUID]:
    if not dates:
        return set()
    now = session.info.get("metrics_now") or datetime.now(UTC)
    head = head_version(session)
    if head == 0:
        return set()
    origin = session.scalar(
        select(func.min(CalendarSessionRevision.local_date)).where(
            CalendarSessionRevision.calendar_version_number <= head
        )
    )
    if origin is None:
        return set()
    days = sorted(
        {d + timedelta(days=offset) for d in dates for offset in (-1, 0, 1) if d + timedelta(days=offset) >= origin}
    )
    if not days:
        return set()
    context_days = sorted(
        {d + timedelta(days=offset) for d in days for offset in range(-2, 3) if d + timedelta(days=offset) >= origin}
    )
    context = set(context_days)
    first, last = context_days[0], context_days[-1] + timedelta(days=1)
    plans = sessions_at_head(session, first, last)
    planned = [_matching_plan(plan) for plan in plans]
    runs = _matching_runs(session, first, last)
    strong = session.scalars(
        select(StrongWorkoutRow).where(
            StrongWorkoutRow.local_date >= first,
            StrongWorkoutRow.local_date < last,
            StrongWorkoutRow.resolution_state == "resolved",
        )
    ).all()
    runs += [{"subject_key": f"strong:{r.id}", "local_date": r.local_date, "kind": "strength"} for r in strong]
    manual = session.scalars(
        select(ManualSession).where(
            ManualSession.date >= first,
            ManualSession.date < last,
            ManualSession.kind == "strength",
            ManualSession.linked_activity_id.is_(None),
        )
    ).all()
    runs += [{"subject_key": f"manual:{r.id}", "local_date": r.date, "kind": "strength"} for r in manual]
    existing = session.scalars(select(SessionCompletion)).all()
    context_plan_uids = {str(p["session_uid"]) for p in planned if p["local_date"] in context}
    historical = session.scalars(
        select(CalendarSessionRevision.session_uid).where(
            CalendarSessionRevision.local_date.in_(context_days),
            CalendarSessionRevision.calendar_version_number <= head,
        )
    ).all()
    context_plan_uids.update(str(uid) for uid in historical)
    context_subject_keys = {str(r["subject_key"]) for r in runs if r["local_date"] in context}
    zone = athlete_tz(session)
    # A held subject omitted from eligible results can still disprove an auto link.
    for completion in existing:
        key = _subject_key(_completion_dict(completion))
        if key is None or key in context_subject_keys:
            continue
        subject_day = None
        if completion.activity_id:
            raw = session.get(Activity, completion.activity_id)
            subject_day = date_in_zone(raw.start_at, zone) if raw else None
        elif completion.strong_workout_id:
            raw_strong = session.get(StrongWorkoutRow, completion.strong_workout_id)
            subject_day = raw_strong.local_date if raw_strong else None
        elif completion.manual_session_id:
            raw_manual = session.get(ManualSession, completion.manual_session_id)
            subject_day = raw_manual.date if raw_manual else None
        if subject_day in context:
            context_subject_keys.add(key)
            runs.append({"subject_key": key, "local_date": subject_day, "eligible": False})
    context_existing = [
        c
        for c in existing
        if str(c.session_uid) in context_plan_uids or _subject_key(_completion_dict(c)) in context_subject_keys
    ]
    result = plan_matches(
        days, planned, runs, [_completion_dict(c) for c in context_existing], context_days=context_days
    )
    affected: set[UUID] = set()
    by_uid = {str(c.session_uid): c for c in context_existing}
    deleted_uids: set[str] = set()
    for uid in result["delete_auto_session_uids"]:
        old = by_uid.get(uid)
        if old is not None and old.match_method == "auto_same_day":
            affected.add(old.session_uid)
            session.delete(old)
            deleted_uids.add(uid)
    for key in result["delete_extra_subject_keys"]:
        for old in context_existing:
            if old.status == "extra" and _subject_key(_completion_dict(old)) == key:
                affected.add(old.session_uid)
                session.delete(old)
                deleted_uids.add(str(old.session_uid))
    if deleted_uids:
        session.flush()
    for item in result["links"] + result["extras"]:
        uid = UUID(item["session_uid"])
        old = by_uid.get(str(uid))
        if old is not None and str(uid) not in deleted_uids:
            self_report = old.match_method == "user_marked" and old.status == "completed_as_planned"
            if (old.match_method in PROTECTED_METHODS and not self_report) or old.status == "skipped":
                continue
            new_subject = _subject_columns(item["subject_key"])
            old_subject = _subject_key(_completion_dict(old))
            if old_subject != item["subject_key"] or old.match_method != item["match_method"]:
                old.activity_id = new_subject.get("activity_id")
                old.strong_workout_id = new_subject.get("strong_workout_id")
                old.manual_session_id = new_subject.get("manual_session_id")
                old.match_method = item["match_method"]
                old.status = "extra" if item in result["extras"] else "unknown"
                old.input_version += 1
                old.version += 1
                old.updated_at = now
                affected.add(uid)
            continue
        row = SessionCompletion(
            session_uid=uid,
            status="extra" if item in result["extras"] else "unknown",
            match_method=item["match_method"],
            updated_at=now,
            **_subject_columns(item["subject_key"]),
        )
        session.add(row)
        affected.add(uid)
    return affected


def candidates_for_session(session: Session, session_uid: UUID) -> list[dict]:
    revision = latest_revision(session, session_uid)
    if revision is None or revision.deleted:
        return []
    day = revision.local_date
    days = [day - timedelta(days=1), day, day + timedelta(days=1)]
    first, last = days[0], days[-1] + timedelta(days=1)
    plans = [_matching_plan(plan) for plan in sessions_at_head(session, first, last)]
    runs = _matching_runs(session, first, last)
    strong = session.scalars(
        select(StrongWorkoutRow).where(
            StrongWorkoutRow.local_date >= days[0],
            StrongWorkoutRow.local_date <= days[-1],
            StrongWorkoutRow.resolution_state == "resolved",
        )
    ).all()
    runs += [{"subject_key": f"strong:{r.id}", "local_date": r.local_date, "kind": "strength"} for r in strong]
    manual = session.scalars(
        select(ManualSession).where(
            ManualSession.date >= days[0],
            ManualSession.date <= days[-1],
            ManualSession.kind == "strength",
            ManualSession.linked_activity_id.is_(None),
        )
    ).all()
    runs += [{"subject_key": f"manual:{r.id}", "local_date": r.date, "kind": "strength"} for r in manual]
    completions = [_completion_dict(c) for c in session.scalars(select(SessionCompletion)).all()]
    result = plan_matches(days, plans, runs, completions)
    return result["candidates"].get(str(session_uid), [])
