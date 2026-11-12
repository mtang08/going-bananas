"""Long-run classification and exposure from recorded timer and distance facts."""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, SessionCompletion
from app.checkin_models import Checkin, SymptomReport
from app.domain.analytics import utc_date_bounds
from app.metrics.contract import MetricResultData, QualityStatus, RunFact, Status, config_hash, sha256_json
from app.metrics.engine import activities_coverage_complete, latest_results, load_runs, metric_source_refs, register
from app.metrics.symptoms import linked_activity_for_checkin
from app.metrics.volume import parse_window_key
from app.models import Activity, AppState
from app.services.timezone import athlete_tz

METRIC_ID = "long_run_exposure"
METHOD_VERSION = "v1"
WINDOW_DAYS = (7, 14, 28, 56, 84)
DEPENDS_ON = ("symptom_response_timeline",)
CONFIG = {"precedence": ["plan_link", "manual", "long_rule"], "long_recipe": "REC002",
          "rule": "long_rule.v1", "rule_multiplier": 1.33, "rule_lookback_days": 28,
          "rule_min_prior_runs": 4, "comparator_lookback_days": 30,
          "break_lookback_days": 14, "weekly_window_days": 7,
          "weekly_includes_current": True}
RUN_SPORTS = ("running", "trail_running", "treadmill_running")


def _measure(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) and value >= 0 else None


def classify(run: RunFact, prior_28: list[RunFact], plan_linked: bool,
             plan_recipe: str | None) -> tuple[str, str, str]:
    if plan_linked:
        return ("long" if plan_recipe == "REC002" else "not_long", "plan_link", "high")
    if run.workout_label is not None:
        return ("long" if run.workout_label == "long" else "not_long", "manual", "high")
    timers = [value for r in prior_28 if (value := _measure(r.timer_s)) is not None]
    current_timer = _measure(run.timer_s)
    if current_timer is None or len(timers) < 4:
        return "unknown", "long_rule", "low"
    return ("long" if current_timer >= 1.33 * statistics.median(timers) else "not_long", "long_rule", "low")


def _max_with_run(runs: list[RunFact], field: str) -> tuple[float | None, RunFact | None]:
    selected = [(value, r) for r in runs if (value := _measure(getattr(r, field))) is not None]
    if not selected:
        return None, None
    return max(selected, key=lambda item: item[0])


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or not math.isfinite(numerator) or not math.isfinite(denominator) or denominator <= 0:
        return None
    return round(numerator / denominator, 3)


