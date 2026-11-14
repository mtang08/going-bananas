"""Exception detector rules (exceptions.v1): pure functions over DetectionInputs."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.session_class import HARD_CLASSES, QUALITY_CLASSES, rpe_mismatch
from app.domain.session_class import MISMATCH_MARGIN as MISMATCH_MARGIN
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


Report = tuple[CheckinFact, SymptomFact]


def _by_site(inputs: DetectionInputs) -> dict[str, list[Report]]:
    groups: dict[str, list[Report]] = {}
    for c, s in _reports(inputs):
        groups.setdefault(s.site_key, []).append((c, s))
    return groups


def _sym_new_site(inputs: DetectionInputs) -> list[Candidate]:
    out: list[Candidate] = []
    for key, reports in _by_site(inputs).items():
        new = [(c, s) for c, s in reports if _in_last(c.local_date, inputs.today, SYMPTOM_TRIGGER_DAYS)
               and not any(c.observed_at - timedelta(days=NEW_SITE_LOOKBACK_DAYS) <= oc.observed_at < c.observed_at
                           for oc, _ in reports)]
        if new:
            c, s = new[-1]
            sev: Severity = 'caution' if s.severity >= SEVERITY_SUPPORT else 'observe'
            out.append(_candidate('SYM_NEW_SITE', 'symptoms_illness', sev, f'site:{key}', [_ev_symptom(c, s)],
                                  f'New symptom: {_cap(_site_label(key))} at {_n(s.severity)}/10.'))
    return out


def _sym_worsening(inputs: DetectionInputs) -> list[Candidate]:
    out: list[Candidate] = []
    for key, reports in _by_site(inputs).items():
        found: tuple[Report, Report] | None = None
        for c, s in reports:
            if not _in_last(c.local_date, inputs.today, SYMPTOM_TRIGGER_DAYS):
                continue
            prior = [(pc, ps) for pc, ps in reports
                     if c.observed_at - timedelta(days=SYMPTOM_TRIGGER_DAYS) <= pc.observed_at < c.observed_at]
            if not prior:
                continue
            pc, ps = max(prior, key=lambda r: (r[0].observed_at, r[0].recorded_at, r[1].id))
            if s.severity > ps.severity:
                found = ((pc, ps), (c, s))
        if found:
            (pc, ps), (c, s) = found
            out.append(_candidate('SYM_WORSENING', 'symptoms_illness', 'caution', f'site:{key}',
                                  [_ev_symptom(pc, ps), _ev_symptom(c, s)],
                                  f'{_cap(_site_label(key))} symptom rose from {_n(ps.severity)} to '
                                  f'{_n(s.severity)}/10 within 7 days.'))
    return out


_PERSIST_WHEN = {'next_morning': 'the next morning', 'hours_24_48': '24–48 hours later'}


def _sym_persisting(inputs: DetectionInputs) -> list[Candidate]:
    out: list[Candidate] = []
    for key, reports in _by_site(inputs).items():
        found: tuple[Report, Report] | None = None
        for lc, ls in reports:
            if not _in_last(lc.local_date, inputs.today, SYMPTOM_TRIGGER_DAYS) or ls.timing not in _PERSIST_WHEN:
                continue
            earlier = [(ec, es) for ec, es in reports if ec.observed_at < lc.observed_at
                       and es.timing in {'during', 'immediately_after'}
                       and ec.linked_activity_id is not None and ec.linked_activity_id == lc.linked_activity_id]
            if earlier:
                found = (earlier[-1], (lc, ls))
        if found:
            (ec, es), (lc, ls) = found
            out.append(_candidate('SYM_PERSISTING', 'symptoms_illness', 'caution', f'site:{key}',
                                  [_ev_symptom(ec, es), _ev_symptom(lc, ls)],
                                  f'{_cap(_site_label(key))} symptom from a run was still present '
                                  f'{_PERSIST_WHEN[ls.timing]} ({_n(ls.severity)}/10).'))
    return out


def _sym_recurrent(inputs: DetectionInputs) -> list[Candidate]:
    out: list[Candidate] = []
    for key, reports in _by_site(inputs).items():
        recent = [(c, s) for c, s in reports if _in_last(c.local_date, inputs.today, 14)]
        days = {c.local_date for c, _ in recent}
        if len(days) >= 3:
            out.append(_candidate('SYM_RECURRENT', 'symptoms_illness', 'caution', f'site:{key}',
                                  [_ev_symptom(c, s) for c, s in recent],
                                  f'{_cap(_site_label(key))} symptom reported on {len(days)} days in the last 14 days.'))
    return out


def _sym_multiweek(inputs: DetectionInputs) -> list[Candidate]:
    out: list[Candidate] = []
    today = inputs.today
    for key, reports in _by_site(inputs).items():
        recent = [(c, s) for c, s in reports if today - timedelta(days=20) <= c.local_date <= today]
        periods = {(today - c.local_date).days // 7 for c, _ in recent}
        if {0, 1, 2} <= periods:
            out.append(_candidate('SYM_MULTIWEEK', 'symptoms_illness', 'escalate', f'site:{key}',
                                  [_ev_symptom(c, s) for c, s in recent],
                                  f'{_cap(_site_label(key))} symptom reported in each of the last three 7-day periods.'))
    return out


def _gait_change(inputs: DetectionInputs) -> list[Candidate]:
    checks = [c for c in _ordered(inputs) if c.gait_change == 'yes' and _in_last(c.local_date, inputs.today, 3)]
    if not checks:
        return []
    return [_candidate('GAIT_CHANGE', 'symptoms_illness', 'hold', 'gait', [_ev_checkin(c) for c in checks],
                       f'Gait change reported on {_d(checks[-1].local_date)}.')]


def _gait_persisting(inputs: DetectionInputs) -> list[Candidate]:
    checks = [c for c in _ordered(inputs) if c.gait_change == 'yes' and _in_last(c.local_date, inputs.today, 7)]
    if len(checks) < 2 or checks[-1].observed_at - checks[0].observed_at < GAIT_REPEAT_GAP:
        return []
    return [_candidate('GAIT_PERSISTING', 'symptoms_illness', 'escalate', 'gait', [_ev_checkin(c) for c in checks],
                       f'Gait change reported on {len(checks)} check-ins at least 20 hours apart in the last 7 days.')]


def _latest_illness(inputs: DetectionInputs, days: int) -> CheckinFact | None:
    known = [c for c in _ordered(inputs) if c.illness is not None and _in_last(c.local_date, inputs.today, days)]
    return known[-1] if known else None


def _illness_possible(inputs: DetectionInputs) -> list[Candidate]:
    c = _latest_illness(inputs, 2)
    if c is None or c.illness != 'possible':
        return []
    return [_candidate('ILLNESS_POSSIBLE', 'symptoms_illness', 'caution', 'illness', [_ev_checkin(c)],
                       f'Possible illness reported on {_d(c.local_date)}.')]


def _illness_present(inputs: DetectionInputs) -> list[Candidate]:
    c = _latest_illness(inputs, 3)
    if c is None or c.illness != 'present':
        return []
    return [_candidate('ILLNESS_PRESENT', 'symptoms_illness', 'hold', 'illness', [_ev_checkin(c)],
                       f'Illness reported on {_d(c.local_date)}.')]


def _illness_prolonged(inputs: DetectionInputs) -> list[Candidate]:
    checks = [c for c in _ordered(inputs) if c.illness == 'present' and _in_last(c.local_date, inputs.today, 10)]
    if not checks:
        return []
    first, last = min(c.local_date for c in checks), max(c.local_date for c in checks)
    if (last - first).days < 6:
        return []
    return [_candidate('ILLNESS_PROLONGED', 'symptoms_illness', 'escalate', 'illness', [_ev_checkin(c) for c in checks],
                       f'Illness reported from {_d(first)} to {_d(last)}.')]


def _clinician_restriction(inputs: DetectionInputs) -> list[Candidate]:
    v = inputs.clinician_restriction
    if v is None or inputs.clinician_restriction_at is None:
        return []
    return [_candidate('CLINICIAN_RESTRICTION', 'symptoms_illness', 'escalate', 'clinician_restriction',
                       [_ev_profile(inputs, inputs.clinician_restriction_at)], f'Clinician restriction on file: {v[:160]}.')]


def _tag_text(tags: set[str]) -> str:
    return _cap(", ".join(TAG_LABELS.get(t, t) for t in sorted(tags)))


def _above(inputs: DetectionInputs, days: int, classes: frozenset[str] | None = None) -> list[tuple[RpeRun, SessionFact]]:
    return [(r, s) for r, s, kind in _mismatches(inputs) if kind == 'above' and _in_last(r.local_date, inputs.today, days)
            and (classes is None or s.session_class in classes)]


_EASY_LONG = frozenset({'easy', 'long'})
_WHY = {'partial': 'partial', 'target': 'target not met'}


def _rpe_above_intent(inputs: DetectionInputs) -> list[Candidate]:
    out: list[Candidate] = []
    for r, s in _above(inputs, 14):
        if s.expected_rpe is None or r.rpe is None:
            continue
        tags = _tags_near(inputs, r)
        lo, hi = s.expected_rpe
        summary = f'{_cap(s.session_class)} run felt RPE {_n(r.rpe)} (expected {_n(lo)}–{_n(hi)}).'
        if tags:
            summary += f' {_tag_text(tags)} reported.'
        out.append(_candidate('RPE_ABOVE_INTENT', 'training_response', 'observe', f'activity:{r.activity_id}',
                              [_ev_rpe(r, s, tags)], summary))
    return out


def _rpe_above_intent_repeated(inputs: DetectionInputs) -> list[Candidate]:
    above = _above(inputs, 7, _EASY_LONG)
    if len(above) < 2:
        return []
    return [_candidate('RPE_ABOVE_INTENT_REPEATED', 'training_response', 'caution', 'rpe_easy_long',
                       [_ev_rpe(r, s, _tags_near(inputs, r)) for r, s in above],
                       f'{len(above)} easy or long runs felt harder than intended in the last 7 days.')]


def _why(s: SessionFact, reason: str) -> str:
    if reason == 'modified':
        return f"modified for {(s.modification_reason or '').replace('_', ' ')}"
    return _WHY[reason]


def _session_failed(inputs: DetectionInputs) -> list[Candidate]:
    return [_candidate('SESSION_FAILED', 'training_response', 'observe', f'session:{s.session_uid}',
                       [_ev_session(s, reason)],
                       f'{_cap(s.session_class)} session on {_d(s.local_date)} was not completed as planned '
                       f'({_why(s, reason)}).')
            for s, reason in _failed(inputs)]


def _session_failed_repeated(inputs: DetectionInputs) -> list[Candidate]:
    failed = _failed(inputs)
    if len(failed) < 2:
        return []
    return [_candidate('SESSION_FAILED_REPEATED', 'training_response', 'caution', 'quality_failed',
                       [_ev_session(s, reason) for s, reason in failed],
                       f'{len(failed)} quality sessions were not completed as planned in the last 14 days.')]


def _response_multiweek(inputs: DetectionInputs) -> list[Candidate]:
    today = inputs.today
    above = _above(inputs, 14, _EASY_LONG)
    failed = _failed(inputs)
    items: list[Item] = []
    for first, last in ((today - timedelta(days=6), today), (today - timedelta(days=13), today - timedelta(days=7))):
        runs = [(r, s) for r, s in above if first <= r.local_date <= last]
        sessions = [(s, reason) for s, reason in failed if first <= s.local_date <= last]
        if len(runs) < 2 and len(sessions) < 2:
            return []
        if len(runs) >= 2:
            items += [_ev_rpe(r, s, _tags_near(inputs, r)) for r, s in runs]
        if len(sessions) >= 2:
            items += [_ev_session(s, reason) for s, reason in sessions]
    return [_candidate('RESPONSE_MULTIWEEK', 'training_response', 'escalate', 'training_response', items,
                       'Training response flags repeated in both of the last two 7-day periods.')]


def _high_fatigue(inputs: DetectionInputs, days: int) -> list[CheckinFact]:
    return [c for c in _ordered(inputs)
            if c.fatigue is not None and c.fatigue >= FATIGUE_HIGH and _in_last(c.local_date, inputs.today, days)]


def _fatigue_high(inputs: DetectionInputs) -> list[Candidate]:
    rows = _high_fatigue(inputs, 2)
    if not rows:
        return []
    latest = rows[-1]
    return [_candidate('FATIGUE_HIGH', 'accumulated_fatigue', 'observe', 'fatigue', [_ev_checkin(c) for c in rows],
                       f'High fatigue ({_n(latest.fatigue or 0)}/10) reported on {_d(latest.local_date)}.')]


def _fatigue_persisting(inputs: DetectionInputs) -> list[Candidate]:
    rows = _high_fatigue(inputs, 4)
    days = {c.local_date for c in rows}
    if len(days) < 2:
        return []
    return [_candidate('FATIGUE_PERSISTING', 'accumulated_fatigue', 'caution', 'fatigue_persisting',
                       [_ev_checkin(c) for c in rows], f'High fatigue reported on {len(days)} days in the last 4 days.')]


_SIGNAL_LABELS = (('fatigue_high', 'high fatigue'), ('rpe_above', 'run harder than intended'),
                  ('poor_sleep', 'poor sleep'), ('travel', 'travel'), ('adverse_recovery', 'recovery markers off'),
                  ('illness_possible', 'possible illness'))


def _signals_converging(inputs: DetectionInputs) -> list[Candidate]:
    recent = [c for c in _ordered(inputs) if _in_last(c.local_date, inputs.today, 4)]
    nights = sorted(d for d in inputs.recovery_adverse_dates if _in_last(d, inputs.today, 4))
    found: dict[str, list[Item]] = {
        'fatigue_high': [_ev_checkin(c) for c in _high_fatigue(inputs, 4)],
        'rpe_above': [_ev_rpe(r, s, _tags_near(inputs, r)) for r, s in _above(inputs, 4)],
        'poor_sleep': [_ev_checkin(c) for c in recent if 'poor_sleep' in c.context_tags],
        'travel': [_ev_checkin(c) for c in recent if 'travel' in c.context_tags],
        'adverse_recovery': [_ev_night(inputs, d) for d in nights] if len(nights) >= 2 else [],
        'illness_possible': [_ev_checkin(c) for c in recent if c.illness == 'possible'],
    }
    present = [(name, label) for name, label in _SIGNAL_LABELS if found[name]]
    names = {name for name, _ in present}
    if len(present) < 2 or not names & {'fatigue_high', 'rpe_above'}:
        return []
    unique = {(d['type'], d['id'], d['at']): (at, d) for name, _ in present for at, d in found[name]}
    return [_candidate('SIGNALS_CONVERGING', 'accumulated_fatigue', 'caution', 'converging', list(unique.values()),
                       f"Signals converging in the last 4 days: {', '.join(label for _, label in present)}.")]


def _fatigue_prolonged(inputs: DetectionInputs) -> list[Candidate]:
    rows = _high_fatigue(inputs, 10)
    days = {c.local_date for c in rows}
    if len(days) < 4:
        return []
    return [_candidate('FATIGUE_PROLONGED', 'accumulated_fatigue', 'hold', 'fatigue_prolonged',
                       [_ev_checkin(c) for c in rows], f'High fatigue reported on {len(days)} days in the last 10 days.')]


def _by_date(inputs: DetectionInputs) -> list[SessionFact]:
    return sorted(inputs.sessions, key=lambda s: (s.local_date, s.session_uid))


def _key_session_missed(inputs: DetectionInputs) -> list[Candidate]:
    return [_candidate('KEY_SESSION_MISSED', 'calendar_disruption', 'observe', f'session:{s.session_uid}',
                       [_ev_session(s)], f'{_cap(s.session_class)} session on {_d(s.local_date)} was missed.')
            for s in _by_date(inputs) if s.session_class in HARD_CLASSES and _missed(inputs, s)]


def _runs_missed_repeated(inputs: DetectionInputs) -> list[Candidate]:
    missed = [s for s in _by_date(inputs) if s.kind == 'run' and _missed(inputs, s)]
    if len(missed) < 2:
        return []
    return [_candidate('RUNS_MISSED_REPEATED', 'calendar_disruption', 'caution', 'runs_missed',
                       [_ev_session(s) for s in missed], f'{len(missed)} planned runs were missed in the last 7 days.')]


_DONE = frozenset({'completed_as_planned', 'completed_modified', 'partial'})


def _hard_spacing_tight(inputs: DetectionInputs) -> list[Candidate]:
    today = inputs.today
    yesterday = today - timedelta(days=1)
    eligible = [s for s in _by_date(inputs)
                if s.session_class in HARD_CLASSES and yesterday <= s.local_date <= today + timedelta(days=6)
                and (s.completion_status in _DONE if s.local_date == yesterday else s.completion_status != 'skipped')]
    out: list[Candidate] = []
    for i, a in enumerate(eligible):
        for b in eligible[i + 1:]:
            if (b.local_date - a.local_date).days <= 1:
                low, high = sorted((a.session_uid, b.session_uid))
                out.append(_candidate('HARD_SPACING_TIGHT', 'calendar_disruption', 'caution', f'spacing:{low}:{high}',
                                      [_ev_session(a), _ev_session(b)],
                                      f'Hard sessions on {_d(a.local_date)} and {_d(b.local_date)} are within one day '
                                      'of each other.'))
    return out


def _travel_reported(inputs: DetectionInputs) -> list[Candidate]:
    rows = [c for c in _ordered(inputs) if 'travel' in c.context_tags and _in_last(c.local_date, inputs.today, 2)]
    if not rows:
        return []
    return [_candidate('TRAVEL_REPORTED', 'calendar_disruption', 'observe', 'travel', [_ev_checkin(c) for c in rows],
                       f'Travel reported on {_d(rows[-1].local_date)}.')]


def _block_benchmark_missing(inputs: DetectionInputs) -> list[Candidate]:
    b = inputs.block_benchmark
    if b is None or b.status != 'not_set':
        return []
    return [_candidate('BLOCK_BENCHMARK_MISSING', 'post_event', 'observe', f'block_benchmark_missing:{b.block_uid}',
                       [_ev_block(b, b.version_created_at)], 'Training block has no ending benchmark.')]


def _block_benchmark_completed(inputs: DetectionInputs) -> list[Candidate]:
    b = inputs.block_benchmark
    if b is None or b.status != 'completed' or b.evidence_at is None or b.local_date is None:
        return []
    summary = f'Block benchmark completed on {_d(b.local_date)}.'
    if b.result_s:
        summary += f' Time {_clock(b.result_s)}.'
    return [_candidate('BLOCK_BENCHMARK_COMPLETED', 'post_event', 'observe',
                       f'block_benchmark_done:{b.block_uid}:{b.version}', [_ev_benchmark(b, b.evidence_at)], summary)]


def _block_benchmark_missed(inputs: DetectionInputs) -> list[Candidate]:
    b = inputs.block_benchmark
    if b is None or b.status != 'missed' or b.planned_date is None:
        return []
    at = _local(inputs, b.review_date + timedelta(days=3), 0, 0)
    return [_candidate('BLOCK_BENCHMARK_MISSED', 'calendar_disruption', 'caution',
                       f'block_benchmark_missed:{b.block_uid}:{b.version}', [_ev_block(b, at)],
                       f'Block benchmark planned for {_d(b.planned_date)} was not completed.')]


_REVIEW_PRIORITIES = frozenset({'target', 'benchmark', 'supported_exposure'})


def _post_event_review_due(inputs: DetectionInputs) -> list[Candidate]:
    today = inputs.today
    bench = inputs.block_benchmark
    excluded = bench.event_id if bench is not None else None
    return [_candidate('POST_EVENT_REVIEW_DUE', 'post_event', 'observe', f'event:{e.id}', [_ev_event(inputs, e)],
                       f'Race review due for {e.name} on {_d(e.event_date)}.')
            for e in sorted(inputs.events, key=lambda x: (x.event_date, x.id))
            if (excluded is None or e.id != excluded) and e.priority in _REVIEW_PRIORITIES
            and e.status != 'cancelled' and today - timedelta(days=EVENT_REVIEW_DAYS) <= e.event_date <= today - timedelta(days=1)
            and (e.status == 'completed' or e.has_run_on_date)]


RULES: tuple[tuple[str, Rule], ...] = (
    ('SYM_NEW_SITE', _sym_new_site),
    ('SYM_WORSENING', _sym_worsening),
    ('SYM_PERSISTING', _sym_persisting),
    ('SYM_RECURRENT', _sym_recurrent),
    ('SYM_MULTIWEEK', _sym_multiweek),
    ('GAIT_CHANGE', _gait_change),
    ('GAIT_PERSISTING', _gait_persisting),
    ('ILLNESS_POSSIBLE', _illness_possible),
    ('ILLNESS_PRESENT', _illness_present),
    ('ILLNESS_PROLONGED', _illness_prolonged),
    ('CLINICIAN_RESTRICTION', _clinician_restriction),
    ('RPE_ABOVE_INTENT', _rpe_above_intent),
    ('RPE_ABOVE_INTENT_REPEATED', _rpe_above_intent_repeated),
    ('SESSION_FAILED', _session_failed),
    ('SESSION_FAILED_REPEATED', _session_failed_repeated),
    ('RESPONSE_MULTIWEEK', _response_multiweek),
    ('FATIGUE_HIGH', _fatigue_high),
    ('FATIGUE_PERSISTING', _fatigue_persisting),
    ('SIGNALS_CONVERGING', _signals_converging),
    ('FATIGUE_PROLONGED', _fatigue_prolonged),
    ('KEY_SESSION_MISSED', _key_session_missed),
    ('RUNS_MISSED_REPEATED', _runs_missed_repeated),
    ('HARD_SPACING_TIGHT', _hard_spacing_tight),
    ('TRAVEL_REPORTED', _travel_reported),
    ('BLOCK_BENCHMARK_MISSING', _block_benchmark_missing),
    ('BLOCK_BENCHMARK_COMPLETED', _block_benchmark_completed),
    ('BLOCK_BENCHMARK_MISSED', _block_benchmark_missed),
    ('POST_EVENT_REVIEW_DUE', _post_event_review_due),
)


def detect(inputs: DetectionInputs) -> list[Candidate]:
    return [candidate for _, rule in RULES for candidate in rule(inputs)]
