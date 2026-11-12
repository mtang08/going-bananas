"""Running frequency, timer duration, and distance by athlete-local window."""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.domain.analytics import utc_date_bounds
from app.metrics.contract import MetricResultData, QualityStatus, RunFact, Status, config_hash, sha256_json
from app.metrics.engine import activities_coverage_complete, load_runs, register
from app.services.timezone import athlete_tz

METRIC_ID = "run_volume_frequency"
METHOD_VERSION = "v1"
WINDOW_DAYS = (7, 14, 28, 56, 84)
DEPENDS_ON: tuple[str, ...] = ()
CONFIG = {"window_days": [7, 14, 28, 56, 84],
          "sports": ["running", "trail_running", "treadmill_running"],
          "duration_field": "timer_s", "local_day_rule": "start_at_in_profile_tz"}


def parse_window_key(key: str) -> tuple[int, date]:
    match = re.fullmatch(r"w(\d+):(\d{4}-\d{2}-\d{2})", key)
    if match is None:
        raise ValueError("invalid_subject_key")
    try:
        days, as_of = int(match[1]), date.fromisoformat(match[2])
    except ValueError as exc:
        raise ValueError("invalid_subject_key") from exc
    if days not in WINDOW_DAYS:
        raise ValueError("invalid_subject_key")
    return days, as_of


def totals(runs: list[RunFact], start: date, end_excl: date) -> dict:
    selected = [r for r in runs if start <= r.local_date < end_excl]
    timer = [r.timer_s for r in selected if r.timer_s is not None and math.isfinite(r.timer_s) and r.timer_s >= 0]
    distance = [r.distance_m for r in selected if r.distance_m is not None
                and math.isfinite(r.distance_m) and r.distance_m >= 0]
    return {"start_date": start.isoformat(), "end_date": (end_excl - timedelta(days=1)).isoformat(),
            "run_count": len(selected),
            "timer_duration_s": round(sum(timer), 1) if timer else (0.0 if not selected else None),
            "distance_m": round(sum(distance), 1) if distance else (0.0 if not selected else None),
            "runs_missing_timer": len(selected) - len(timer),
            "runs_missing_distance": len(selected) - len(distance)}


def volume_outcome(runs: list[RunFact], as_of: date, days: int, coverage_complete: bool,
                   previous_coverage_complete: bool) -> dict:
    if days not in WINDOW_DAYS:
        raise ValueError("invalid_subject_key")
    start = as_of - timedelta(days=days - 1)
    selected = [r for r in runs if start <= r.local_date <= as_of]
    cur = totals(runs, start, as_of + timedelta(days=1))
    prev = totals(runs, start - timedelta(days=days), start)
    if not previous_coverage_complete and prev["run_count"] == 0:
        prev["timer_duration_s"] = None
        prev["distance_m"] = None
    reasons = []
    if cur["runs_missing_timer"]:
        reasons.append("TIMER_MISSING")
    if cur["runs_missing_distance"]:
        reasons.append("DISTANCE_MISSING")
    flags = [] if coverage_complete else ["SYNC_COVERAGE_INCOMPLETE"]
    if not coverage_complete and not selected:
        cur["timer_duration_s"] = None
        cur["distance_m"] = None
        status = "missing"
    else:
        status = "partial" if reasons or flags else "available"
    return {"status": status, "quality_status": "good" if status == "available" else
            "limited" if status == "partial" else None,
            "value": {**cur, "previous": {**prev, "coverage_complete": previous_coverage_complete}},
            "reason_codes": reasons, "quality_flags": flags,
            "activity_ids": [str(r.activity_id) for r in selected]}


def _result(key: str, outcome: dict, source_refs: dict, timezone: str,
            start: datetime, end: datetime) -> MetricResultData:
    return MetricResultData(METRIC_ID, METHOD_VERSION, "window", key, Status(outcome["status"]),
                            tuple(outcome["reason_codes"]), tuple(outcome["quality_flags"]),
                            source_refs, (), config_hash(CONFIG), window_start=start, window_end=end,
                            window_label=key,
                            quality_status=QualityStatus(outcome["quality_status"]) if outcome["quality_status"] else None,
                            value=outcome["value"], unit=None, timezone=timezone)


@register(METRIC_ID, METHOD_VERSION, DEPENDS_ON)
def compute(session: Session, subject_key: str) -> list[MetricResultData]:
    days, as_of = parse_window_key(subject_key)
    tz = athlete_tz(session)
    start_day = as_of - timedelta(days=days - 1)
    previous_day = start_day - timedelta(days=days)
    runs = load_runs(session, previous_day, as_of + timedelta(days=1))
    current_coverage = activities_coverage_complete(session, start_day, as_of + timedelta(days=1))
    previous_coverage = activities_coverage_complete(session, previous_day, start_day)
    outcome = volume_outcome(runs, as_of, days, current_coverage, previous_coverage)
    relevant = sorted(runs, key=lambda r: (r.start_at, str(r.activity_id)))
    sources = [{"activity_id": str(r.activity_id), "source_revision": r.source_revision,
                "source_refs": r.source_refs} for r in relevant]
    refs = {"activity_ids": outcome["activity_ids"], "sources": sources,
            "coverage_complete": current_coverage, "previous_coverage_complete": previous_coverage,
            "input_hash": sha256_json({"sources": sources, "coverage_complete": current_coverage,
                                       "previous_coverage_complete": previous_coverage})}
    start, end = utc_date_bounds(start_day, as_of, tz.key)
    return [_result(subject_key, outcome, refs, tz.key, start, end)]