def exposure_outcome(run: RunFact, history: list[RunFact], plan_linked: bool, plan_recipe: str | None,
                     coverage_complete_week: bool, delayed_symptom_status: str,
                     linked_checkin_ids: list[str], coverage_complete_comparator: bool = True) -> dict:
    d = run.local_date
    others = [h for h in history if h.activity_id != run.activity_id]
    prior_28 = [h for h in others if h.start_at < run.start_at and d - timedelta(days=28) <= h.local_date <= d]
    prior_30 = [h for h in others if h.start_at < run.start_at and d - timedelta(days=30) <= h.local_date <= d]
    week = [h for h in history if d - timedelta(days=6) <= h.local_date <= d]
    classification, source, confidence = classify(run, prior_28, plan_linked, plan_recipe)
    run_timer, run_distance = _measure(run.timer_s), _measure(run.distance_m)
    value: dict[str, Any] = {"activity_id": str(run.activity_id), "local_date": d.isoformat(), "timer_s": run_timer,
             "distance_m": run_distance, "classification": classification,
             "classification_source": source, "classification_confidence": confidence,
             "delayed_symptom_status": delayed_symptom_status,
             "linked_checkin_ids": linked_checkin_ids}
    if classification == "not_long":
        return {"status": "not_applicable", "quality_status": None, "value": value,
                "reason_codes": ["NOT_LONG_RUN"], "quality_flags": []}
    if classification == "unknown":
        reasons = ["CLASSIFICATION_UNKNOWN"]
        if len([h for h in prior_28 if _measure(h.timer_s) is not None]) < 4:
            reasons.append("INSUFFICIENT_HISTORY")
        if run_timer is None:
            reasons.append("TIMER_MISSING")
        return {"status": "not_assessable", "quality_status": None, "value": value,
                "reason_codes": reasons, "quality_flags": []}
    max_timer, timer_run = _max_with_run(prior_30, "timer_s")
    max_distance, distance_run = _max_with_run(prior_30, "distance_m")
    week_timer_values = [measurement for h in week if (measurement := _measure(h.timer_s)) is not None]
    week_distance_values = [measurement for h in week if (measurement := _measure(h.distance_m)) is not None]
    week_timer = sum(week_timer_values) if week_timer_values else None
    week_distance = sum(week_distance_values) if week_distance_values else None
    duration_ratio = _ratio(run_timer, max_timer)
    distance_ratio = _ratio(run_distance, max_distance)
    duration_share = _ratio(run_timer, week_timer)
    distance_share = _ratio(run_distance, week_distance)
    value.update({"prior_max_timer_s": round(max_timer, 1) if max_timer is not None else None,
                  "prior_max_distance_m": round(max_distance, 1) if max_distance is not None else None,
                  "duration_ratio_to_recent_max": duration_ratio,
                  "distance_ratio_to_recent_max": distance_ratio,
                  "week_timer_s": round(week_timer, 1) if week_timer is not None else None,
                  "week_distance_m": round(week_distance, 1) if week_distance is not None else None,
                  "weekly_share_duration": duration_share, "weekly_share_distance": distance_share,
                  "comparator_window": {"start_date": (d - timedelta(days=30)).isoformat(),
                                        "end_date": d.isoformat()},
                  "weekly_window": {"start_date": (d - timedelta(days=6)).isoformat(),
                                    "end_date": d.isoformat()}})
    reasons = []
    if not prior_30:
        reasons.append("INSUFFICIENT_HISTORY")
    if run_timer is None:
        reasons.append("TIMER_MISSING")
    if run_distance is None:
        reasons.append("DISTANCE_MISSING")
    flags = []
    if not any(d - timedelta(days=14) <= h.local_date <= d - timedelta(days=1) for h in others):
        flags.append("RETURN_FROM_BREAK")
    if any(source_run is not None and source_run.sport != run.sport for source_run in (timer_run, distance_run)):
        flags.append("SURFACE_NOT_COMPARABLE")
    if not coverage_complete_comparator or prior_30 and any(
            _measure(h.timer_s) is None or _measure(h.distance_m) is None for h in prior_30):
        flags.append("PARTIAL_COMPARATOR")
    if not coverage_complete_week or any(_measure(h.timer_s) is None or _measure(h.distance_m) is None for h in week):
        flags.append("PARTIAL_WEEK")
    if not coverage_complete_week:
        flags.append("SYNC_COVERAGE_INCOMPLETE")
    if source == "long_rule":
        flags.append("LOW_CONFIDENCE_CLASSIFICATION")
    complete = all(x is not None for x in (duration_ratio, distance_ratio, duration_share, distance_share))
    return {"status": "available" if complete else "partial",
            "quality_status": "good" if complete and not flags else "limited",
            "value": value, "reason_codes": reasons, "quality_flags": flags}


def delayed_status(checkins: list[tuple[str, list[float]]]) -> str:
    delayed = [severities for kind, severities in checkins if kind == "delayed_followup"]
    if not delayed:
        return "unknown"
    return "reported" if any(severity > 0 for values in delayed for severity in values) else "none_reported"


