import dataclasses
from datetime import UTC, date, datetime, time, timedelta
from typing import get_args
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.domain.session_class import classify, expected_rpe
from app.services.exceptions.facts import (
    BlockBenchmarkFact,
    CheckinFact,
    DetectionInputs,
    EventFact,
    RpeRun,
    SessionFact,
    SymptomFact,
)
from app.services.exceptions.rules import _clock, detect
from app.services.exceptions.vocab import (
    CATEGORY,
    FINDING_STATUS,
    LADDER,
    NON_TERMINAL_FINDING,
    PATCH_CATEGORY,
    PATCH_STATUS,
    RULE_VERSION,
    SEVERITY,
    TERMINAL_FINDING,
    Severity,
    max_severity,
)

TZ = 'America/New_York'
TODAY = date(2026, 11, 16)
NOW = datetime(2026, 11, 16, 17, tzinfo=UTC)  # 12:00 local


def at(days_ago, hour=9):
    return datetime.combine(TODAY - timedelta(days=days_ago), time(hour), ZoneInfo(TZ)).astimezone(UTC)


def sym(site='Achilles', side='left', severity=3.0, timing='during'):
    return SymptomFact(uuid4().hex, site, side, severity, timing)


def chk(days_ago=0, hour=9, *, fatigue=None, illness=None, gait=None, tags=(), activity=None, linked=None, symptoms=()):
    o = at(days_ago, hour)
    return CheckinFact(uuid4().hex, 'exception', o, o, TODAY - timedelta(days=days_ago), fatigue, illness, gait,
                       tuple(tags), activity, linked or activity, tuple(symptoms))


def run(days_ago, rpe, *, uid=None, aid=None, rpe_at=None):
    s = at(days_ago, 7)
    return RpeRun(aid or uuid4().hex, TODAY - timedelta(days=days_ago), s, s + timedelta(hours=1), rpe, 'manual', rpe_at, uid)


def ses(days_ago, recipe='REC001', *, kind='run', status=None, reason=None, aid=None, uid=None, intent='Run',
        planned_at=None, updated_at=None):
    cls = classify(kind, recipe, intent)
    d = TODAY - timedelta(days=days_ago)
    return SessionFact(uid or uuid4().hex, d, kind, recipe, intent, 'committed', cls, expected_rpe(recipe, cls),
                       status, reason, aid, planned_at or at(30), updated_at)


def ev(days_ago=3, *, priority='target', status='completed', ran=False, run_end=None):
    return EventFact('e1', 'Synthetic 10K', TODAY - timedelta(days=days_ago), priority, status, ran, run_end)


def inp(**kw):
    return DetectionInputs(today=TODAY, now=NOW, tz=TZ, **kw)


def hits(inputs, code):
    return [(c.entity_key, c.severity) for c in detect(inputs) if c.rule_code == code]


def one(inputs, code):
    return next(c for c in detect(inputs) if c.rule_code == code)


def bb(status, **kw):
    return dataclasses.replace(BlockBenchmarkFact(
        block_uid='b1', version=2, version_created_at=at(40), planned_date=TODAY - timedelta(days=5),
        review_date=TODAY - timedelta(days=4), kind='time_trial', event_id=None, status=status, activity_id=None,
        local_date=None, evidence_at=None, protocol='5 km solo time trial'), **kw)



def test_vocab() -> None:
    assert max_severity('observe', 'hold') == 'hold'
    assert max_severity('escalate', 'caution', 'observe') == 'escalate'
    assert SEVERITY == ('observe', 'caution', 'hold', 'escalate')
    assert CATEGORY == ('symptoms_illness', 'training_response', 'accumulated_fatigue', 'calendar_disruption', 'post_event')
    assert PATCH_CATEGORY == tuple(category for category in CATEGORY if category != 'post_event')
    assert FINDING_STATUS == NON_TERMINAL_FINDING + TERMINAL_FINDING
    assert PATCH_STATUS == ('open', 'resolved', 'escalated', 'superseded')
    assert LADDER == ('current_session', 'next_session', 'next_days', 'committed_window', 'block')
    assert get_args(Severity) == SEVERITY
    assert RULE_VERSION == 'exceptions.v1'


