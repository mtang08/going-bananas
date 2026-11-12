"""Component level planned versus actual assessment and completion writeback."""
from __future__ import annotations

import math
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.metrics.contract import (
    MetricResultData,
    QualityStatus,
    Status,
    completion_association_hash,
    config_hash,
    sha256_json,
)
from app.metrics.engine import activities_coverage_complete, latest_results, load_runs, metric_source_refs, register
from app.models import Activity, AppState, ManualSession, RawObject, SourceRecord
from app.services.calendar_structure import expand_structure
from app.services.matching import candidates_for_session
from app.services.timezone import athlete_tz
from app.strong_models import StrongWorkoutRow

METRIC_ID = "planned_actual_session"
METHOD_VERSION = "v1"
WINDOW_DAYS: tuple[int, ...] = ()
DEPENDS_ON = ("work_interval_execution",)
CONFIG: dict = {"ratio_met": .9, "ratio_partial": .5, "exceeded": 1.15,
          "step_met": 1, "target_met": .75, "target_partial": .4,
          "precedence": ["skipped", "moved", "extra", "partial", "modified", "as_planned", "unknown"]}
SENSIBLE_REASONS = {"symptom_onset", "fatigue", "illness"}


def component(name: str, actual: float | None, planned: float | None) -> dict:
    if planned is None or not math.isfinite(planned) or planned <= 0:
        return {"name": name, "value": None, "status": "omitted"}
    if actual is None or not math.isfinite(actual) or actual < 0:
        return {"name": name, "value": None, "status": "not_assessable"}
    ratio = actual / planned
    if name == "step_completion_ratio":
        status = "met" if ratio >= CONFIG["step_met"] else "partially_met" if ratio >= CONFIG["ratio_partial"] else "not_met"
    elif name == "target_coverage":
        status = "met" if ratio >= CONFIG["target_met"] else "partially_met" if ratio >= CONFIG["target_partial"] else "not_met"
    else:
        status = ("met" if ratio >= CONFIG["ratio_met"]
                  else "partially_met" if ratio >= CONFIG["ratio_partial"] else "not_met")
    return {"name": name, "value": round(ratio, 3), "status": status}


def _required_structure(plan: dict) -> tuple[bool, bool]:
    structure = plan.get("structure")
    if not structure:
        return False, False
    steps = expand_structure(structure)
    work = [step for step in steps if step["type"] == "work"]
    return bool(work), any((step.get("target") or {}).get("modality") == "speed" for step in work)


def planned_actual_outcome(plan: dict | None, completion: dict | None, activity: dict | None,
                           intervals: dict | None, candidates: list[dict], coverage_complete: bool,
                           as_of: date) -> dict:
    match_method = completion.get("match_method") if completion else None
    prior_status = completion.get("status") if completion else None
    linked = completion is not None and any(completion.get(field) for field in
                                            ("activity_id", "strong_workout_id", "manual_session_id", "subject_key"))
    values = {"overall_status": "unknown", "components": [],
              "certainty": plan.get("certainty") if plan else None,
              "kind": plan.get("kind") if plan else activity.get("kind") if activity else None,
              "candidate_activity_ids": [str(c.get("subject_key") or c.get("activity_id")) for c in candidates],
              "calendar_version": plan.get("calendar_version_number") if plan else None,
              "match_method": match_method or "none"}
    reasons: list[str] = []
    flags: list[str] = []
    if prior_status == "skipped" and match_method in {"explicit", "user_marked", "confirmed_move"}:
        values["overall_status"] = "skipped"
    elif match_method == "confirmed_move" and linked and activity is not None:
        values["overall_status"] = "moved"
    elif prior_status == "extra" and linked and activity is not None:
        values["overall_status"] = "extra"
    elif not linked:
        if plan and plan.get("local_date") and plan["local_date"] > as_of:
            reasons.append("NOT_YET_DUE")
        elif any(c.get("reason") == "AMBIGUOUS_MATCH" for c in candidates):
            reasons.append("AMBIGUOUS_MATCH")
        elif any(c.get("reason") == "MOVE_CANDIDATE" for c in candidates):
            reasons.append("MOVE_CANDIDATE")
        elif not coverage_complete:
            reasons.append("AWAITING_SYNC")
        else:
            reasons.append("NO_ACTIVITY_FOUND")
    else:
        assert completion is not None
        components = []
        if activity is None:
            reasons.append("ACTIVITY_EXCLUDED")
        if plan:
            for name, planned_field, actual_field in (("duration_ratio", "planned_duration_s", "timer_s"),
                                                     ("distance_ratio", "planned_distance_m", "distance_m")):
                item = component(name, activity.get(actual_field) if activity else None, plan.get(planned_field))
                if item["status"] != "omitted":
                    components.append(item)
            need_steps, need_target = _required_structure(plan)
            if need_steps:
                components.append(component("step_completion_ratio", intervals.get("step_completion_ratio")
                                            if intervals else None, 1))
            if need_target:
                components.append(component("target_coverage", intervals.get("target_coverage")
                                            if intervals else None, 1))
        values["components"] = components
        if not components and not reasons:
            reasons.append("INSUFFICIENT_PLAN")
        unknown_component = any(c["status"] == "not_assessable" for c in components)
        if unknown_component and "COMPONENT_NOT_ASSESSABLE" not in reasons:
            reasons.append("COMPONENT_NOT_ASSESSABLE")
        if activity is not None and components:
            by_name = {c["name"]: c for c in components}
            actual_timer = activity.get("timer_s")
            duration_raw = (actual_timer / plan["planned_duration_s"] if plan and
                            isinstance(actual_timer, (int, float)) and math.isfinite(actual_timer)
                            and plan.get("planned_duration_s") and plan["planned_duration_s"] > 0 else None)
            step_raw = intervals.get("step_completion_ratio") if intervals else None
            if (step_raw is not None and step_raw < 1 and duration_raw is not None
                    and duration_raw < CONFIG["ratio_met"]):
                values["overall_status"] = "partial"
            elif (any(c["status"] != "not_assessable" for c in components) and
                  (completion.get("modification_reason") or any(c["status"] in ("partially_met", "not_met")
                                                                for c in components))):
                values["overall_status"] = "completed_modified"
            elif not unknown_component and all(c["status"] == "met" for c in components):
                values["overall_status"] = "completed_as_planned"
            for name, planned_field, actual_field in (("duration_ratio", "planned_duration_s", "timer_s"),
                                                     ("distance_ratio", "planned_distance_m", "distance_m")):
                measurement = activity.get(actual_field)
                if (name in by_name and plan and plan.get(planned_field)
                        and isinstance(measurement, (int, float)) and math.isfinite(measurement)):
                    if measurement / plan[planned_field] > CONFIG["exceeded"]:
                        flags.append("EXCEEDED")
        if completion.get("modification_reason") in SENSIBLE_REASONS:
            flags.append("SENSIBLE_MODIFICATION")
    overall = values["overall_status"]
    flags = list(dict.fromkeys(flags))
    if overall in {"completed_as_planned", "completed_modified", "partial", "moved", "extra", "skipped"}:
        status = "available" if not reasons else "partial"
    else:
        status = "partial" if reasons and linked else "missing"
    outcome = {"status": status, "quality_status": "good" if status == "available" and not flags else
               "limited" if status == "partial" or flags else None,
               "value": values, "reason_codes": reasons, "quality_flags": flags}
    if linked or values["overall_status"] in ("skipped", "extra"):
        outcome["derived_completion_status"] = overall
    return outcome


