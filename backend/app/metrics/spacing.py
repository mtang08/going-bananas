"""Time ranges between observed or planned hard exposures."""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.domain.analytics import utc_date_bounds
from app.metric_models import MetricResult as MetricResultRow
from app.metrics.contract import MetricResultData, Status, completion_association_hash, config_hash, sha256_json
from app.metrics.engine import load_runs, register
from app.models import Activity, AppState, ManualSession, RawObject, SourceRecord
from app.planning_models import StrengthRoutineSlot
from app.services.timezone import athlete_tz
from app.strong_models import StrongWorkoutRow

METRIC_ID = "hard_session_spacing"
METHOD_VERSION = "v1"
WINDOW_DAYS = (14,)
DEPENDS_ON = ("long_run_exposure",)
CONFIG = {"quality_recipes": ["REC003", "REC004", "REC005", "REC006", "REC008", "REC009"],
          "long_recipe": "REC002", "lower_body_cost": ["moderate", "high"],
          "range_rule": "interval_subtraction.v1"}
HARD_CLASSES = ("quality", "long", "lower_body_strength")


def _gap(previous: dict, following: dict) -> dict:
    low = (following["start_low"] - previous["end_high"]).total_seconds() / 3600
    high = (following["start_high"] - previous["end_low"]).total_seconds() / 3600
    exact = (previous["end_low"] == previous["end_high"]
             and following["start_low"] == following["start_high"])
    return {"low": round(low, 1), "high": round(high, 1),
            "confidence": "high" if exact else "low"}


def spacing_outcome(exposures: list[dict], as_of: date, tz: ZoneInfo) -> dict:
    first, last = as_of - timedelta(days=7), as_of + timedelta(days=6)
    by_subject: dict[str, dict] = {}
    for item in exposures:
        if not item["classes"]:
            continue
        key = item["subject_key"]
        if key in by_subject:
            by_subject[key] = {**by_subject[key], "classes": sorted(set(by_subject[key]["classes"]) | set(item["classes"]))}
        else:
            by_subject[key] = {**item, "classes": sorted(set(item["classes"]))}
    ordered = sorted(by_subject.values(), key=lambda e: (e["start_low"], e["subject_key"]))
    current = [e for e in ordered if first <= e["local_date"] <= last]
    sessions = []
    for exposure in current:
        index = ordered.index(exposure)
        since: dict[str, dict] = {}
        until: dict[str, dict] = {}
        for cls in HARD_CLASSES:
            prior = next((e for e in reversed(ordered[:index]) if cls in e["classes"] and e is not exposure), None)
            after = next((e for e in ordered[index + 1:] if cls in e["classes"] and e is not exposure), None)
            if prior:
                since[cls] = _gap(prior, exposure)
            if after:
                until[cls] = _gap(exposure, after)
        sessions.append({"session_uid": exposure.get("session_uid"), "subject_key": exposure["subject_key"],
                         "local_date": exposure["local_date"].isoformat(), "hours_since": since,
                         "hours_until": until})
    sequence = [{"subject_key": e["subject_key"], "classes": e["classes"],
                 "local_date": e["local_date"].isoformat(), "session_uid": e.get("session_uid"),
                 "activity_id": e.get("activity_id"), "source": e.get("source"),
                 "start_low": e["start_low"].isoformat(), "start_high": e["start_high"].isoformat(),
                 "end_low": e["end_low"].isoformat(), "end_high": e["end_high"].isoformat()}
                for e in current]
    gaps = []
    for left, right in zip(ordered, ordered[1:]):
        if left not in current and right not in current:
            continue
        gap = _gap(left, right)
        for from_class in HARD_CLASSES:
            if from_class not in left["classes"]:
                continue
            for to_class in HARD_CLASSES:
                if to_class in right["classes"]:
                    gaps.append({"from_class": from_class, "to_class": to_class,
                                 "from_date": left["local_date"].isoformat(),
                                 "to_date": right["local_date"].isoformat(),
                                 "hours_min": gap["low"], "hours_max": gap["high"],
                                 "confidence": gap["confidence"]})
    return {"status": "available", "quality_status": None,
            "value": {"sessions": sessions, "sequence": sequence, "gaps": gaps},
            "reason_codes": [], "quality_flags": []}