def test_empty_inputs_detect_nothing():
    assert detect(inp()) == []


def test_clock_format():
    assert _clock(1470) == "24:30"
    assert _clock(3725) == "1:02:05"


def test_sym_new_site():
    code = 'SYM_NEW_SITE'
    def check(*checks):
        return hits(inp(checkins=checks), code)
    assert check(chk(1, symptoms=(sym(),))) == [('site:achilles|left', 'observe')]
    assert check(chk(1, symptoms=(sym(severity=7),))) == [('site:achilles|left', 'caution')]
    assert check(chk(1, symptoms=(sym(severity=6.9),))) == [('site:achilles|left', 'observe')]
    assert check(chk(20, symptoms=(sym(),)), chk(1, symptoms=(sym(),))) == []
    assert check(chk(30, symptoms=(sym(),)), chk(1, symptoms=(sym(),)))
    assert check(chk(20, symptoms=(sym(site=' ACHILLES '),)), chk(1, symptoms=(sym(),))) == []
    assert ('site:achilles|left', 'observe') in check(chk(20, symptoms=(sym(side='right'),)), chk(1, symptoms=(sym(),)))
    assert check(chk(7, symptoms=(sym(),))) == []
    assert check(chk(6, symptoms=(sym(),)))
    assert one(inp(checkins=(chk(1, symptoms=(sym(),)),)), code).summary == 'New symptom: Left achilles at 3/10.'


def test_sym_worsening():
    code = 'SYM_WORSENING'
    def check(*pairs):
        return inp(checkins=tuple(chk(day, symptoms=(sym(severity=severity),)) for day, severity in pairs))
    first = check((3, 3), (1, 5))
    assert hits(first, code) == [('site:achilles|left', 'caution')]
    assert hits(check((3, 5), (1, 3)), code) == []
    assert hits(check((3, 3), (1, 3)), code) == []
    assert hits(check((8, 3), (0, 5)), code) == []
    assert hits(check((7, 3), (0, 5)), code)
    assert hits(check((4, 6), (2, 2), (0, 4)), code)
    assert one(first, code).summary == 'Left achilles symptom rose from 3 to 5/10 within 7 days.'


def test_sym_persisting():
    code = 'SYM_PERSISTING'
    early = chk(1, 8, activity='a1', symptoms=(sym(timing='immediately_after'),))
    late = chk(0, 8, linked='a1', symptoms=(sym(timing='next_morning'),))
    assert hits(inp(checkins=(early, late)), code) == [('site:achilles|left', 'caution')]
    assert hits(inp(checkins=(early, dataclasses.replace(late, linked_activity_id='a2'))), code) == []
    assert hits(inp(checkins=(dataclasses.replace(early, symptoms=(sym(timing='later'),)), late)), code) == []
    assert hits(inp(checkins=(early, dataclasses.replace(late, symptoms=(sym(timing='during'),)))), code) == []
    assert hits(inp(checkins=(early, dataclasses.replace(late, linked_activity_id=None))), code) == []


def test_sym_recurrent():
    code = 'SYM_RECURRENT'
    assert hits(inp(checkins=tuple(chk(d, symptoms=(sym(),)) for d in (0, 5, 13))), code) == [('site:achilles|left', 'caution')]
    assert hits(inp(checkins=tuple(chk(d, symptoms=(sym(),)) for d in (0, 5, 14))), code) == []
    assert hits(inp(checkins=tuple(chk(d, symptoms=(sym(),)) for d in (0, 0, 5))), code) == []


def test_sym_multiweek():
    code = 'SYM_MULTIWEEK'
    for days in ((2, 9, 16), (6, 13, 20), (0, 7, 14)):
        assert hits(inp(checkins=tuple(chk(d, symptoms=(sym(),)) for d in days)), code) == [('site:achilles|left', 'escalate')]
    assert hits(inp(checkins=tuple(chk(d, symptoms=(sym(),)) for d in (2, 9, 21))), code) == []
