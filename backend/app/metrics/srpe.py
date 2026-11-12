"""Session RPE load with explicit missingness and source precedence."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.checkin_models import SessionRpe
from app.domain.analytics import utc_date_bounds
from app.metrics.contract import MetricResultData, QualityStatus, Status, config_hash, coverage_label, sha256_json
from app.metrics.engine import activities_coverage_complete, load_runs, metric_source_refs, register
from app.models import Activity, ManualSession, RawObject, SourceRecord
from app.services.timezone import athlete_tz
from app.strong_models import StrongWorkoutRow

METRIC_ID = "session_rpe_load"
METHOD_VERSION = "v1"
WINDOW_DAYS = (7, 14, 28, 56, 84)
DEPENDS_ON: tuple[str, ...] = ()
CONFIG = {"rpe_precedence": ["manual", "garmin_fit"], "rpe_range": [0, 10],
          "duration_fields": {"run": "activities.timer_s", "strong": "strong_workouts.duration_s",
                              "manual": "manual_sessions.duration_s"}, "load_formula": "rpe_x_duration_min",
          "window_days": [7, 14, 28, 56, 84], "strength_sources": ["strong", "manual"]}
RUN_SPORTS = ("running", "trail_running", "treadmill_running")


@dataclass(frozen=True)
class RpeFact:
    subject_key: str
    kind: str
    local_date: date
    duration_s: float | None
    manual_rpe: float | None
    garmin_rpe: float | None
    manual_delay_s: int | None
    garmin_delay_s: int | None


def effective_rpe(f: RpeFact) -> tuple[float | None, str | None, float | None, int | None, bool]:
    if f.manual_rpe is not None:
        return f.manual_rpe, "manual", f.garmin_rpe, f.manual_delay_s, (
            f.garmin_rpe is not None and f.manual_rpe != f.garmin_rpe)
    if f.garmin_rpe is not None:
        return f.garmin_rpe, "garmin_fit", None, f.garmin_delay_s, False
    return None, None, None, None, False


def session_outcome(f: RpeFact) -> dict:
    rpe, source, other, delay, conflict = effective_rpe(f)
    invalid = rpe is not None and (not math.isfinite(rpe) or not 0 <= rpe <= 10)
    duration = f.duration_s if f.duration_s is not None and math.isfinite(f.duration_s) and f.duration_s >= 0 else None
    reasons = (["RPE_OUT_OF_RANGE"] if invalid else
               (["RPE_MISSING"] if rpe is None else []) +
               (["DURATION_MISSING"] if duration is None else []))
    flags = ["RPE_SOURCE_CONFLICT"] if conflict else []
    status = "invalid" if invalid else "missing" if reasons else "available"
    value = {"kind": f.kind, "duration_s": round(duration, 1) if duration is not None else None,
             "duration_min": round(duration / 60, 1) if duration is not None else None,
             "rpe": rpe if rpe is None or math.isfinite(rpe) else None, "rpe_source": source,
             "other_source_rpe": other if other is None or math.isfinite(other) else None,
             "collection_delay_s": delay,
             "load_au": round(rpe * duration / 60, 1)
             if status == "available" and rpe is not None and duration is not None else None}
    return {"status": status, "quality_status": ("limited" if flags else "good") if status == "available" else None,
            "value": value, "reason_codes": reasons, "quality_flags": flags}


def window_outcome(facts: list[RpeFact], strength_overlap_dates: list[date], coverage_complete: bool) -> dict:
    outcomes = [session_outcome(f) for f in facts]
    with_rpe = sum(o["value"]["rpe"] is not None and o["status"] != "invalid" for o in outcomes)
    durations = [f.duration_s if f.duration_s is not None and math.isfinite(f.duration_s) and f.duration_s >= 0
                 else None for f in facts]
    duration_total = sum(d for d in durations if d is not None)
    duration_known = sum(f.duration_s for f, o in zip(facts, outcomes)
                         if f.duration_s is not None and o["value"]["load_au"] is not None)
    raw_loads = [f.duration_s * o["value"]["rpe"] / 60 for f, o in zip(facts, outcomes)
                 if f.duration_s is not None and o["value"]["load_au"] is not None]
    missing = sum(o["status"] != "available" for o in outcomes)
    reasons = ["SESSIONS_WITHOUT_LOAD"] if missing else []
    if not coverage_complete:
        reasons.append("SYNC_COVERAGE_INCOMPLETE")
    value = {"load_au": round(sum(raw_loads), 1) if raw_loads else (0.0 if not facts and coverage_complete else None),
             "sessions_total": len(facts), "sessions_with_rpe": with_rpe,
             "sessions_without_load": sum(o["value"]["load_au"] is None for o in outcomes),
             "sessions_missing_duration": sum(d is None for d in durations),
             "duration_total_s": round(duration_total, 1) if any(d is not None for d in durations)
             or coverage_complete and not facts else None,
             "duration_with_rpe_s": round(duration_known, 1) if any(d is not None for d in durations)
             or coverage_complete and not facts else None,
             "coverage_duration": round(duration_known / duration_total, 3)
             if duration_total and all(d is not None for d in durations) else None,
             "coverage_sessions": round(with_rpe / len(facts), 3) if facts else None}
    quality = (coverage_label(duration_known, duration_total) if duration_total and
               all(d is not None for d in durations) else
               coverage_label(with_rpe, len(facts)) if facts else None)
    if facts and missing and quality == QualityStatus.good:
        quality = QualityStatus.limited
    return {"status": "partial" if facts and reasons else "missing" if reasons else "available",
            "quality_status": quality.value if quality else None,
            "value": value, "reason_codes": reasons,
            "quality_flags": ["STRENGTH_SOURCE_OVERLAP"] if strength_overlap_dates else []}


def _rpe_rows(session: Session, field: str, id_: UUID) -> list[SessionRpe]:
    return list(session.scalars(select(SessionRpe).where(getattr(SessionRpe, field) == id_)
                                .order_by(SessionRpe.source, SessionRpe.id)).all())


def _fact(key: str, kind: str, day: date, duration: float | None, rows: list[SessionRpe]) -> RpeFact:
    sources = {row.source: row for row in rows}
    manual = sources.get("manual")
    garmin = sources.get("garmin_fit") if kind == "run" else None
    return RpeFact(key, kind, day, duration, manual.rpe if manual else None, garmin.rpe if garmin else None,
                   manual.collection_delay_s if manual else None, garmin.collection_delay_s if garmin else None)


def _result(key: str, outcome: dict, refs: dict, timezone: str, start: datetime | None,
            end: datetime | None, *, is_window: bool = False, label: str | None = None) -> MetricResultData:
    return MetricResultData(METRIC_ID, METHOD_VERSION, "window" if is_window else "activity", key,
                            Status(outcome["status"]), tuple(outcome["reason_codes"]),
                            tuple(outcome["quality_flags"]), refs, (), config_hash(CONFIG),
                            window_start=start, window_end=end,
                            window_label=key if is_window else label,
                            quality_status=QualityStatus(outcome["quality_status"]) if outcome["quality_status"] else None,
                            value=outcome["value"], unit="AU", timezone=timezone)


def _strong_refs(session: Session, row: StrongWorkoutRow) -> dict:
    source = session.get(SourceRecord, row.source_record_id)
    raw = session.get(RawObject, row.raw_object_id)
    return {"strong_workout_id": str(row.id), "payload_hash": row.payload_hash,
            "source_record_id": str(row.source_record_id), "source_payload_hash": source.payload_hash if source else None,
            "source_parser_version": source.parser_version if source else None,
            "raw_object_id": str(row.raw_object_id), "raw_sha256": raw.sha256 if raw else None}


def _session_data(session: Session, prefix: str, id_: UUID, tz) -> tuple[RpeFact, dict, datetime, datetime | None] | None:
    if prefix == "strong":
        row = session.get(StrongWorkoutRow, id_)
        if row is None:
            return None
        start = datetime.fromisoformat(row.local_start).replace(tzinfo=tz).astimezone(UTC)
        end = start + timedelta(seconds=row.duration_s) if row.duration_s is not None else None
        rpes = _rpe_rows(session, "strong_workout_id", id_)
        refs = _strong_refs(session, row)
        fact = _fact(f"strong:{id_}", "strength", row.local_date, row.duration_s, rpes)
        if row.resolution_state != "resolved":
            refs["excluded"] = True
    else:
        manual_row = session.get(ManualSession, id_)
        if manual_row is None or manual_row.kind != "strength" or manual_row.linked_activity_id is not None:
            return None
        if manual_row.time is None:
            start, end = utc_date_bounds(manual_row.date, manual_row.date, tz.key)
        else:
            start = datetime.combine(manual_row.date, manual_row.time, tz).astimezone(UTC)
            end = start + timedelta(seconds=manual_row.duration_s) if manual_row.duration_s is not None else None
        rpes = _rpe_rows(session, "manual_session_id", id_)
        refs = {"manual_session_id": str(id_), "version": manual_row.version,
                "source_revision": sha256_json({"version": manual_row.version, "date": manual_row.date.isoformat(),
                                                 "time": manual_row.time.isoformat() if manual_row.time else None,
                                                 "duration_s": manual_row.duration_s, "kind": manual_row.kind,
                                                 "linked_activity_id": str(manual_row.linked_activity_id)
                                                 if manual_row.linked_activity_id else None})}
        fact = _fact(f"manual:{id_}", "strength", manual_row.date, manual_row.duration_s, rpes)
    refs["session_rpe_ids"] = [str(r.id) for r in rpes]
    refs["session_rpe"] = [{"id": str(r.id), "source": r.source, "rpe": r.rpe,
                            "collection_delay_s": r.collection_delay_s, "collected_at": r.collected_at.isoformat()}
                           for r in rpes]
    return fact, refs, start, end


@register(METRIC_ID, METHOD_VERSION, DEPENDS_ON)
def compute(session: Session, subject_key: str) -> list[MetricResultData]:
    tz = athlete_tz(session)
    match = re.fullmatch(r"w(\d+):(\d{4}-\d{2}-\d{2})", subject_key)
    if match:
        try:
            days, as_of = int(match[1]), date.fromisoformat(match[2])
        except ValueError as exc:
            raise ValueError("invalid_subject_key") from exc
        if days not in WINDOW_DAYS:
            raise ValueError("invalid_subject_key")
        first = as_of - timedelta(days=days - 1)
        start, window_end = utc_date_bounds(first, as_of, tz.key)
        runs = load_runs(session, first, as_of + timedelta(days=1))
        strong = session.scalars(select(StrongWorkoutRow).where(StrongWorkoutRow.resolution_state == "resolved",
                            StrongWorkoutRow.local_date >= first, StrongWorkoutRow.local_date <= as_of)
                                 .order_by(StrongWorkoutRow.local_date, StrongWorkoutRow.id)).all()
        manual = session.scalars(select(ManualSession).where(ManualSession.kind == "strength",
                            ManualSession.linked_activity_id.is_(None), ManualSession.date >= first,
                            ManualSession.date <= as_of).order_by(ManualSession.date, ManualSession.id)).all()
        run_items = []
        for run in runs:
            rpes = _rpe_rows(session, "activity_id", run.activity_id)
            run_items.append((_fact(str(run.activity_id), "run", run.local_date, run.timer_s, rpes),
                              {**metric_source_refs(session, run.activity_id), "session_rpe_ids": [str(r.id) for r in rpes],
                               "session_rpe": [{"id": str(r.id), "rpe": r.rpe, "source": r.source,
                                                "collection_delay_s": r.collection_delay_s,
                                                "collected_at": r.collected_at.isoformat()} for r in rpes]}))
        strength_items = [_session_data(session, "strong", r.id, tz) for r in strong]
        strength_items += [_session_data(session, "manual", r.id, tz) for r in manual]
        overlap = sorted({r.local_date for r in strong} & {r.date for r in manual})
        results = []
        for kind, items in (("run", run_items), ("strength", [(x[0], x[1]) for x in strength_items if x])):
            facts = [x[0] for x in items]
            coverage_complete = (activities_coverage_complete(session, first, as_of + timedelta(days=1))
                                 if kind == "run" else False)
            refs = {"subject_keys": [f.subject_key for f in facts], "sources": [x[1] for x in items],
                    "coverage_complete": coverage_complete,
                    "input_hash": sha256_json({"sources": [x[1] for x in items],
                                               "coverage_complete": coverage_complete})}
            outcome = window_outcome(facts, overlap if kind == "strength" else [], coverage_complete)
            results.append(_result(f"w{days}:{as_of}:{kind}", outcome, refs, tz.key, start, window_end, is_window=True))
        return results
    prefix = ""
    raw_id = subject_key
    if subject_key.startswith(("strong:", "manual:")):
        prefix, raw_id = subject_key.split(":", 1)
    try:
        id_ = UUID(raw_id)
    except ValueError as exc:
        raise ValueError("invalid_subject_key") from exc
    if prefix:
        data = _session_data(session, prefix, id_, tz)
        if data is None:
            return []
        fact, refs, start, end = data
        outcome = ({"status": "not_applicable", "quality_status": None, "value": None,
                    "reason_codes": ["ACTIVITY_EXCLUDED"], "quality_flags": []}
                   if refs.get("excluded") else session_outcome(fact))
        return [_result(subject_key, outcome, refs, tz.key, start, end, label=fact.local_date.isoformat())]
    row = session.get(Activity, id_)
    if row is None or row.sport not in RUN_SPORTS:
        return []
    day = row.start_at.astimezone(tz).date()
    run_fact = next((r for r in load_runs(session, day, day + timedelta(days=1)) if r.activity_id == id_), None)
    rpes = _rpe_rows(session, "activity_id", id_)
    refs = {**metric_source_refs(session, id_), "activity_id": str(id_),
            "session_rpe_ids": [str(r.id) for r in rpes],
            "session_rpe": [{"id": str(r.id), "rpe": r.rpe, "source": r.source,
                             "collection_delay_s": r.collection_delay_s, "collected_at": r.collected_at.isoformat()} for r in rpes]}
    outcome = session_outcome(_fact(subject_key, "run", day, run_fact.timer_s, rpes)) if run_fact else {
        "status": "not_applicable", "quality_status": None, "value": None,
        "reason_codes": ["ACTIVITY_EXCLUDED"], "quality_flags": []}
    return [_result(subject_key, outcome, refs, tz.key, row.start_at, row.end_at, label=day.isoformat())]
