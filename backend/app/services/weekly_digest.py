"""Weekly planned-versus-done digest. Read-only; one loader serves the API and the coach."""

from __future__ import annotations

import math
from collections import Counter
from datetime import date, timedelta
from typing import Literal, get_args

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.calendar_models import SessionCompletion
from app.db import global_read_lock
from app.domain.calendar_structure import StructureError, expand_structure
from app.domain.local_time import date_in_zone
from app.domain.session_class import HARD_CLASSES, classify
from app.errors import fail
from app.metric_models import MetricResult
from app.metrics import intervals as interval_metric
from app.metrics import planned_actual
from app.metrics.contract import RunFact
from app.metrics.engine import activities_coverage_complete, current_results, load_runs
from app.models import Activity, ManualSession
from app.read.calendar import head_version, latest_revisions
from app.services import calendar
from app.services.timezone import athlete_tz
from app.services.weekly_projection import planned_distance, recent_pace_mps
from app.strong_models import StrongWorkoutRow

DIGEST_SCHEMA = "weekly_digest.v1"
Outcome = Literal["completed", "modified", "partial", "moved", "missed", "recorded", "not_recorded", "planned"]
OUTCOMES: tuple[Outcome, ...] = get_args(Outcome)
DONE_OUTCOMES = frozenset({"completed", "modified", "partial", "moved", "recorded"})
NOT_DONE_OUTCOMES = frozenset({"missed", "not_recorded"})
HEADLINE_KINDS = ("run", "strength", "cross")
REPORTED_KINDS = ("run", "strength", "cross", "mobility")
KEY_CLASSES = HARD_CLASSES
PACE_WINDOW_DAYS = 28
_DAY = timedelta(days=1)
_STATUS_OUTCOME: dict[str, Outcome] = {
    "completed_as_planned": "completed",
    "completed_modified": "modified",
    "partial": "partial",
    "moved": "moved",
    "skipped": "missed",
}
_SUBJECT_FIELDS = (
    ("activity_id", "activity"),
    ("strong_workout_id", "strong_workout"),
    ("manual_session_id", "manual_session"),
)


def week_bounds(day: date) -> tuple[date, date]:
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def session_outcome(local_date: date, completion: dict | None, today: date) -> Outcome:
    status = completion.get("status") if completion else None
    if status in _STATUS_OUTCOME:
        return _STATUS_OUTCOME[status]
    if completion and any(completion.get(field) for field, _ in _SUBJECT_FIELDS):
        return "recorded"
    return "not_recorded" if local_date < today else "planned"


def _amount(value: object, *, positive: bool = False) -> float | None:
    ok = (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and (value > 0 if positive else value >= 0)
    )
    return float(value) if ok else None  # type: ignore[arg-type]


def planned_duration_s(row: dict) -> float | None:
    direct = _amount(row.get("planned_duration_s"), positive=True)
    if direct is not None:
        return direct
    if not row.get("structure"):
        return None
    try:
        steps = expand_structure(row["structure"])
    except StructureError:
        return None
    if any(step["duration_type"] != "time" for step in steps):
        return None
    return float(sum(step["duration_value"] for step in steps))


def _execution(assessment: dict | None, interval: dict | None) -> dict:
    interval = interval or {}
    count = lambda v: v if isinstance(v, int) and not isinstance(v, bool) else None  # noqa: E731
    reps = {"reps_planned": count(interval.get("n_planned")), "reps_completed": count(interval.get("n_completed"))}
    if assessment is None:
        return {
            "assessment_status": None,
            "reason_codes": ["ASSESSMENT_MISSING"],
            "quality_flags": [],
            "components": [],
            **reps,
        }
    status = assessment.get("status")
    components = (assessment.get("value") or {}).get("components") or []
    return {
        "assessment_status": status if status in ("available", "partial", "missing") else "missing",
        "reason_codes": list(assessment.get("reason_codes") or []),
        "quality_flags": list(assessment.get("quality_flags") or []),
        "components": [{"name": c["name"], "value": c.get("value"), "status": c["status"]} for c in components],
        **reps,
    }