def _day_range(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    return utc_date_bounds(day, day, tz.key)


def _planned_exposure(row: CalendarSessionRevision, classes: list[str], tz: ZoneInfo) -> dict:
    start, end = _day_range(row.local_date, tz)
    return {"subject_key": str(row.session_uid), "classes": classes, "local_date": row.local_date,
            "session_uid": str(row.session_uid), "activity_id": None, "source": "plan",
            "start_low": start, "start_high": end, "end_low": start, "end_high": end}


def _actual_exposure(subject_key: str, day: date, start: datetime | None, end: datetime | None,
                     classes: list[str], tz: ZoneInfo, session_uid: UUID | None,
                     activity_id: UUID | None, source: str) -> dict:
    day_start, next_start = _day_range(day, tz)
    start_low = start.astimezone(UTC) if start else day_start
    start_high = start_low if start else next_start
    end_low = end.astimezone(UTC) if end else start_low
    end_high = end.astimezone(UTC) if end else next_start
    return {"subject_key": subject_key, "classes": classes, "local_date": day,
            "session_uid": str(session_uid) if session_uid else None,
            "activity_id": str(activity_id) if activity_id else None, "source": source,
            "start_low": start_low, "start_high": start_high, "end_low": end_low, "end_high": end_high}


def _plan_classes(session: Session, row: CalendarSessionRevision) -> list[str]:
    if row.kind == "run":
        if row.recipe_id in CONFIG["quality_recipes"]:
            return ["quality"]
        if row.recipe_id == "REC002":
            return ["long"]
    if row.kind == "strength" and row.strength_slot_id:
        slot = session.get(StrengthRoutineSlot, row.strength_slot_id)
        if slot and slot.lower_body_cost in CONFIG["lower_body_cost"]:
            return ["lower_body_strength"]
    return []


def _plan_ref(session: Session, row: CalendarSessionRevision,
              completion: SessionCompletion | None = None) -> dict:
    slot = session.get(StrengthRoutineSlot, row.strength_slot_id) if row.strength_slot_id else None
    return {"plan_revision_id": str(row.id), "revision": row.revision,
            "calendar_version": row.calendar_version_number,
            "structure_hash": sha256_json(row.structure), "recipe_id": row.recipe_id,
            "session_uid": str(row.session_uid),
            "completion_association_hash": completion_association_hash(completion) if completion else None,
            "strength_slot": {"id": str(slot.id), "version": slot.version,
                              "lower_body_cost": slot.lower_body_cost, "active": slot.active}
            if slot else None}


@register(METRIC_ID, METHOD_VERSION, DEPENDS_ON)
def compute(session: Session, subject_key: str) -> list[MetricResultData]:
    match = re.fullmatch(r"w14:(\d{4}-\d{2}-\d{2})", subject_key)
    if match is None:
        raise ValueError("invalid_subject_key")
    try:
        as_of = date.fromisoformat(match[1])
    except ValueError as exc:
        raise ValueError("invalid_subject_key") from exc
    tz = athlete_tz(session)
    state = session.get(AppState, 1)
    head = state.calendar_head_version if state else 0
    plans = (session.scalars(select(CalendarSessionRevision)
             .where(CalendarSessionRevision.calendar_version_number <= head)
             .order_by(CalendarSessionRevision.session_uid,
                       desc(CalendarSessionRevision.calendar_version_number),
                       desc(CalendarSessionRevision.revision))
             .distinct(CalendarSessionRevision.session_uid)).all() if head else [])
    plans = [p for p in plans if not p.deleted and p.kind in ("run", "strength")]
    completions = list(session.scalars(select(SessionCompletion)).all())
    linked = {c.session_uid: c for c in completions}
    by_activity = {c.activity_id: c for c in completions if c.activity_id and c.status != "skipped"}
    exposures = []
    source_refs = []
    for plan in plans:
        completion = linked.get(plan.session_uid)
        if completion and completion.status == "skipped":
            continue
        if completion and any((completion.activity_id, completion.strong_workout_id, completion.manual_session_id)):
            continue
        classes = _plan_classes(session, plan)
        if classes:
            exposures.append(_planned_exposure(plan, classes, tz))
            source_refs.append({**_plan_ref(session, plan, completion), "classes": classes})
    # Query all stored history so the nearest earlier/later exposure is not cut off at the display window.
    bounds = session.execute(select(func.min(Activity.start_at), func.max(Activity.start_at)).where(
        Activity.sport.in_(("running", "trail_running", "treadmill_running")))).one()
    runs = (load_runs(session, bounds[0].astimezone(tz).date(),
                      bounds[1].astimezone(tz).date() + timedelta(days=1)) if bounds[0] and bounds[1] else [])
    long_rows = session.scalars(select(MetricResultRow).where(
        MetricResultRow.metric_id == "long_run_exposure", MetricResultRow.method_version == "v1",
        MetricResultRow.is_current.is_(True))).all()
    long_by_id = {r.subject_key: r for r in long_rows}
    for run in runs:
        completion = by_activity.get(run.activity_id)
        linked_plan = next((p for p in plans if completion and p.session_uid == completion.session_uid), None)
        classes = _plan_classes(session, linked_plan) if linked_plan else []
        long_result = long_by_id.get(str(run.activity_id))
        long_value = long_result.value if long_result else None
        is_long = (long_value.get("classification") == "long" if isinstance(long_value, dict)
                   else linked_plan is None and run.workout_label == "long")
        if is_long:
            if "long" not in classes:
                classes.append("long")
        if not classes:
            continue
        exposure = _actual_exposure(str(run.activity_id), run.local_date, run.start_at, run.end_at, classes,
                                    tz, completion.session_uid if completion else None, run.activity_id, "activity")
        exposures.append(exposure)
        source_refs.append({"activity_id": str(run.activity_id), "source_revision": run.source_revision,
                            "source_refs": run.source_refs,
                            "plan": _plan_ref(session, linked_plan, completion) if linked_plan else None,
                            "long_metric_id": str(long_result.id) if long_result else None,
                            "long_dependency_hash": long_result.dependency_hash if long_result else None})
    for completion in completions:
        if completion.status == "skipped":
            continue
        strength_plan = next((p for p in plans if p.session_uid == completion.session_uid), None)
        if strength_plan is None:
            continue
        classes = _plan_classes(session, strength_plan)
        if "lower_body_strength" not in classes:
            continue
        if completion.strong_workout_id:
            strong = session.get(StrongWorkoutRow, completion.strong_workout_id)
            if strong is None or strong.resolution_state != "resolved":
                continue
            try:
                start = datetime.fromisoformat(strong.local_start).replace(tzinfo=tz).astimezone(UTC)
            except ValueError:
                start = None
            end = start + timedelta(seconds=strong.duration_s) if start and strong.duration_s is not None else None
            exposures.append(_actual_exposure(f"strong:{strong.id}", strong.local_date, start, end, classes,
                             tz, completion.session_uid, None, "strong"))
            source_record = session.get(SourceRecord, strong.source_record_id)
            raw_object = session.get(RawObject, strong.raw_object_id)
            source_refs.append({"strong_workout_id": str(strong.id), "payload_hash": strong.payload_hash,
                                "source_record_id": str(strong.source_record_id),
                                "source_payload_hash": source_record.payload_hash if source_record else None,
                                "source_parser_version": source_record.parser_version if source_record else None,
                                "raw_object_id": str(strong.raw_object_id),
                                "raw_sha256": raw_object.sha256 if raw_object else None,
                                "plan": _plan_ref(session, strength_plan, completion)})
        elif completion.manual_session_id:
            manual = session.get(ManualSession, completion.manual_session_id)
            if manual is None or manual.kind != "strength":
                continue
            start = datetime.combine(manual.date, manual.time, tz).astimezone(UTC) if manual.time else None
            end = start + timedelta(seconds=manual.duration_s) if start and manual.duration_s is not None else None
            exposures.append(_actual_exposure(f"manual:{manual.id}", manual.date, start, end, classes,
                             tz, completion.session_uid, None, "manual"))
            source_refs.append({"manual_session_id": str(manual.id), "version": manual.version,
                                "duration_s": manual.duration_s,
                                "plan": _plan_ref(session, strength_plan, completion)})
    outcome = spacing_outcome(exposures, as_of, tz)
    first, last = as_of - timedelta(days=7), as_of + timedelta(days=6)
    start, end = utc_date_bounds(first, last, tz.key)
    source_refs.sort(key=sha256_json)
    refs = {"sources": source_refs, "calendar_head": head,
            "input_hash": sha256_json({"sources": source_refs, "calendar_head": head})}
    return [MetricResultData(METRIC_ID, METHOD_VERSION, "window", subject_key, Status(outcome["status"]),
                             tuple(outcome["reason_codes"]), tuple(outcome["quality_flags"]), refs, (),
                             config_hash(CONFIG), window_start=start, window_end=end, window_label=subject_key,
                             value=outcome["value"], unit=None, timezone=tz.key)]
