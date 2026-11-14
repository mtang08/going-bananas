"""Exception detector rules (exceptions.v1): pure functions over DetectionInputs."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.session_class import MISMATCH_MARGIN as MISMATCH_MARGIN
from app.domain.session_class import QUALITY_CLASSES, rpe_mismatch
from app.services.exceptions.facts import (
    BlockBenchmarkFact,
    Candidate,
    CheckinFact,
    DetectionInputs,
    EventFact,
    RpeRun,
    SessionFact,
    SymptomFact,
)
from app.services.exceptions.vocab import Category, Severity

SEVERITY_SUPPORT = 7.0
FATIGUE_HIGH = 7.0
OBSERVE_EXPIRY_DAYS = 14
EVENT_REVIEW_DAYS = 7
SYMPTOM_TRIGGER_DAYS = 7
CHECKIN_LOOKBACK_DAYS = 35
NEW_SITE_LOOKBACK_DAYS = 28
CONTEXT_WINDOW = timedelta(hours=12)
GAIT_REPEAT_GAP = timedelta(hours=20)
SUMMARY_MAX = 240
EVIDENCE_MAX = 8
TAG_LABELS = {'heat': 'heat', 'travel': 'travel', 'poor_sleep': 'poor sleep',
              'unusual_surface': 'unusual surface', 'equipment': 'equipment'}
Rule = Callable[[DetectionInputs], list[Candidate]]
Item = tuple[datetime, dict[str, Any]]


def _in_last(day: date, today: date, n: int) -> bool:
    return today - timedelta(days=n - 1) <= day <= today


def _ordered(inputs: DetectionInputs) -> list[CheckinFact]:
    return sorted(inputs.checkins, key=lambda c: (c.observed_at, c.recorded_at, c.id))


def _reports(inputs: DetectionInputs) -> list[tuple[CheckinFact, SymptomFact]]:
    return [(c, s) for c in _ordered(inputs) for s in c.symptoms]


def _local(inputs: DetectionInputs, day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), ZoneInfo(inputs.tz)).astimezone(UTC)


def _run_end(run: RpeRun) -> datetime:
    return run.end_at or run.start_at


def _run_time(run: RpeRun) -> datetime:
    return max(_run_end(run), run.rpe_at) if run.rpe_at is not None else _run_end(run)


def _session_time(s: SessionFact) -> datetime:
    return max(s.planned_at, s.completion_updated_at) if s.completion_updated_at is not None else s.planned_at


def _event_time(inputs: DetectionInputs, e: EventFact) -> datetime:
    return e.run_end_at if e.run_end_at is not None else _local(inputs, e.event_date, 23, 59)


def _d(day: date) -> str:
    return f"{day:%a %b} {day.day}"


def _n(x: float) -> str:
    return f"{x:g}"


def _site_label(site_key: str) -> str:
    site, side = site_key.rsplit('|', 1)
    return site if side == 'na' else f"{side} {site}"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _clock(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if seconds >= 3600 else f"{minutes}:{secs:02d}"


def _item(kind: str, item_id: str | None, at: datetime, detail: dict[str, Any]) -> Item:
    return at, {"type": kind, "id": item_id, "at": _iso(at), "detail": detail}


def _ev_checkin(c: CheckinFact) -> Item:
    return _item("checkin", c.id, c.observed_at, {"kind": c.kind, "fatigue": c.fatigue, "illness": c.illness,
                                                  "gait_change": c.gait_change, "context_tags": list(c.context_tags)})


def _ev_symptom(c: CheckinFact, s: SymptomFact) -> Item:
    return _item("symptom", s.id, c.observed_at, {"checkin_id": c.id, "site_key": s.site_key, "severity": s.severity,
                                                  "timing": s.timing, "activity_id": c.linked_activity_id})


def _ev_rpe(run: RpeRun, s: SessionFact, tags: set[str]) -> Item:
    return _item("rpe", run.activity_id, _run_time(run), {
        "rpe": run.rpe, "rpe_source": run.rpe_source, "session_uid": s.session_uid, "class": s.session_class,
        "expected_rpe": list(s.expected_rpe or ()), "local_date": run.local_date.isoformat(),
        "context_tags": sorted(tags)})


def _ev_session(s: SessionFact, reason: str | None = None) -> Item:
    return _item("session", s.session_uid, _session_time(s), {
        "local_date": s.local_date.isoformat(), "kind": s.kind, "class": s.session_class, "recipe_id": s.recipe_id,
        "completion_status": s.completion_status, "modification_reason": s.modification_reason, "reason": reason})


def _ev_night(inputs: DetectionInputs, day: date) -> Item:
    return _item("recovery_night", None, _local(inputs, day, 0, 0), {"local_date": day.isoformat()})


def _ev_event(inputs: DetectionInputs, e: EventFact) -> Item:
    return _item("event", e.id, _event_time(inputs, e), {"name": e.name, "event_date": e.event_date.isoformat(),
                                                        "priority": e.priority, "status": e.status,
                                                        "run_on_date": e.has_run_on_date})


def _ev_profile(inputs: DetectionInputs, at: datetime) -> Item:
    return _item("profile", None, at, {"clinician_restriction": inputs.clinician_restriction})


def _ev_block(b: BlockBenchmarkFact, at: datetime) -> Item:
    return _item("block", b.block_uid, at, {
        "version": b.version, "status": b.status, "kind": b.kind,
        "planned_date": b.planned_date.isoformat() if b.planned_date else None,
        "protocol": b.protocol, "review_date": b.review_date.isoformat()})


def _ev_benchmark(b: BlockBenchmarkFact, at: datetime) -> Item:
    return _item("activity", b.activity_id, at, {
        "block_uid": b.block_uid, "version": b.version, "match_method": b.match_method, "event_id": b.event_id,
        "local_date": b.local_date.isoformat() if b.local_date else None, "distance_m": b.distance_m,
        "result_s": b.result_s, "rpe": b.rpe})


def _candidate(code: str, category: Category, severity: Severity, entity_key: str, items: list[Item],
               summary: str) -> Candidate:
    evidence_at = max(at for at, detail in items if detail["type"] != "recovery_night")
    ordered = sorted(items, key=lambda i: (i[0], i[1]["id"] or ""), reverse=True)
    text = summary if len(summary) <= SUMMARY_MAX else summary[:SUMMARY_MAX - 1] + "…"
    return Candidate(code, category, severity, entity_key, evidence_at, [d for _, d in ordered[:EVIDENCE_MAX]], text)


def _mismatches(inputs: DetectionInputs) -> list[tuple[RpeRun, SessionFact, str]]:
    sessions = {s.session_uid: s for s in inputs.sessions}
    result: list[tuple[RpeRun, SessionFact, str]] = []
    for run in inputs.runs:
        s = sessions.get(run.session_uid) if run.session_uid else None
        kind = rpe_mismatch(s.session_class, s.recipe_id, run.rpe) if s is not None else None
        if s is not None and kind is not None:
            result.append((run, s, kind))
    return result


def _tags_near(inputs: DetectionInputs, run: RpeRun) -> set[str]:
    end = _run_end(run)
    return {t for c in inputs.checkins if abs(c.observed_at - end) <= CONTEXT_WINDOW for t in c.context_tags}


def _failed(inputs: DetectionInputs) -> list[tuple[SessionFact, str]]:
    result: list[tuple[SessionFact, str]] = []
    for s in sorted(inputs.sessions, key=lambda x: (x.local_date, x.session_uid)):
        if (s.certainty != 'committed' or s.session_class not in QUALITY_CLASSES
                or not _in_last(s.local_date, inputs.today, 14)):
            continue
        planned = inputs.planned_actual.get(s.session_uid)
        if s.completion_status == 'partial':
            result.append((s, 'partial'))
        elif s.completion_status == 'completed_modified' and s.modification_reason in {'symptom_onset', 'fatigue'}:
            result.append((s, 'modified'))
        elif planned is not None and planned.target_coverage == 'not_met':
            result.append((s, 'target'))
    return result


def _missed(inputs: DetectionInputs, s: SessionFact) -> bool:
    if s.certainty != 'committed':
        return False
    if not inputs.today - timedelta(days=7) <= s.local_date <= inputs.today - timedelta(days=1):
        return False
    if s.completion_status in {'skipped', 'unknown'}:
        return True
    planned = inputs.planned_actual.get(s.session_uid)
    return s.completion_status is None and planned is not None and 'NO_ACTIVITY_FOUND' in planned.reason_codes


RULES: tuple[tuple[str, Rule], ...] = ()


def detect(inputs: DetectionInputs) -> list[Candidate]:
    return [candidate for _, rule in RULES for candidate in rule(inputs)]