def assemble_week(
    *,
    week_start: date,
    today: date,
    timezone: str,
    calendar_version: int,
    sessions: list[dict],
    removed: list[dict],
    completions: dict[str, dict],
    runs: list[dict],
    lifts: list[dict],
    manuals: list[dict],
    assessments: dict[str, dict],
    intervals: dict[str, dict],
    pace_mps: float | None,
    activity_coverage_complete: bool,
) -> dict:
    week_end = week_start + timedelta(days=6)
    today_s = today.isoformat()
    subjects: dict[tuple[str, str], dict] = {}
    for run in runs:
        subjects[("activity", str(run["activity_id"]))] = {
            "local_date": run["local_date"],
            "kind": "run",
            "duration_s": _amount(run.get("timer_s")),
            "distance_m": _amount(run.get("distance_m")),
            "linked": False,
        }
    for lift in lifts:
        subjects[("strong_workout", str(lift["id"]))] = {
            "local_date": lift["local_date"],
            "kind": "strength",
            "duration_s": _amount(lift.get("duration_s")),
            "distance_m": None,
            "linked": False,
        }
    for manual in manuals:
        subjects[("manual_session", str(manual["id"]))] = {
            "local_date": manual["date"],
            "kind": manual["kind"],
            "duration_s": _amount(manual.get("duration_s")),
            "distance_m": None,
            "linked": bool(manual.get("linked_activity_id")),
        }
    head_uids = {str(s["session_uid"]) for s in sessions}
    referenced = {
        (subject, str(c[field]))
        for uid, c in completions.items()
        if uid in head_uids
        for field, subject in _SUBJECT_FIELDS
        if c.get(field)
    }

    rows = []
    for s in sorted(
        (s for s in sessions if s["kind"] != "rest"), key=lambda s: (s["local_date"], s["slot"], str(s["session_uid"]))
    ):
        uid, completion = str(s["session_uid"]), completions.get(str(s["session_uid"]))
        cls = classify(s["kind"], s.get("recipe_id"), s.get("intent"))
        ref = next(
            (
                (subject, str(completion[field]))
                for field, subject in _SUBJECT_FIELDS
                if completion and completion.get(field)
            ),
            None,
        )
        found = subjects.get(ref) if ref else None
        distance, estimated = planned_distance(s, pace_mps) if s["kind"] == "run" else (None, False)
        key = cls in KEY_CLASSES
        rows.append(
            {
                "session_uid": uid,
                "local_date": s["local_date"].isoformat(),
                "slot": s["slot"],
                "kind": s["kind"],
                "class": cls,
                "recipe_id": s.get("recipe_id"),
                "custom": bool(s.get("custom")),
                "intent": s.get("intent"),
                "key": key,
                "changed": s["revision"] > 1,
                "outcome": session_outcome(s["local_date"], completion, today),
                "modification_reason": completion.get("modification_reason") if completion else None,
                "planned_duration_s": planned_duration_s(s),
                "planned_distance_m": distance,
                "planned_distance_estimated": estimated,
                "actual": {
                    "subject": ref[0],
                    "id": ref[1],
                    "local_date": found["local_date"].isoformat(),
                    "duration_s": found["duration_s"],
                    "distance_m": found["distance_m"],
                }
                if ref and found
                else None,
                "execution": _execution(assessments.get(uid), intervals.get(ref[1]) if ref[0] == "activity" else None)
                if key and ref
                else None,
            }
        )

    in_week = [
        (ref, sub)
        for ref, sub in subjects.items()
        if week_start <= sub["local_date"] <= week_end and sub["kind"] != "mobility" and not sub["linked"]
    ]
    unplanned = sorted(
        (
            {
                "subject": ref[0],
                "id": ref[1],
                "local_date": sub["local_date"].isoformat(),
                "kind": sub["kind"],
                "duration_s": sub["duration_s"],
                "distance_m": sub["distance_m"],
            }
            for ref, sub in in_week
            if ref not in referenced
        ),
        key=lambda u: (u["local_date"], u["kind"], u["id"]),
    )
    headline = [r for r in rows if r["kind"] in HEADLINE_KINDS]
    due = lambda r: r["local_date"] <= today_s  # noqa: E731
    counts = lambda rs: {  # noqa: E731
        "planned": len(rs),
        "planned_to_date": sum(map(due, rs)),
        "done": sum(r["outcome"] in DONE_OUTCOMES for r in rs),
    }
    by_outcome = lambda rs: {o: Counter(r["outcome"] for r in rs).get(o, 0) for o in OUTCOMES}  # noqa: E731
    total = lambda xs: round(sum(xs), 1)  # noqa: E731
    run_rows = [r for r in headline if r["kind"] == "run"]
    self_reported = [
        r
        for r in headline
        if r["outcome"] == "completed" and completions[r["session_uid"]].get("match_method") == "user_marked"
    ]
    actual_runs = [sub for _, sub in in_week if sub["kind"] == "run"]
    key_rows = [r for r in rows if r["key"]]
    removed_rows = sorted(
        (
            {"session_uid": str(x["session_uid"]), "local_date": x["local_date"].isoformat(), "kind": x["kind"]}
            for x in removed
            if x["kind"] != "rest"
        ),
        key=lambda x: (x["local_date"], x["session_uid"]),
    )
    return {
        "schema": DIGEST_SCHEMA,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "today": today_s,
        "days_elapsed": max(0, min(7, (today - week_start).days + 1)),
        "timezone": timezone,
        "calendar_version": calendar_version,
        "plan_available": calendar_version > 0,
        "activity_coverage_complete": activity_coverage_complete,
        "totals": {
            "sessions": {
                **counts(headline),
                "by_outcome": by_outcome(headline),
                "removed": len(removed_rows),
                "unplanned": len(unplanned),
            },
            "by_kind": {k: counts([r for r in rows if r["kind"] == k]) for k in REPORTED_KINDS},
            "time": {
                "planned_s": total(r["planned_duration_s"] or 0 for r in headline),
                "planned_to_date_s": total(r["planned_duration_s"] or 0 for r in headline if due(r)),
                "planned_unknown": sum(r["planned_duration_s"] is None for r in headline),
                "actual_s": total(sub["duration_s"] or 0 for _, sub in in_week),
                "actual_unknown": sum(sub["duration_s"] is None for _, sub in in_week) + len(self_reported),
                "unplanned_s": total(u["duration_s"] or 0 for u in unplanned),
            },
            "run_distance": {
                "planned_m": total(r["planned_distance_m"] or 0 for r in run_rows),
                "planned_to_date_m": total(r["planned_distance_m"] or 0 for r in run_rows if due(r)),
                "planned_estimated": sum(r["planned_distance_estimated"] for r in run_rows),
                "planned_unknown": sum(r["planned_distance_m"] is None for r in run_rows),
                "actual_m": total(sub["distance_m"] or 0 for sub in actual_runs),
                "actual_unknown": sum(sub["distance_m"] is None for sub in actual_runs)
                + sum(r["kind"] == "run" for r in self_reported),
            },
            "key_sessions": {**counts(key_rows), "by_outcome": by_outcome(key_rows)},
        },
        "sessions": rows,
        "unplanned": unplanned,
        "removed": removed_rows,
    }


