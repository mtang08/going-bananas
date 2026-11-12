"""Symptom reports linked to actual run ends, without inferred end times."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.checkin_models import Checkin, SymptomReport
from app.domain.analytics import utc_date_bounds
from app.domain.associations import preceding_sessions
from app.metrics.contract import MetricResultData, Status, config_hash, sha256_json
from app.metrics.engine import load_runs, metric_source_refs, register
from app.models import Activity
from app.services.timezone import athlete_tz

METRIC_ID = "symptom_response_timeline"
METHOD_VERSION = "v1"
WINDOW_DAYS = (28,)
DEPENDS_ON: tuple[str, ...] = ()
LINK_HOURS = 48
CONFIG: dict[str, object] = {"link_hours": 48, "link_rule": "activity_id_else_associations.preceding_sessions_first",
          "recurrence_lookback_days": 28,
          "bucket_0_24": ["during", "immediately_after", "next_morning"],
          "bucket_24_48": ["hours_24_48"], "bucket_later": ["later"],
          "unknown_timing_rule": "by_hours_after_end", "site_normalization": "strip_lower",
          "gait_order": ["yes", "unsure", "no", "unknown"]}
RUN_SPORTS = ("running", "trail_running", "treadmill_running")


@dataclass(frozen=True)
class ReportIn:
    checkin_id: str
    observed_at: datetime
    kind: str
    gait_change: str | None
    site: str
    side: str
    severity: float
    timing: str


@dataclass(frozen=True)
class CheckinIn:
    checkin_id: str
    observed_at: datetime
    kind: str
    gait_change: str | None
    reports: list[ReportIn]


def run_end(start_at: datetime, end_at: datetime | None, timer_s: float | None) -> tuple[datetime | None, bool]:
    return (end_at, False) if end_at is not None else (None, True)


def linked_activity_for_checkin(session: Session, checkin: Checkin) -> UUID | None:
    if checkin.activity_id is not None:
        return checkin.activity_id
    tz = athlete_tz(session)
    day = checkin.observed_at.astimezone(tz).date()
    runs = load_runs(session, day - timedelta(days=3), day + timedelta(days=1))
    known = [r for r in runs if r.end_at is not None]
    known.sort(key=lambda r: str(r.activity_id))
    known.sort(key=lambda r: r.end_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    candidates = [{"id": r.activity_id, "start_at": r.start_at,
                   "elapsed_s": (r.end_at - r.start_at).total_seconds() if r.end_at else None,
                   "sport": r.sport} for r in known]
    hits = preceding_sessions(checkin.observed_at, candidates, tz.key, hours=LINK_HOURS)
    return UUID(hits[0]["activity_id"]) if hits else None


def bucket(timing: str, hours: float | None) -> str:
    if timing in ("during", "immediately_after", "next_morning"):
        return "0_24"
    if timing == "hours_24_48":
        return "24_48"
    if timing == "later":
        return "later"
    if hours is None:
        return "unknown"
    return "0_24" if hours < 24 else "24_48" if hours <= 48 else "later"


def _reports(checkins: list[CheckinIn]) -> list[ReportIn]:
    return [report for checkin in sorted(checkins, key=lambda c: (c.observed_at, c.checkin_id))
            for report in checkin.reports]


def activity_outcome(end: datetime | None, end_unknown: bool, checkins: list[CheckinIn]) -> dict:
    flags = ["END_TIME_UNKNOWN"] if end_unknown else []
    if not checkins:
        return {"status": "missing", "quality_status": None, "value": None,
                "reason_codes": ["NO_LINKED_CHECKIN"], "quality_flags": flags}
    ordered = sorted(checkins, key=lambda c: (c.observed_at, c.checkin_id))
    if not any(c.kind == "delayed_followup" for c in ordered):
        flags.append("DELAYED_FOLLOWUP_MISSING")
    reports = []
    grouped: dict[tuple[str, str], list[dict]] = {}
    for report in _reports(ordered):
        hours = ((report.observed_at - end).total_seconds() / 3600) if end is not None else None
        category = bucket(report.timing, hours)
        item = {"checkin_id": report.checkin_id, "observed_at": report.observed_at.isoformat(),
                "kind": report.kind, "site": report.site, "side": report.side,
                "severity": round(report.severity, 1), "timing": report.timing,
                "gait_change": report.gait_change,
                "hours_after_end": round(hours, 1) if hours is not None else None}
        reports.append(item)
        grouped.setdefault((report.site.strip().lower(), report.side), []).append({**item, "_bucket": category})
    sites = []
    for (site, side), items in sorted(grouped.items()):
        in_0 = [r["severity"] for r in items if r["_bucket"] == "0_24"]
        in_24 = [r["severity"] for r in items if r["_bucket"] == "24_48"]
        latest = items[-1]
        sites.append({"site": site, "side": side, "max_severity_0_24h": max(in_0, default=None),
                      "max_severity_24_48h": max(in_24, default=None),
                      "latest_severity": latest["severity"], "latest_observed_at": latest["observed_at"],
                      "first_report_hours_after_end": items[0]["hours_after_end"]})
    gait = next((g for g in ("yes", "unsure", "no") if any(c.gait_change == g for c in ordered)), "unknown")
    return {"status": "available", "quality_status": "limited" if flags else "good",
            "value": {"activity_end_at": end.isoformat() if end else None,
                      "delayed_followup_answered": any(c.kind == "delayed_followup" for c in ordered),
                      "reports": reports, "sites": sites, "gait_change": gait},
            "reason_codes": [], "quality_flags": flags}


def window_outcome(checkins: list[CheckinIn], tz: ZoneInfo) -> dict:
    if not checkins:
        return {"status": "missing", "quality_status": None, "value": None,
                "reason_codes": ["NO_CHECKINS_IN_WINDOW"], "quality_flags": []}
    grouped: dict[tuple[str, str], list[ReportIn]] = {}
    for report in _reports(checkins):
        grouped.setdefault((report.site.strip().lower(), report.side), []).append(report)
    sites = []
    for (site, side), items in sorted(grouped.items()):
        latest = max(enumerate(items), key=lambda pair: (pair[1].observed_at, pair[0]))[1]
        sites.append({"site": site, "side": side, "report_count": len(items),
                      "recurrence_days": len({r.observed_at.astimezone(tz).date() for r in items if r.severity > 0}),
                      "max_severity": round(max(r.severity for r in items), 1),
                      "latest_severity": round(latest.severity, 1), "latest_timing": latest.timing,
                      "gait_change_reported": any(r.gait_change == "yes" for r in items)})
    return {"status": "available", "quality_status": None,
            "value": {"checkin_count": len(checkins), "sites": sites},
            "reason_codes": [], "quality_flags": []}


def _checkins(session: Session, rows: list[Checkin]) -> tuple[list[CheckinIn], dict]:
    facts = []
    refs = []
    for row in sorted(rows, key=lambda c: (c.observed_at, str(c.id))):
        reports = session.scalars(select(SymptomReport).where(SymptomReport.checkin_id == row.id)
                                  .order_by(SymptomReport.id)).all()
        facts.append(CheckinIn(str(row.id), row.observed_at, row.kind, row.gait_change,
                               [ReportIn(str(row.id), row.observed_at, row.kind, row.gait_change,
                                         r.site, r.side, r.severity, r.timing) for r in reports]))
        refs.append({"id": str(row.id), "version": row.version, "activity_id": str(row.activity_id) if row.activity_id else None,
                     "observed_at": row.observed_at.isoformat(), "kind": row.kind, "gait_change": row.gait_change,
                     "reports": [{"id": str(r.id), "site": r.site, "side": r.side,
                                  "severity": r.severity, "timing": r.timing} for r in reports]})
    return facts, {"checkin_ids": [f.checkin_id for f in facts], "checkins": refs,
                   "input_hash": sha256_json(refs)}


def _result(key: str, outcome: dict, refs: dict, tz: str, start: datetime | None,
            end: datetime | None, is_window: bool = False) -> MetricResultData:
    from app.metrics.contract import QualityStatus
    return MetricResultData(METRIC_ID, METHOD_VERSION, "window" if is_window else "activity", key,
                            Status(outcome["status"]), tuple(outcome["reason_codes"]),
                            tuple(outcome["quality_flags"]), refs, (), config_hash(CONFIG),
                            window_start=start, window_end=end,
                            window_label=key if is_window else None,
                            quality_status=QualityStatus(outcome["quality_status"]) if outcome["quality_status"] else None,
                            value=outcome["value"], unit=None, timezone=tz)


@register(METRIC_ID, METHOD_VERSION, DEPENDS_ON)
def compute(session: Session, subject_key: str) -> list[MetricResultData]:
    tz = athlete_tz(session)
    match = re.fullmatch(r"w(\d+):(\d{4}-\d{2}-\d{2})", subject_key)
    if match:
        try:
            days, as_of = int(match[1]), date.fromisoformat(match[2])
        except ValueError as exc:
            raise ValueError("invalid_subject_key") from exc
        if days != 28:
            raise ValueError("invalid_subject_key")
        first = as_of - timedelta(days=27)
        start, window_end = utc_date_bounds(first, as_of, tz.key)
        rows = session.scalars(select(Checkin).where(Checkin.observed_at >= start,
                            Checkin.observed_at < window_end).order_by(Checkin.observed_at, Checkin.id)).all()
        facts, refs = _checkins(session, list(rows))
        return [_result(subject_key, window_outcome(facts, tz), refs, tz.key, start, window_end, True)]
    try:
        id_ = UUID(subject_key)
    except ValueError as exc:
        raise ValueError("invalid_subject_key") from exc
    row = session.get(Activity, id_)
    if row is None or row.sport not in RUN_SPORTS:
        return []
    day = row.start_at.astimezone(tz).date()
    run = next((r for r in load_runs(session, day, day + timedelta(days=1)) if r.activity_id == id_), None)
    refs = {**metric_source_refs(session, id_), "activity_ids": [str(id_)]}
    if run is None:
        outcome = {"status": "not_applicable", "quality_status": None, "value": None,
                   "reason_codes": ["ACTIVITY_EXCLUDED"], "quality_flags": []}
        return [_result(subject_key, outcome, refs, tz.key, row.start_at, row.end_at)]
    end, unknown = run_end(run.start_at, run.end_at, run.timer_s)
    explicit = list(session.scalars(select(Checkin).where(Checkin.activity_id == id_)).all())
    implicit = []
    if end is not None:
        candidates = session.scalars(select(Checkin).where(Checkin.activity_id.is_(None),
                                     Checkin.observed_at >= end,
                                     Checkin.observed_at <= end + timedelta(hours=LINK_HOURS))).all()
        implicit = [c for c in candidates if linked_activity_for_checkin(session, c) == id_]
    facts, checkin_refs = _checkins(session, explicit + implicit)
    refs.update(checkin_refs)
    return [_result(subject_key, activity_outcome(end, unknown, facts), refs, tz.key, row.start_at, end)]