def window_outcome(entries: list[dict], coverage_complete: bool = True,
                   expected_run_count: int | None = None) -> dict:
    missing_results = expected_run_count is not None and len(entries) < expected_run_count
    unknown = any(entry.get("classification") == "unknown" for entry in entries)
    flags = (["SYNC_COVERAGE_INCOMPLETE"] if not coverage_complete else []) + (
        ["ACTIVITY_RESULT_MISSING"] if missing_results else []) + (
        ["CLASSIFICATION_UNKNOWN"] if unknown else [])
    if not entries and not coverage_complete:
        return {"status": "missing", "quality_status": None, "value": None,
                "reason_codes": [], "quality_flags": flags}
    long = [entry for entry in entries if entry["classification"] == "long"]
    return {"status": "partial" if flags else "available", "quality_status": None,
            "value": {"long_run_count": len(long), "latest": long[-1] if long else None},
            "reason_codes": [], "quality_flags": flags}


def _plan_link(session: Session, activity_id: UUID) -> tuple[bool, str | None]:
    completion = session.scalar(select(SessionCompletion).where(SessionCompletion.activity_id == activity_id))
    if completion is None:
        return False, None
    state = session.get(AppState, 1)
    head = state.calendar_head_version if state else 0
    revision = session.scalar(select(CalendarSessionRevision).where(
        CalendarSessionRevision.session_uid == completion.session_uid,
        CalendarSessionRevision.calendar_version_number <= head)
        .order_by(CalendarSessionRevision.calendar_version_number.desc(), CalendarSessionRevision.revision.desc()).limit(1))
    if revision is None or revision.deleted or revision.kind != "run":
        return False, None
    return True, revision.recipe_id


def _linked_checkins(session: Session, run: RunFact) -> tuple[list[tuple[str, list[float]]], list[str], list[dict]]:
    explicit = list(session.scalars(select(Checkin).where(Checkin.activity_id == run.activity_id)).all())
    inferred = []
    if run.end_at is not None:
        candidates = session.scalars(select(Checkin).where(Checkin.activity_id.is_(None),
                            Checkin.observed_at >= run.end_at,
                            Checkin.observed_at <= run.end_at + timedelta(hours=48))).all()
        inferred = [c for c in candidates if linked_activity_for_checkin(session, c) == run.activity_id]
    rows = sorted(explicit + inferred, key=lambda c: (c.observed_at, str(c.id)))
    summaries = []
    refs = []
    for c in rows:
        reports = list(session.scalars(select(SymptomReport).where(SymptomReport.checkin_id == c.id)
                                       .order_by(SymptomReport.id)).all())
        summaries.append((c.kind, [r.severity for r in reports]))
        refs.append({"id": str(c.id), "version": c.version, "kind": c.kind,
                     "observed_at": c.observed_at.isoformat(),
                     "activity_id": str(c.activity_id) if c.activity_id else None,
                     "reports": [{"id": str(r.id), "severity": r.severity, "site": r.site,
                                  "side": r.side, "timing": r.timing} for r in reports]})
    return summaries, [str(c.id) for c in rows], refs


def _result(key: str, outcome: dict, refs: dict, tz: str, start: datetime | None,
            end: datetime | None, is_window: bool = False, label: str | None = None) -> MetricResultData:
    return MetricResultData(METRIC_ID, METHOD_VERSION, "window" if is_window else "activity", key,
                            Status(outcome["status"]), tuple(outcome["reason_codes"]),
                            tuple(outcome["quality_flags"]), refs, (), config_hash(CONFIG),
                            window_start=start, window_end=end, window_label=key if is_window else label,
                            quality_status=QualityStatus(outcome["quality_status"]) if outcome["quality_status"] else None,
                            value=outcome["value"], unit=None, timezone=tz)