def _current_plan(session: Session, uid: UUID) -> CalendarSessionRevision | None:
    state = session.get(AppState, 1)
    head = state.calendar_head_version if state else 0
    if head == 0:
        return None
    row = session.scalar(select(CalendarSessionRevision).where(CalendarSessionRevision.session_uid == uid,
                         CalendarSessionRevision.calendar_version_number <= head)
                         .order_by(CalendarSessionRevision.calendar_version_number.desc(),
                                   CalendarSessionRevision.revision.desc()).limit(1))
    return row if row and not row.deleted else None


def _activity(session: Session, completion: SessionCompletion) -> tuple[dict | None, dict]:
    if completion.activity_id:
        activity_row = session.get(Activity, completion.activity_id)
        if activity_row is None:
            return None, {"activity_id": str(completion.activity_id), "resolution_state": None}
        tz = athlete_tz(session)
        local_day = activity_row.start_at.astimezone(tz).date()
        eligible = any(r.activity_id == activity_row.id for r in load_runs(session, local_day,
                                                                          local_day + date.resolution))
        if not eligible:
            return None, {"activity_id": str(completion.activity_id),
                          "resolution_state": activity_row.resolution_state,
                          **metric_source_refs(session, activity_row.id, completion.session_uid)}
        refs = metric_source_refs(session, activity_row.id, completion.session_uid)
        return {"kind": "run", "timer_s": activity_row.timer_s, "distance_m": activity_row.distance_m,
                "activity_id": str(activity_row.id)}, refs
    if completion.strong_workout_id:
        strong_row = session.get(StrongWorkoutRow, completion.strong_workout_id)
        if strong_row is None or strong_row.resolution_state != "resolved":
            return None, {"strong_workout_id": str(completion.strong_workout_id)}
        source_record = session.get(SourceRecord, strong_row.source_record_id)
        raw_object = session.get(RawObject, strong_row.raw_object_id)
        return {"kind": "strength", "timer_s": strong_row.duration_s, "distance_m": None}, {
            "strong_workout_id": str(strong_row.id), "source_record_id": str(strong_row.source_record_id),
            "source_payload_hash": source_record.payload_hash if source_record else None,
            "source_parser_version": source_record.parser_version if source_record else None,
            "raw_object_id": str(strong_row.raw_object_id), "raw_sha256": raw_object.sha256 if raw_object else None,
            "payload_hash": strong_row.payload_hash}
    if completion.manual_session_id:
        manual_row = session.get(ManualSession, completion.manual_session_id)
        if manual_row is None:
            return None, {"manual_session_id": str(completion.manual_session_id)}
        return {"kind": manual_row.kind, "timer_s": manual_row.duration_s, "distance_m": None}, {
            "manual_session_id": str(manual_row.id), "version": manual_row.version,
            "source_revision": sha256_json({"version": manual_row.version, "date": manual_row.date.isoformat(),
                                             "time": manual_row.time.isoformat() if manual_row.time else None,
                                             "duration_s": manual_row.duration_s, "kind": manual_row.kind})}
    return None, {}