def _run_fact(run: RunFact) -> dict:
    return {
        "activity_id": run.activity_id,
        "local_date": run.local_date,
        "timer_s": run.timer_s,
        "distance_m": run.distance_m,
    }


def _rows(result: dict[str, MetricResult]) -> dict[str, dict]:
    return {
        key: {
            "status": row.status,
            "reason_codes": list(row.reason_codes or []),
            "quality_flags": list(row.quality_flags or []),
            "value": row.value,
        }
        for key, row in result.items()
    }


def load_week(session: Session, week_start: date, *, today: date) -> dict:
    week_end = week_start + timedelta(days=6)
    as_of = min(week_end, today)
    timezone = athlete_tz(session)
    head = head_version(session)
    latest = [row for row in latest_revisions(session, head).values() if week_start <= row.local_date <= week_end]
    sessions = [calendar.row_data(row) for row in latest if not row.deleted]
    removed = [
        {"session_uid": row.session_uid, "local_date": row.local_date, "kind": row.kind}
        for row in latest
        if row.deleted
    ]
    head_uids = {row["session_uid"] for row in sessions}

    runs = {run.activity_id: _run_fact(run) for run in load_runs(session, week_start, week_end + _DAY)}
    lift_fields = select(StrongWorkoutRow.id, StrongWorkoutRow.local_date, StrongWorkoutRow.duration_s).where(
        StrongWorkoutRow.resolution_state == "resolved"
    )
    lifts = {
        row.id: dict(row._mapping)
        for row in session.execute(lift_fields.where(StrongWorkoutRow.local_date.between(week_start, week_end)))
    }
    manual_fields = select(
        ManualSession.id,
        ManualSession.date,
        ManualSession.kind,
        ManualSession.duration_s,
        ManualSession.linked_activity_id,
    )
    manuals = {
        row.id: dict(row._mapping)
        for row in session.execute(manual_fields.where(ManualSession.date.between(week_start, week_end)))
    }

    completion = SessionCompletion
    kept = session.execute(
        select(
            completion.session_uid,
            completion.status,
            completion.match_method,
            completion.activity_id,
            completion.strong_workout_id,
            completion.manual_session_id,
            completion.modification_reason,
        ).where(
            or_(
                completion.session_uid.in_(head_uids),
                and_(
                    completion.status == "extra",
                    or_(
                        completion.activity_id.in_(runs),
                        completion.strong_workout_id.in_(lifts),
                        completion.manual_session_id.in_(manuals),
                    ),
                ),
            )
        )
    ).all()
    for row in kept:
        if row.session_uid not in head_uids:
            continue
        if row.activity_id is not None and row.activity_id not in runs:
            start_at = session.scalar(select(Activity.start_at).where(Activity.id == row.activity_id))
            if start_at is not None:
                day = date_in_zone(start_at, timezone)
                for run in load_runs(session, day, day + _DAY):
                    if run.activity_id == row.activity_id:
                        runs[run.activity_id] = _run_fact(run)
        if row.strong_workout_id is not None and row.strong_workout_id not in lifts:
            lift = session.execute(lift_fields.where(StrongWorkoutRow.id == row.strong_workout_id)).one_or_none()
            if lift is not None:
                lifts[lift.id] = dict(lift._mapping)
        if row.manual_session_id is not None and row.manual_session_id not in manuals:
            manual = session.execute(manual_fields.where(ManualSession.id == row.manual_session_id)).one_or_none()
            if manual is not None:
                manuals[manual.id] = dict(manual._mapping)

    completions = {
        str(row.session_uid): {
            "status": row.status,
            "match_method": row.match_method,
            "activity_id": row.activity_id,
            "strong_workout_id": row.strong_workout_id,
            "manual_session_id": row.manual_session_id,
            "modification_reason": row.modification_reason,
        }
        for row in kept
    }
    key_uids = [
        str(row["session_uid"])
        for row in sessions
        if classify(row["kind"], row.get("recipe_id"), row.get("intent")) in KEY_CLASSES
    ]
    key_activity_ids = [
        str(completions[uid]["activity_id"])
        for uid in key_uids
        if uid in completions and completions[uid]["activity_id"]
    ]
    pace_runs = load_runs(session, as_of - timedelta(days=PACE_WINDOW_DAYS - 1), as_of + _DAY)
    pace, _ = recent_pace_mps(pace_runs, as_of, PACE_WINDOW_DAYS)
    return assemble_week(
        week_start=week_start,
        today=today,
        timezone=timezone.key,
        calendar_version=head,
        sessions=sessions,
        removed=removed,
        completions=completions,
        runs=list(runs.values()),
        lifts=list(lifts.values()),
        manuals=list(manuals.values()),
        assessments=_rows(current_results(session, planned_actual.METRIC_ID, key_uids)),
        intervals={
            key: row.value
            for key, row in current_results(session, interval_metric.METRIC_ID, key_activity_ids).items()
            if isinstance(row.value, dict)
        },
        pace_mps=pace,
        activity_coverage_complete=activities_coverage_complete(session, week_start, as_of + _DAY),
    )


def weekly_digest(session: Session, week_start: date | None) -> dict:
    if week_start is not None and week_start.weekday() != 0:
        fail("invalid_week_start", "Week start must be a Monday")
    global_read_lock(session)
    today = calendar.calendar_today(session)
    return load_week(session, week_start or week_bounds(today)[0], today=today)