@register(METRIC_ID, METHOD_VERSION, DEPENDS_ON)
def compute(session: Session, subject_key: str) -> list[MetricResultData]:
    tz = athlete_tz(session)
    if subject_key.startswith("w"):
        days, as_of = parse_window_key(subject_key)
        first = as_of - timedelta(days=days - 1)
        runs = load_runs(session, first, as_of + timedelta(days=1))
        runs.sort(key=lambda r: (r.start_at, str(r.activity_id)))
        keys = [str(r.activity_id) for r in runs]
        latest = latest_results(session, METRIC_ID, METHOD_VERSION, keys)
        entries = [cast(dict, latest[key].value) for key in keys
                   if key in latest and isinstance(latest[key].value, dict)]
        source_rows = [{"activity_id": key, "source_revision": run.source_revision,
                        "source_refs": run.source_refs,
                        "metric_result_id": str(latest[key].id) if key in latest else None,
                        "metric_dependency_hash": latest[key].dependency_hash if key in latest else None}
                       for key, run in zip(keys, runs)]
        coverage = activities_coverage_complete(session, first, as_of + timedelta(days=1))
        refs = {"activity_ids": keys, "sources": source_rows, "coverage_complete": coverage,
                "expected_run_count": len(runs), "computed_result_count": len(entries),
                "input_hash": sha256_json({"sources": source_rows, "coverage_complete": coverage,
                                           "expected_run_count": len(runs), "computed_result_count": len(entries)})}
        start, end = utc_date_bounds(first, as_of, tz.key)
        return [_result(subject_key, window_outcome(entries, coverage, len(runs)), refs, tz.key, start, end, True)]
    try:
        activity_id = UUID(subject_key)
    except ValueError as exc:
        raise ValueError("invalid_subject_key") from exc
    activity = session.get(Activity, activity_id)
    if activity is None or activity.sport not in RUN_SPORTS:
        return []
    day = activity.start_at.astimezone(tz).date()
    history = load_runs(session, day - timedelta(days=30), day + timedelta(days=1))
    run = next((r for r in history if r.activity_id == activity_id), None)
    refs = {**metric_source_refs(session, activity_id), "activity_ids": [str(activity_id)]}
    if run is None:
        outcome = {"status": "not_applicable", "quality_status": None, "value": None,
                   "reason_codes": ["ACTIVITY_EXCLUDED"], "quality_flags": []}
        return [_result(subject_key, outcome, refs, tz.key, activity.start_at, activity.end_at,
                        label=day.isoformat())]
    linked, recipe = _plan_link(session, activity_id)
    completion = session.scalar(select(SessionCompletion).where(SessionCompletion.activity_id == activity_id))
    session_uid = completion.session_uid if completion else None
    refs.update(metric_source_refs(session, activity_id, session_uid))
    summaries, checkin_ids, checkin_refs = _linked_checkins(session, run)
    coverage = activities_coverage_complete(session, day - timedelta(days=6), day + timedelta(days=1))
    comparator_coverage = activities_coverage_complete(session, day - timedelta(days=30), day + timedelta(days=1))
    ordered_history = sorted(history, key=lambda h: (h.start_at, str(h.activity_id)))
    prior = [h for h in ordered_history if h.activity_id != activity_id and h.start_at < run.start_at]
    later_week = [h for h in ordered_history if h.activity_id != activity_id and h.start_at >= run.start_at
                  and day - timedelta(days=6) <= h.local_date <= day]
    refs.update({"activity_ids": [str(run.activity_id)] + [str(h.activity_id) for h in prior],
                 "weekly_other_activity_ids": [str(h.activity_id) for h in later_week],
                 "history": [{"activity_id": str(h.activity_id), "source_revision": h.source_revision,
                              "source_refs": h.source_refs} for h in ordered_history],
                 "session_uid": str(session_uid) if session_uid else None,
                 "plan_linked": linked, "plan_recipe": recipe,
                 "checkin_ids": checkin_ids, "checkins": checkin_refs,
                 "coverage_complete_week": coverage, "coverage_complete_comparator": comparator_coverage})
    refs["input_hash"] = sha256_json({"history": refs["history"], "plan": refs.get("plan"),
                                      "completion_association_hash": refs.get("completion_association_hash"),
                                      "checkins": checkin_refs, "coverage_complete_week": coverage,
                                      "coverage_complete_comparator": comparator_coverage})
    outcome = exposure_outcome(run, history, linked, recipe, coverage, delayed_status(summaries),
                               checkin_ids, comparator_coverage)
    return [_result(subject_key, outcome, refs, tz.key, run.start_at, run.end_at,
                    label=day.isoformat())]