def _interval_components(value: dict | None) -> dict | None:
    if value is None:
        return None
    result = dict(value)
    reps = value.get("reps")
    if isinstance(reps, list):
        valid = [float(rep["target_valid_s"]) for rep in reps if isinstance(rep, dict)
                 and rep.get("target_valid_s") is not None]
        in_range = [float(rep["target_in_range_s"]) for rep in reps if isinstance(rep, dict)
                    and rep.get("target_in_range_s") is not None]
        if valid and len(valid) == len(in_range) and sum(valid) > 0:
            result["target_coverage"] = sum(in_range) / sum(valid)
    planned = value.get("n_planned")
    completed = value.get("n_completed")
    if isinstance(planned, int) and planned > 0 and isinstance(completed, int):
        result["step_completion_ratio"] = completed / planned
    return result


@register(METRIC_ID, METHOD_VERSION, DEPENDS_ON)
def compute(session: Session, subject_key: str) -> list[MetricResultData]:
    try:
        uid = UUID(subject_key)
    except ValueError as exc:
        raise ValueError("invalid_subject_key") from exc
    plan = _current_plan(session, uid)
    completion = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == uid))
    if plan is None and completion is None:
        return []
    plan_data = ({"local_date": plan.local_date, "kind": plan.kind, "certainty": plan.certainty,
                  "planned_duration_s": plan.planned_duration_s, "planned_distance_m": plan.planned_distance_m,
                  "structure": plan.structure, "calendar_version_number": plan.calendar_version_number}
                 if plan else None)
    completion_data = ({"status": completion.status, "match_method": completion.match_method,
                        "modification_reason": completion.modification_reason,
                        "activity_id": completion.activity_id, "strong_workout_id": completion.strong_workout_id,
                        "manual_session_id": completion.manual_session_id} if completion else None)
    activity, activity_refs = _activity(session, completion) if completion else (None, {})
    interval_row = (latest_results(session, "work_interval_execution", "v1", [str(completion.activity_id)])
                    .get(str(completion.activity_id)) if completion and completion.activity_id else None)
    intervals = _interval_components(interval_row.value) if interval_row and isinstance(interval_row.value, dict) else None
    local_date = plan.local_date if plan else None
    if local_date is None and completion:
        if completion.activity_id:
            actual = session.get(Activity, completion.activity_id)
            local_date = actual.local_date if actual else None
        elif completion.strong_workout_id:
            actual_strong = session.get(StrongWorkoutRow, completion.strong_workout_id)
            local_date = actual_strong.local_date if actual_strong else None
        elif completion.manual_session_id:
            actual_manual = session.get(ManualSession, completion.manual_session_id)
            local_date = actual_manual.date if actual_manual else None
    tz = athlete_tz(session)
    now = session.info.get("metrics_now") or datetime.now(UTC)
    as_of = now.astimezone(tz).date()
    candidates = candidates_for_session(session, uid) if plan else []
    coverage = activities_coverage_complete(session, local_date, local_date + date.resolution) if local_date else False
    outcome = planned_actual_outcome(plan_data, completion_data, activity, intervals, candidates, coverage, as_of)
    if completion is not None and "derived_completion_status" in outcome:
        derived = outcome["derived_completion_status"]
        if completion.status != derived:
            completion.status = derived
            completion.version += 1
            completion.updated_at = now
    refs = {"session_uid": str(uid), "plan": {"revision_id": str(plan.id),
            "revision": plan.revision, "calendar_version": plan.calendar_version_number,
            "structure_hash": sha256_json(plan.structure)} if plan else None,
            "completion_association_hash": completion_association_hash(completion) if completion else None,
            "activity": activity_refs, "interval_result_id": str(interval_row.id) if interval_row else None,
            "interval_dependency_hash": interval_row.dependency_hash if interval_row else None,
            "candidate_activity_ids": outcome["value"]["candidate_activity_ids"],
            "coverage_complete": coverage, "as_of": as_of.isoformat()}
    refs["input_hash"] = sha256_json(refs)
    return [MetricResultData(METRIC_ID, METHOD_VERSION, "session", subject_key, Status(outcome["status"]),
                             tuple(outcome["reason_codes"]), tuple(outcome["quality_flags"]), refs, (),
                             config_hash(CONFIG), window_label=local_date.isoformat() if local_date else None,
                             quality_status=QualityStatus(outcome["quality_status"]) if outcome["quality_status"] else None,
                             value=outcome["value"], unit=None, timezone=tz.key)]
