"""Timer-weighted intensity distributions; missing anchors/data remain explicit."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.fit_models import ActivityStream
from app.metrics.anchors import ActiveAnchor, active_anchors, anchor_set_hash
from app.metrics.contract import (
    MetricResultData,
    QualityStatus,
    Status,
    config_hash,
    coverage_label,
    integrate_timer_on,
    plausible_hr,
    plausible_speed,
    sha256_json,
)
from app.metrics.engine import activities_coverage_complete, latest_results, load_runs, metric_source_refs, register
from app.models import Activity
from app.services.timezone import athlete_tz

METRIC_ID = "intensity_time_distribution"
METHOD_VERSION = "v1"
WINDOW_DAYS = (7, 14, 28, 56, 84)
DEPENDS_ON: tuple[str, ...] = ()
MODALITIES = {"hr": ("hr_aerobic_upper", "hr_threshold_lower"),
              "speed": ("speed_aerobic_upper", "speed_threshold_lower")}
CONFIG: dict = {"max_record_gap_s": 10, "zones": ["easy", "moderate", "high"], "zone_rule": "lower_inclusive",
          "hr_valid_bpm": [30, 230], "speed_valid_mps": [0, 10], "coverage_good": 0.9, "coverage_limited": 0.7}
_SECONDS = ("easy_s", "moderate_s", "high_s", "valid_s", "unclassified_s", "unknown_s", "eligible_timer_s")
_NUMBERS = (*_SECONDS, "coverage", "fraction_valid", "fraction_timer")
_TIMER_FLAGS = ("TIMER_EVENTS_MISSING", "TIMER_EVENTS_AMBIGUOUS", "TIMER_MISMATCH")


@dataclass(frozen=True)
class StreamIn:
    t_s: list[int]
    hr_bpm: list[float | None]
    speed_mps: list[float | None]
    timer_on: list[tuple[int, int]]
    quality_flags: tuple[str, ...] = ()


def zone(v: float, aerobic_upper: float, threshold_lower: float) -> str:
    return "easy" if v < aerobic_upper else "moderate" if v < threshold_lower else "high"


def sample_valid(modality: str, v: float | None) -> bool:
    return plausible_hr(v) if modality == "hr" else plausible_speed(v)


def _ratios(values: dict) -> dict:
    valid, eligible = values["valid_s"], values["eligible_timer_s"]
    return {"coverage": round(valid / eligible, 3) if eligible else None,
            "fraction_valid": {z: round(values[f"{z}_s"] / valid, 3) for z in CONFIG["zones"]} if valid else None,
            "fraction_timer": {z: round(values[f"{z}_s"] / eligible, 3) for z in CONFIG["zones"]} if eligible else None}


def distribution(modality: str, stream: StreamIn, aerobic_upper: float, threshold_lower: float) -> dict:
    series = stream.hr_bpm if modality == "hr" else stream.speed_mps
    values = {key: 0.0 for key in _SECONDS}
    for i, seconds, known in integrate_timer_on(stream.t_s, [(float(a), float(b)) for a, b in stream.timer_on], 10):
        values["eligible_timer_s"] += seconds
        v = series[i] if i is not None and i < len(series) else None
        if not known or not sample_valid(modality, v):
            values["unknown_s"] += seconds
        else:
            assert v is not None
            values[f"{zone(v, aerobic_upper, threshold_lower)}_s"] += seconds
            values["valid_s"] += seconds
    return {**{k: round(v, 1) for k, v in values.items()}, **_ratios(values)}


def modality_outcome(modality: str, stream: StreamIn | None, anchors: dict[str, ActiveAnchor],
                     local_date: date, session_timer_s: float | None) -> dict:
    result: dict = {"status": "missing", "reason_codes": [], "quality_status": None,
                    "flags": [], "anchors_used": [], "confidence": None, **dict.fromkeys(_NUMBERS)}

    def stop(status: str, reason: str) -> dict:
        result.update(status=status, reason_codes=[reason])
        return result

    if stream is None:
        return stop("missing", "NO_STREAM")
    timer_flags = [flag for flag in _TIMER_FLAGS if flag in stream.quality_flags]
    if timer_flags:
        result.update(status="not_assessable", reason_codes=timer_flags, flags=timer_flags)
        if "TIMER_MISMATCH" in timer_flags:
            eligible = sum(seconds for _, seconds, _ in integrate_timer_on(
                stream.t_s, [(float(a), float(b)) for a, b in stream.timer_on], 10))
            result["timer_diagnostics"] = {"eligible_timer_s": round(eligible, 1), "session_timer_s": session_timer_s}
        return result
    pair = [anchors.get(kind) for kind in MODALITIES[modality]]
    if any(a is None or a.confidence == "insufficient" for a in pair):
        return stop("not_assessable", "ANCHOR_MISSING")
    aerobic, threshold = pair
    assert aerobic is not None and threshold is not None
    result["anchors_used"] = [aerobic, threshold]
    if aerobic.value_low >= threshold.value_low:
        return stop("invalid", "ANCHOR_CONFIG_ERROR")
    confidences = ("low", "moderate", "high")
    result["confidence"] = min((aerobic.confidence, threshold.confidence), key=confidences.index)
    if result["confidence"] == "low":
        result["flags"].append("LOW_CONFIDENCE_ANCHOR")
    if any(local_date > a.review_after for a in (aerobic, threshold)):
        result["flags"].append("ANCHOR_REVIEW_DUE")
    series = stream.hr_bpm if modality == "hr" else stream.speed_mps
    if all(v is None for v in series):
        return stop("missing", "HR_NOT_RECORDED" if modality == "hr" else "SPEED_NOT_RECORDED")
    values = distribution(modality, stream, aerobic.value_low, threshold.value_low)
    eligible = values["eligible_timer_s"]
    if eligible == 0:
        return stop("missing", "NO_TIMER_ON_DATA")
    if session_timer_s is not None and abs(eligible - session_timer_s) > max(1, .01 * session_timer_s):
        result["flags"].append("TIMER_MISMATCH")
        result["timer_diagnostics"] = {"eligible_timer_s": eligible, "session_timer_s": session_timer_s}
        return stop("not_assessable", "TIMER_MISMATCH")
    quality = coverage_label(values["valid_s"], eligible)
    result.update(values)
    result.update(quality_status=quality, status="available" if quality == "good" else "partial",
                  reason_codes=[] if quality == "good" else ["LOW_COVERAGE"])
    return result


def _combined(modalities: list[dict]) -> dict:
    statuses = [m["status"] for m in modalities]
    status = ("available" if all(s == "available" for s in statuses) else
              "partial" if any(s in ("available", "partial") for s in statuses) else
              "not_assessable" if "not_assessable" in statuses else
              "invalid" if "invalid" in statuses else "missing")
    qualities = [m["quality_status"] for m in modalities if m.get("quality_status") is not None]
    return {"status": status, "quality_status": min(qualities, key=("insufficient", "limited", "good").index)
            if qualities else None, "reason_codes": sorted({r for m in modalities for r in m["reason_codes"]}),
            "quality_flags": sorted({f for m in modalities for f in m.get("flags", [])})}


def activity_outcome(stream: StreamIn | None, anchors: dict[str, ActiveAnchor], local_date: date,
                     session_timer_s: float | None) -> dict:
    outcomes = {m: modality_outcome(m, stream, anchors, local_date, session_timer_s) for m in MODALITIES}
    used = {a.anchor_key: a for m in outcomes.values() for a in m["anchors_used"]}
    value = {name: {k: v for k, v in outcome.items() if k not in {"flags", "anchors_used", "quality_status"}}
             for name, outcome in outcomes.items()}
    value["session_timer_s"] = session_timer_s  # type: ignore[assignment]
    return {**_combined(list(outcomes.values())), "value": value, "anchor_keys": sorted(used),
            "anchors_used": [used[key] for key in sorted(used)]}


def window_outcome(items: list[dict | None], coverage_complete: bool = True) -> dict:
    outcomes = {}
    for modality in MODALITIES:
        results = [(item.get("value") or {}).get(modality) if item else None for item in items]
        counted = [m for m in results if m and m["status"] in ("available", "partial")]
        result: dict = {"confidence": None, "activities_total": len(items), "activities_counted": len(counted),
                  "activities_without_result": sum(item is None for item in items), "flags": [],
                  "quality_status": None, "reason_codes": [], **dict.fromkeys(_NUMBERS)}
        if not items and coverage_complete:
            values = {k: 0.0 for k in _SECONDS}
            result.update(values, status="available", **_ratios(values))
        elif not counted:
            result.update(status="not_assessable" if any(m and m["status"] == "not_assessable" for m in results)
                          else "missing", reason_codes=["NO_ACTIVITY_COUNTED"] if items else ["SYNC_COVERAGE_INCOMPLETE"])
        else:
            values = {key: sum(m[key] for m in counted) for key in _SECONDS}
            result.update({key: round(value, 1) for key, value in values.items()}, **_ratios(values))
            reasons = []
            if len(counted) < len(items):
                reasons.append("ACTIVITIES_NOT_COUNTED")
            if any(m["status"] == "partial" for m in counted):
                reasons.append("PARTIAL_ACTIVITY_COVERAGE")
            result.update(status="partial" if reasons or not coverage_complete else "available",
                          reason_codes=reasons, quality_status=coverage_label(values["valid_s"], values["eligible_timer_s"]))
        if not coverage_complete and "SYNC_COVERAGE_INCOMPLETE" not in result["reason_codes"]:
            result["reason_codes"].append("SYNC_COVERAGE_INCOMPLETE")
        outcomes[modality] = result
    value = {name: {k: v for k, v in result.items() if k not in {"flags", "quality_status"}}
             for name, result in outcomes.items()}
    value["anchor_set_hashes"] = sorted({item["anchor_set_hash"] for item in items if item and item.get("anchor_set_hash")})  # type: ignore[assignment]
    return {**_combined(list(outcomes.values())), "value": value,
            "anchor_keys": sorted({key for item in items if item for key in item.get("anchor_keys", [])})}


def _result(key: str, outcome: dict, refs: dict, timezone: str, *, start: datetime | None = None,
            end: datetime | None = None) -> MetricResultData:
    return MetricResultData(METRIC_ID, METHOD_VERSION, "window" if start else "activity", key,
                            Status(outcome["status"]), tuple(outcome["reason_codes"]), tuple(outcome["quality_flags"]),
                            refs, tuple(outcome["anchor_keys"]), config_hash(CONFIG), window_start=start,
                            window_end=end, window_label=key if start else None,
                            quality_status=QualityStatus(outcome["quality_status"]) if outcome["quality_status"] else None,
                            value=outcome["value"], unit="s", timezone=timezone,
                            anchor_set_hash=anchor_set_hash(outcome.get("anchors_used", [])))


@register(METRIC_ID, METHOD_VERSION, DEPENDS_ON)
def compute(session: Session, subject_key: str) -> list[MetricResultData]:
    tz = athlete_tz(session)
    match = re.fullmatch(r"w(\d+):(\d{4}-\d{2}-\d{2})", subject_key)
    if match:
        try:
            days, as_of = int(match[1]), date.fromisoformat(match[2])
            if days not in WINDOW_DAYS:
                raise ValueError
        except ValueError as exc:
            raise ValueError("invalid_subject_key") from exc
        start, end = as_of - timedelta(days=days - 1), as_of + timedelta(days=1)
        runs = load_runs(session, start, end)
        keys = [str(run.activity_id) for run in runs]
        rows = latest_results(session, METRIC_ID, METHOD_VERSION, keys)
        items = [{"status": rows[key].status, "value": rows[key].value,
                  "anchor_set_hash": rows[key].anchor_set_hash, "anchor_keys": rows[key].anchor_keys}
                 if key in rows else None for key in keys]
        complete = activities_coverage_complete(session, start, end)
        outcome = window_outcome(items, complete)
        refs = {"activity_ids": keys, "sources": [run.source_refs for run in runs],
                "dependencies": [{"id": str(row.id), "dependency_hash": row.dependency_hash} for row in (rows[key] for key in sorted(rows))],
                "input_hash": sha256_json({"start": start, "end": end, "coverage_complete": complete})}
        return [_result(subject_key, outcome, refs, tz.key,
                        start=datetime.combine(start, time.min, tzinfo=tz).astimezone(UTC),
                        end=datetime.combine(end, time.min, tzinfo=tz).astimezone(UTC))]
    try:
        activity_id = UUID(subject_key)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_subject_key") from exc
    activity = session.get(Activity, activity_id)
    if activity is None or activity.sport not in ("running", "trail_running", "treadmill_running"):
        return []
    day = activity.start_at.astimezone(tz).date()
    run = next((r for r in load_runs(session, day, day + timedelta(days=1)) if r.activity_id == activity_id), None)
    refs = {**metric_source_refs(session, activity_id), "activity_ids": [str(activity_id)]}
    if run is None:
        outcome = {"status": "not_applicable", "quality_status": None, "value": None,
                   "reason_codes": ["ACTIVITY_EXCLUDED"], "quality_flags": [], "anchor_keys": []}
    else:
        row = session.get(ActivityStream, activity_id)
        stream = StreamIn(row.t_s, row.hr_bpm, row.speed_mps, [tuple(x) for x in row.timer_on],
                          tuple(row.quality_flags)) if row else None
        outcome = activity_outcome(stream, active_anchors(session, day), day, run.timer_s)
        refs["anchor_keys"] = outcome["anchor_keys"]
    return [_result(subject_key, outcome, refs, tz.key)]
