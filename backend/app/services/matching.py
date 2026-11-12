"""Deterministic plan to actual matching; callers own the transaction."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.metrics.engine import load_runs
from app.models import Activity, AppState, ManualSession
from app.services.timezone import athlete_tz
from app.strong_models import StrongWorkoutRow

EXTRA_NAMESPACE = UUID("e35269d4-74b0-53bf-8a74-f01b3ef69218")
PROTECTED_METHODS = {"explicit", "user_marked", "confirmed_move"}
ELIGIBLE_KINDS = {"run", "strength"}


def sessions_at_head(session: Session, start: date, end_excl: date) -> list[CalendarSessionRevision]:
    state = session.get(AppState, 1)
    head = state.calendar_head_version if state else 0
    if head == 0:
        return []
    rows = session.scalars(select(CalendarSessionRevision)
        .where(CalendarSessionRevision.calendar_version_number <= head)
        .order_by(CalendarSessionRevision.session_uid,
                  desc(CalendarSessionRevision.calendar_version_number),
                  desc(CalendarSessionRevision.revision))
        .distinct(CalendarSessionRevision.session_uid)).all()
    return sorted((r for r in rows if not r.deleted and start <= r.local_date < end_excl),
                  key=lambda r: (r.local_date, r.kind, r.slot, str(r.session_uid)))


def _subject_key(row: dict) -> str | None:
    if row.get("subject_key"):
        return str(row["subject_key"])
    for field, prefix in (("activity_id", ""), ("strong_workout_id", "strong:"),
                          ("manual_session_id", "manual:")):
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


def plan_matches(days: list[date], planned: list[dict], runs: list[dict], completions: list[dict]) -> dict:
    """Return only unambiguous links; candidate lists explain every unresolved plan."""
    day_scope = set(days)
    plans = [p for p in planned if p.get("kind") in ELIGIBLE_KINDS and not p.get("deleted")
             and not p.get("skipped") and _day(p["local_date"]) in day_scope]
    plans.sort(key=lambda p: (_day(p["local_date"]), p["kind"], str(p["session_uid"])))
    subjects = [r for r in runs if _subject_key(r) and _kind(r) in ELIGIBLE_KINDS
                and _day(r["local_date"]) in day_scope and r.get("resolution_state", "resolved") == "resolved"]
    subjects.sort(key=lambda r: (_day(r["local_date"]), _kind(r), _subject_key(r) or ""))
    plan_by_uid = {str(p["session_uid"]): p for p in plans}
    subject_by_key = {_subject_key(r): r for r in subjects}
    protected_uids = set()
    protected_subjects = set()
    auto_uids = set()
    delete_auto = set()
    existing_extra_subjects = set()
    for completion in completions:
        uid = str(completion["session_uid"])
        key = _subject_key(completion)
        method = completion.get("match_method")
        if method in PROTECTED_METHODS or completion.get("status") == "skipped":
            protected_uids.add(uid)
            if key:
                protected_subjects.add(key)
        elif method == "auto_same_day":
            plan, subject = plan_by_uid.get(uid), subject_by_key.get(key)
            if (plan is not None and subject is not None and key is not None
                    and _day(plan["local_date"]) == _day(subject["local_date"])
                    and plan["kind"] == _kind(subject)):
                auto_uids.add(uid)
                protected_subjects.add(key)
            else:
                delete_auto.add(uid)
        elif completion.get("status") == "extra" and key:
            existing_extra_subjects.add(key)
    available_plans = [p for p in plans if str(p["session_uid"]) not in protected_uids | auto_uids]
    available_subjects = [r for r in subjects if _subject_key(r) not in protected_subjects]
    links: list[dict] = []
    candidates: dict[str, list[dict]] = {}
    for day in sorted(day_scope):
        for kind in ("run", "strength"):
            day_plans = [p for p in available_plans if _day(p["local_date"]) == day and p["kind"] == kind]
            day_subjects = [r for r in available_subjects if _day(r["local_date"]) == day and _kind(r) == kind]
            if len(day_plans) == len(day_subjects) == 1:
                links.append({"session_uid": str(day_plans[0]["session_uid"]),
                              "subject_key": _subject_key(day_subjects[0]), "match_method": "auto_same_day"})
    linked_subjects = {link["subject_key"] for link in links}
    for day in sorted(day_scope):
        for kind in ("run", "strength"):
            day_plans = [p for p in available_plans if _day(p["local_date"]) == day and p["kind"] == kind]
            day_subjects = [r for r in available_subjects if _day(r["local_date"]) == day and _kind(r) == kind]
            if len(day_plans) == len(day_subjects) == 1:
                continue
            day_subjects = [r for r in day_subjects if _subject_key(r) not in linked_subjects]
            for plan in day_plans:
                uid = str(plan["session_uid"])
                same = [{"subject_key": _subject_key(r), "local_date": day.isoformat(),
                         "kind": kind, "reason": "AMBIGUOUS_MATCH" if len(day_plans) > 1 or len(day_subjects) > 1
                         else "SAME_DAY_CANDIDATE"} for r in day_subjects]
                moves = []
                if kind == "run" and not same:
                    moves = [{"subject_key": _subject_key(r), "local_date": _day(r["local_date"]).isoformat(),
                              "kind": kind, "reason": "MOVE_CANDIDATE"} for r in available_subjects
                             if _kind(r) == "run" and _subject_key(r) not in linked_subjects
                             and abs((_day(r["local_date"]) - day).days) == 1]
                candidates[uid] = sorted(same + moves, key=lambda c: (c["local_date"], c["kind"], c["subject_key"]))
    extras = []
    for subject in available_subjects:
        key = _subject_key(subject)
        if key is None or key in linked_subjects:
            continue
        day = _day(subject["local_date"])
        if any(p["kind"] == _kind(subject) and abs((_day(p["local_date"]) - day).days) <= 1
               for p in available_plans):
            continue
        extras.append({"session_uid": str(uuid.uuid5(EXTRA_NAMESPACE, f"extra:{key}")),
                       "subject_key": key, "match_method": "none"})
    extras.sort(key=lambda e: e["subject_key"])
    # Existing extra rows may need replacement once a planned match becomes possible.
    delete_extra = sorted(existing_extra_subjects - {e["subject_key"] for e in extras})
    return {"delete_auto_session_uids": sorted(delete_auto), "delete_extra_subject_keys": delete_extra,
            "links": links, "extras": extras, "candidates": candidates}


def _completion_dict(row: SessionCompletion) -> dict:
    return {"session_uid": row.session_uid, "activity_id": row.activity_id,
            "strong_workout_id": row.strong_workout_id, "manual_session_id": row.manual_session_id,
            "status": row.status, "match_method": row.match_method}


def _subject_columns(key: str) -> dict:
    if key.startswith("strong:"):
        return {"strong_workout_id": UUID(key[7:])}
    if key.startswith("manual:"):
        return {"manual_session_id": UUID(key[7:])}
    return {"activity_id": UUID(key)}


def rematch_dates(session: Session, dates: set[date]) -> set[UUID]:
    if not dates:
        return set()
    now = session.info.get("metrics_now") or datetime.now(UTC)
    state = session.get(AppState, 1)
    if state is None or state.calendar_head_version == 0:
        return set()
    origin = session.scalar(select(func.min(CalendarSessionRevision.local_date)).where(
        CalendarSessionRevision.calendar_version_number <= state.calendar_head_version))
    if origin is None:
        return set()
    days = sorted({d + timedelta(days=offset) for d in dates for offset in (-1, 0, 1) if d + timedelta(days=offset) >= origin})
    if not days:
        return set()
    first, last = days[0], days[-1] + timedelta(days=1)
    plans = sessions_at_head(session, first, last)
    planned = [{"session_uid": p.session_uid, "local_date": p.local_date, "kind": p.kind}
               for p in plans]
    runs = [{"subject_key": str(r.activity_id), "local_date": r.local_date, "kind": "run"}
            for r in load_runs(session, first, last)]
    strong = session.scalars(select(StrongWorkoutRow).where(StrongWorkoutRow.local_date >= first,
                            StrongWorkoutRow.local_date < last,
                            StrongWorkoutRow.resolution_state == "resolved")).all()
    runs += [{"subject_key": f"strong:{r.id}", "local_date": r.local_date, "kind": "strength"} for r in strong]
    manual = session.scalars(select(ManualSession).where(ManualSession.date >= first,
                            ManualSession.date < last, ManualSession.kind == "strength",
                            ManualSession.linked_activity_id.is_(None))).all()
    runs += [{"subject_key": f"manual:{r.id}", "local_date": r.date, "kind": "strength"} for r in manual]
    existing = session.scalars(select(SessionCompletion)).all()
    scoped_uids = {str(p["session_uid"]) for p in planned if p["local_date"] in days}
    historical = session.scalars(select(CalendarSessionRevision.session_uid).where(
        CalendarSessionRevision.local_date.in_(days),
        CalendarSessionRevision.calendar_version_number <= state.calendar_head_version)).all()
    scoped_uids.update(str(uid) for uid in historical)
    scoped_subjects = {str(r["subject_key"]) for r in runs if r["local_date"] in days}
    zone = athlete_tz(session)
    for completion in existing:
        subject_day = None
        if completion.activity_id:
            raw = session.get(Activity, completion.activity_id)
            subject_day = raw.start_at.astimezone(zone).date() if raw else None
        elif completion.strong_workout_id:
            raw_strong = session.get(StrongWorkoutRow, completion.strong_workout_id)
            subject_day = raw_strong.local_date if raw_strong else None
        elif completion.manual_session_id:
            raw_manual = session.get(ManualSession, completion.manual_session_id)
            subject_day = raw_manual.date if raw_manual else None
        if subject_day in days:
            key = _subject_key(_completion_dict(completion))
            if key:
                scoped_subjects.add(key)
    scoped_existing = [c for c in existing if str(c.session_uid) in scoped_uids
                       or _subject_key(_completion_dict(c)) in scoped_subjects]
    result = plan_matches(days, planned, runs, [_completion_dict(c) for c in scoped_existing])
    affected: set[UUID] = set()
    by_uid = {str(c.session_uid): c for c in scoped_existing}
    deleted_uids: set[str] = set()
    for uid in result["delete_auto_session_uids"]:
        old = by_uid.get(uid)
        if old is not None and old.match_method == "auto_same_day":
            affected.add(old.session_uid)
            session.delete(old)
            deleted_uids.add(uid)
    for key in result["delete_extra_subject_keys"]:
        for old in scoped_existing:
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
            if old.match_method in PROTECTED_METHODS or old.status == "skipped":
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
        row = SessionCompletion(session_uid=uid, status="extra" if item in result["extras"] else "unknown",
                                match_method=item["match_method"], updated_at=now,
                                **_subject_columns(item["subject_key"]))
        session.add(row)
        affected.add(uid)
    return affected


def candidates_for_session(session: Session, session_uid: UUID) -> list[dict]:
    state = session.get(AppState, 1)
    if state is None or state.calendar_head_version == 0:
        return []
    revision = session.scalar(select(CalendarSessionRevision).where(
        CalendarSessionRevision.session_uid == session_uid,
        CalendarSessionRevision.calendar_version_number <= state.calendar_head_version)
        .order_by(CalendarSessionRevision.calendar_version_number.desc(), CalendarSessionRevision.revision.desc()).limit(1))
    if revision is None or revision.deleted:
        return []
    day = revision.local_date
    days = [day - timedelta(days=1), day, day + timedelta(days=1)]
    plans = [{"session_uid": p.session_uid, "local_date": p.local_date, "kind": p.kind}
             for p in sessions_at_head(session, days[0], days[-1] + timedelta(days=1))]
    runs = [{"subject_key": str(r.activity_id), "local_date": r.local_date, "kind": "run"}
            for r in load_runs(session, days[0], days[-1] + timedelta(days=1))]
    strong = session.scalars(select(StrongWorkoutRow).where(StrongWorkoutRow.local_date >= days[0],
                            StrongWorkoutRow.local_date <= days[-1],
                            StrongWorkoutRow.resolution_state == "resolved")).all()
    runs += [{"subject_key": f"strong:{r.id}", "local_date": r.local_date, "kind": "strength"} for r in strong]
    manual = session.scalars(select(ManualSession).where(ManualSession.date >= days[0],
                            ManualSession.date <= days[-1], ManualSession.kind == "strength",
                            ManualSession.linked_activity_id.is_(None))).all()
    runs += [{"subject_key": f"manual:{r.id}", "local_date": r.date, "kind": "strength"} for r in manual]
    completions = [_completion_dict(c) for c in session.scalars(select(SessionCompletion)).all()]
    result = plan_matches(days, plans, runs, completions)
    return result["candidates"].get(str(session_uid), [])
