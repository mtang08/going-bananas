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
    PlannedActualFact,
    RpeRun,
    SessionFact,
    SymptomFact,
)
from app.services.exceptions.rules import RULES, _clock, detect
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

TZ = "America/New_York"
TODAY = date(2026, 11, 16)
NOW = datetime(2026, 11, 16, 17, tzinfo=UTC)  # 12:00 local


def at(days_ago, hour=9):
    return datetime.combine(TODAY - timedelta(days=days_ago), time(hour), ZoneInfo(TZ)).astimezone(UTC)


def sym(site="Achilles", side="left", severity=3.0, timing="during"):
    return SymptomFact(uuid4().hex, site, side, severity, timing)


def chk(days_ago=0, hour=9, *, fatigue=None, illness=None, gait=None, tags=(), activity=None, linked=None, symptoms=()):
    o = at(days_ago, hour)
    return CheckinFact(
        uuid4().hex,
        "exception",
        o,
        o,
        TODAY - timedelta(days=days_ago),
        fatigue,
        illness,
        gait,
        tuple(tags),
        activity,
        linked or activity,
        tuple(symptoms),
    )


def run(days_ago, rpe, *, uid=None, aid=None, rpe_at=None):
    s = at(days_ago, 7)
    return RpeRun(
        aid or uuid4().hex, TODAY - timedelta(days=days_ago), s, s + timedelta(hours=1), rpe, "manual", rpe_at, uid
    )


def ses(
    days_ago,
    recipe="REC001",
    *,
    kind="run",
    status=None,
    reason=None,
    aid=None,
    uid=None,
    intent="Run",
    planned_at=None,
    updated_at=None,
):
    cls = classify(kind, recipe, intent)
    d = TODAY - timedelta(days=days_ago)
    return SessionFact(
        uid or uuid4().hex,
        d,
        kind,
        recipe,
        intent,
        "committed",
        cls,
        expected_rpe(recipe, cls),
        status,
        reason,
        aid,
        planned_at or at(30),
        updated_at,
    )


def ev(days_ago=3, *, purpose="pr", status="completed", ran=False, run_end=None):
    return EventFact("e1", "Synthetic 10K", TODAY - timedelta(days=days_ago), purpose, status, ran, run_end)


def inp(**kw):
    return DetectionInputs(today=TODAY, now=NOW, tz=TZ, **kw)


def hits(inputs, code):
    return [(c.entity_key, c.severity) for c in detect(inputs) if c.rule_code == code]


def one(inputs, code):
    return next(c for c in detect(inputs) if c.rule_code == code)


def bb(status, **kw):
    return dataclasses.replace(
        BlockBenchmarkFact(
            block_uid="b1",
            version=2,
            version_created_at=at(40),
            planned_date=TODAY - timedelta(days=5),
            review_date=TODAY - timedelta(days=4),
            kind="time_trial",
            event_id=None,
            status=status,
            activity_id=None,
            local_date=None,
            evidence_at=None,
            protocol="5 km solo time trial",
        ),
        **kw,
    )


def test_vocab() -> None:
    assert max_severity("observe", "hold") == "hold"
    assert max_severity("escalate", "caution", "observe") == "escalate"
    assert SEVERITY == ("observe", "caution", "hold", "escalate")
    assert CATEGORY == (
        "symptoms_illness",
        "training_response",
        "accumulated_fatigue",
        "calendar_disruption",
        "post_event",
    )
    assert PATCH_CATEGORY == tuple(category for category in CATEGORY if category != "post_event")
    assert FINDING_STATUS == NON_TERMINAL_FINDING + TERMINAL_FINDING
    assert PATCH_STATUS == ("open", "resolved", "escalated", "superseded")
    assert LADDER == ("current_session", "next_session", "next_days", "committed_window", "block")
    assert get_args(Severity) == SEVERITY
    assert RULE_VERSION == "exceptions.v1"


def test_empty_inputs_detect_nothing():
    assert detect(inp()) == []


def test_clock_format():
    assert _clock(1470) == "24:30"
    assert _clock(3725) == "1:02:05"


def test_sym_new_site():
    code = "SYM_NEW_SITE"

    def check(*checks):
        return hits(inp(checkins=checks), code)

    assert check(chk(1, symptoms=(sym(),))) == [("site:achilles|left", "observe")]
    assert check(chk(1, symptoms=(sym(severity=7),))) == [("site:achilles|left", "caution")]
    assert check(chk(1, symptoms=(sym(severity=6.9),))) == [("site:achilles|left", "observe")]
    assert check(chk(20, symptoms=(sym(),)), chk(1, symptoms=(sym(),))) == []
    assert check(chk(30, symptoms=(sym(),)), chk(1, symptoms=(sym(),)))
    assert check(chk(20, symptoms=(sym(site=" ACHILLES "),)), chk(1, symptoms=(sym(),))) == []
    assert ("site:achilles|left", "observe") in check(chk(20, symptoms=(sym(side="right"),)), chk(1, symptoms=(sym(),)))
    assert check(chk(7, symptoms=(sym(),))) == []
    assert check(chk(6, symptoms=(sym(),)))
    assert one(inp(checkins=(chk(1, symptoms=(sym(),)),)), code).summary == "New symptom: Left achilles at 3/10."


def test_sym_worsening():
    code = "SYM_WORSENING"

    def check(*pairs):
        return inp(checkins=tuple(chk(day, symptoms=(sym(severity=severity),)) for day, severity in pairs))

    first = check((3, 3), (1, 5))
    assert hits(first, code) == [("site:achilles|left", "caution")]
    assert hits(check((3, 5), (1, 3)), code) == []
    assert hits(check((3, 3), (1, 3)), code) == []
    assert hits(check((8, 3), (0, 5)), code) == []
    assert hits(check((7, 3), (0, 5)), code)
    assert hits(check((4, 6), (2, 2), (0, 4)), code)
    assert one(first, code).summary == "Left achilles symptom rose from 3 to 5/10 within 7 days."


def test_sym_persisting():
    code = "SYM_PERSISTING"
    early = chk(1, 8, activity="a1", symptoms=(sym(timing="immediately_after"),))
    late = chk(0, 8, linked="a1", symptoms=(sym(timing="next_morning"),))
    assert hits(inp(checkins=(early, late)), code) == [("site:achilles|left", "caution")]
    assert hits(inp(checkins=(early, dataclasses.replace(late, linked_activity_id="a2"))), code) == []
    assert hits(inp(checkins=(dataclasses.replace(early, symptoms=(sym(timing="later"),)), late)), code) == []
    assert hits(inp(checkins=(early, dataclasses.replace(late, symptoms=(sym(timing="during"),)))), code) == []
    assert hits(inp(checkins=(early, dataclasses.replace(late, linked_activity_id=None))), code) == []


def test_sym_recurrent():
    code = "SYM_RECURRENT"
    assert hits(inp(checkins=tuple(chk(d, symptoms=(sym(),)) for d in (0, 5, 13))), code) == [
        ("site:achilles|left", "caution")
    ]
    assert hits(inp(checkins=tuple(chk(d, symptoms=(sym(),)) for d in (0, 5, 14))), code) == []
    assert hits(inp(checkins=tuple(chk(d, symptoms=(sym(),)) for d in (0, 0, 5))), code) == []


def test_sym_multiweek():
    code = "SYM_MULTIWEEK"
    for days in ((2, 9, 16), (6, 13, 20), (0, 7, 14)):
        assert hits(inp(checkins=tuple(chk(d, symptoms=(sym(),)) for d in days)), code) == [
            ("site:achilles|left", "escalate")
        ]
    assert hits(inp(checkins=tuple(chk(d, symptoms=(sym(),)) for d in (2, 9, 21))), code) == []


def test_gait_change():
    assert hits(inp(checkins=(chk(2, gait="yes"),)), "GAIT_CHANGE") == [("gait", "hold")]
    assert hits(inp(checkins=(chk(3, gait="yes"),)), "GAIT_CHANGE") == []
    assert hits(inp(checkins=(chk(gait="unsure"),)), "GAIT_CHANGE") == []


def test_gait_persisting():
    code = "GAIT_PERSISTING"
    assert hits(inp(checkins=(chk(1, 9, gait="yes"), chk(0, 9, gait="yes"))), code) == [("gait", "escalate")]
    assert hits(inp(checkins=(chk(0, 8, gait="yes"), chk(0, 20, gait="yes"))), code) == []
    assert hits(inp(checkins=(chk(1, 13, gait="yes"), chk(0, 9, gait="yes"))), code)
    assert hits(inp(checkins=(chk(7, gait="yes"), chk(0, gait="yes"))), code) == []


def test_illness_possible():
    code = "ILLNESS_POSSIBLE"
    assert hits(inp(checkins=(chk(1, illness="possible"),)), code) == [("illness", "caution")]
    assert hits(inp(checkins=(chk(1, illness="possible"), chk(0, illness="none"))), code) == []
    assert hits(inp(checkins=(chk(2, illness="possible"),)), code) == []
    assert hits(inp(checkins=(chk(1, illness="possible"), chk(0))), code)


def test_illness_present():
    code = "ILLNESS_PRESENT"
    assert hits(inp(checkins=(chk(2, illness="present"),)), code) == [("illness", "hold")]
    assert hits(inp(checkins=(chk(3, illness="present"),)), code) == []
    assert hits(inp(checkins=(chk(2, illness="present"), chk(1, illness="none"))), code) == []


def test_illness_prolonged():
    code = "ILLNESS_PROLONGED"
    assert hits(inp(checkins=(chk(9, illness="present"), chk(3, illness="present"))), code) == [("illness", "escalate")]
    assert hits(inp(checkins=(chk(8, illness="present"), chk(3, illness="present"))), code) == []
    assert hits(inp(checkins=(chk(10, illness="present"), chk(0, illness="present"))), code) == []


def test_clinician_restriction():
    code = "CLINICIAN_RESTRICTION"
    inputs = inp(clinician_restriction="No running", clinician_restriction_at=at(40))
    assert hits(inputs, code) == [("clinician_restriction", "escalate")]
    assert one(inputs, code).evidence_at == at(40)
    assert one(inputs, code).summary == "Clinician restriction on file: No running."
    assert hits(inp(), code) == []
    assert hits(inp(clinician_restriction="No running"), code) == []


def test_rpe_above_intent():
    code = "RPE_ABOVE_INTENT"
    s = ses(2, status="completed_as_planned", aid="a1", uid="s1")
    r = run(2, 6, uid="s1", aid="a1")
    inputs = inp(sessions=(s,), runs=(r,))
    assert hits(inputs, code) == [("activity:a1", "observe")]
    assert one(inputs, code).summary == "Easy run felt RPE 6 (expected 2–4)."
    assert one(dataclasses.replace(inputs, checkins=(chk(2, 10, tags=("heat",)),)), code).summary.endswith(
        " Heat reported."
    )
    assert one(dataclasses.replace(inputs, checkins=(chk(1, 9, tags=("heat",)),)), code).summary.endswith("2–4).")
    assert hits(dataclasses.replace(inputs, runs=(dataclasses.replace(r, rpe=5.9),)), code) == []
    assert hits(dataclasses.replace(inputs, runs=(run(2, 9),)), code) == []
    for d, expected in ((14, False), (13, True)):
        assert bool(hits(inp(sessions=(ses(d, uid="s1"),), runs=(run(d, 6, uid="s1"),)), code)) == expected
    assert hits(inp(sessions=(ses(2, "REC009", uid="s1"),), runs=(run(2, 10, uid="s1"),)), code) == []
    assert one(inputs, code).evidence_at == at(2, 8)
    assert one(dataclasses.replace(inputs, runs=(dataclasses.replace(r, rpe_at=at(1, 9)),)), code).evidence_at == at(
        1, 9
    )


def test_rpe_above_intent_repeated():
    code = "RPE_ABOVE_INTENT_REPEATED"
    for days, expected in (((1, 5), [("rpe_easy_long", "caution")]), ((1, 7), [])):
        sessions = tuple(ses(d, uid=str(d)) for d in days)
        runs = tuple(run(d, 6, uid=str(d)) for d in days)
        assert hits(inp(sessions=sessions, runs=runs), code) == expected
    assert (
        hits(
            inp(sessions=(ses(1, uid="a"), ses(5, "REC003", uid="b")), runs=(run(1, 6, uid="a"), run(5, 10, uid="b"))),
            code,
        )
        == []
    )


def test_session_failed():
    code = "SESSION_FAILED"
    s = ses(3, "REC003", status="partial", uid="s1")
    assert hits(inp(sessions=(s,)), code) == [("session:s1", "observe")]
    modified = dataclasses.replace(s, completion_status="completed_modified", modification_reason="fatigue")
    assert "modified for fatigue" in one(inp(sessions=(modified,)), code).summary
    assert hits(inp(sessions=(dataclasses.replace(modified, modification_reason="schedule"),)), code) == []
    completed = dataclasses.replace(s, completion_status="completed_as_planned")
    assert hits(inp(sessions=(completed,), planned_actual={"s1": PlannedActualFact((), "not_met")}), code)
    assert hits(inp(sessions=(ses(3, "REC001", status="partial"),)), code) == []
    for d, expected in ((14, False), (13, True), (-1, False)):
        assert bool(hits(inp(sessions=(ses(d, "REC003", status="partial"),)), code)) == expected


def test_session_failed_repeated():
    code = "SESSION_FAILED_REPEATED"
    sessions = tuple(ses(d, "REC003", status="partial") for d in (2, 10))
    assert hits(inp(sessions=sessions), code) == [("quality_failed", "caution")]
    assert hits(inp(sessions=sessions[:1]), code) == []


def test_response_multiweek():
    code = "RESPONSE_MULTIWEEK"
    sessions = tuple(ses(d, "REC003", status="partial") for d in (1, 3, 8, 12))
    assert hits(inp(sessions=sessions), code) == [("training_response", "escalate")]
    assert hits(inp(sessions=sessions[:2]), code) == []
    easy = tuple(ses(d, uid=str(d)) for d in (1, 2))
    failed = tuple(ses(d, "REC003", status="partial") for d in (8, 9))
    runs = tuple(run(d, 6, uid=str(d)) for d in (1, 2))
    assert hits(inp(sessions=easy + failed, runs=runs), code) == [("training_response", "escalate")]


def test_fatigue_high():
    code = "FATIGUE_HIGH"
    assert hits(inp(checkins=(chk(1, fatigue=7),)), code) == [("fatigue", "observe")]
    assert hits(inp(checkins=(chk(1, fatigue=6.9),)), code) == []
    assert hits(inp(checkins=(chk(2, fatigue=7),)), code) == []


def test_fatigue_persisting():
    code = "FATIGUE_PERSISTING"
    assert hits(inp(checkins=(chk(0, fatigue=7), chk(3, fatigue=7))), code) == [("fatigue_persisting", "caution")]
    assert hits(inp(checkins=(chk(0, fatigue=7), chk(4, fatigue=7))), code) == []
    assert hits(inp(checkins=(chk(0, fatigue=7), chk(0, fatigue=7))), code) == []


def test_signals_converging():
    code = "SIGNALS_CONVERGING"
    assert hits(inp(checkins=(chk(0, fatigue=7), chk(2, tags=("poor_sleep",)))), code) == [("converging", "caution")]
    assert hits(inp(checkins=(chk(0, tags=("poor_sleep",)), chk(2, tags=("travel",)))), code) == []
    nights = frozenset({TODAY, TODAY - timedelta(days=1)})
    inputs = inp(checkins=(chk(0, fatigue=7),), recovery_adverse_dates=nights)
    assert hits(inputs, code) == [("converging", "caution")]
    assert hits(dataclasses.replace(inputs, recovery_adverse_dates=frozenset({TODAY})), code) == []
    assert hits(inp(checkins=(chk(0, tags=("poor_sleep",)),), recovery_adverse_dates=nights), code) == []


def test_fatigue_prolonged():
    code = "FATIGUE_PROLONGED"
    assert hits(inp(checkins=tuple(chk(d, fatigue=7) for d in (0, 3, 6, 9))), code) == [("fatigue_prolonged", "hold")]
    assert hits(inp(checkins=tuple(chk(d, fatigue=7) for d in (0, 3, 6, 10))), code) == []


def test_key_session_missed():
    code = "KEY_SESSION_MISSED"
    s = ses(2, "REC002", status="skipped", uid="s1")
    assert hits(inp(sessions=(s,)), code) == [("session:s1", "observe")]
    assert hits(inp(sessions=(dataclasses.replace(s, completion_status="unknown"),)), code)
    missing = dataclasses.replace(s, completion_status=None)
    assert hits(inp(sessions=(missing,), planned_actual={"s1": PlannedActualFact(("NO_ACTIVITY_FOUND",), None)}), code)
    assert hits(inp(sessions=(missing,)), code) == []
    assert hits(inp(sessions=(ses(2, "REC001", status="skipped"),)), code) == []
    for d, expected in ((0, False), (7, True), (8, False)):
        assert bool(hits(inp(sessions=(ses(d, "REC002", status="skipped"),)), code)) == expected
    assert one(inp(sessions=(dataclasses.replace(s, completion_updated_at=at(1, 10)),)), code).evidence_at == at(1, 10)
    assert one(inp(sessions=(s,)), code).evidence_at == at(30)


def test_runs_missed_repeated():
    code = "RUNS_MISSED_REPEATED"
    sessions = tuple(ses(d, status="skipped") for d in (1, 6))
    assert hits(inp(sessions=sessions), code) == [("runs_missed", "caution")]
    assert hits(inp(sessions=sessions[:1]), code) == []
    assert hits(inp(sessions=tuple(ses(d, None, kind="strength", status="skipped") for d in (1, 6))), code) == []


def test_hard_spacing_tight():
    code = "HARD_SPACING_TIGHT"
    future = (ses(-2, "REC003", uid="u-b"), ses(-3, "REC002", uid="u-a"))
    assert hits(inp(sessions=future), code) == [("spacing:u-a:u-b", "caution")]
    assert hits(inp(sessions=(ses(-2, "REC003"), ses(-4, "REC002"))), code) == []
    today = ses(0, "REC002", uid="u-a")
    yesterday = ses(1, "REC003", status="completed_as_planned", uid="u-b")
    assert hits(inp(sessions=(yesterday, today)), code)
    assert hits(inp(sessions=(dataclasses.replace(yesterday, completion_status=None), today)), code) == []
    assert hits(inp(sessions=(dataclasses.replace(yesterday, completion_status="skipped"), today)), code) == []
    assert hits(inp(sessions=(ses(-6, "REC003"), ses(-7, "REC002"))), code) == []
    timed = dataclasses.replace(future[0], planned_at=at(20))
    assert one(inp(sessions=(timed, future[1])), code).evidence_at == at(20)
    yesterday = dataclasses.replace(yesterday, completion_updated_at=at(1, 20))
    assert one(inp(sessions=(yesterday, today)), code).evidence_at == at(1, 20)


def test_travel_reported():
    assert hits(inp(checkins=(chk(1, tags=("travel",)),)), "TRAVEL_REPORTED") == [("travel", "observe")]
    assert hits(inp(checkins=(chk(2, tags=("travel",)),)), "TRAVEL_REPORTED") == []


def test_block_benchmark_rules():
    missing, completed, missed = ("BLOCK_BENCHMARK_" + suffix for suffix in ("MISSING", "COMPLETED", "MISSED"))
    inputs = inp(block_benchmark=bb("not_set"))
    assert [c.rule_code for c in detect(inputs) if c.rule_code.startswith("BLOCK_BENCHMARK")] == []
    for block in (bb("pending"), None):
        for code in (missing, completed, missed):
            assert hits(inp(block_benchmark=block), code) == []
    inputs = inp(
        block_benchmark=bb(
            "completed",
            match_method="auto",
            activity_id="a9",
            local_date=TODAY - timedelta(days=5),
            result_s=1470,
            evidence_at=at(5, 8),
        )
    )
    assert hits(inputs, completed) == [("block_benchmark_done:b1:2", "observe")]
    assert one(inputs, completed).summary == "Block benchmark completed on Wed Nov 11. Time 24:30."
    assert one(inputs, completed).evidence_at == at(5, 8)
    inputs = inp(block_benchmark=bb("missed"))
    assert hits(inputs, missed) == [("block_benchmark_missed:b1:2", "caution")]
    assert one(inputs, missed).category == "calendar_disruption"
    assert one(inputs, missed).evidence_at == datetime(2026, 11, 15, 0, 0, tzinfo=ZoneInfo(TZ))


def test_post_event_review_due():
    code = "POST_EVENT_REVIEW_DUE"
    assert hits(inp(events=(ev(3),), block_benchmark=bb("pending", event_id="e1")), code) == []
    assert hits(inp(events=(ev(3),), block_benchmark=bb("pending", event_id="other")), code)
    inputs = inp(events=(ev(3),))
    assert hits(inputs, code) == [("event:e1", "observe")]
    assert one(inputs, code).summary == "Race review due for Synthetic 10K on Fri Nov 13."
    assert hits(inp(events=(ev(3, purpose="training"),)), code) == []
    assert hits(inp(events=(ev(3, purpose="benchmark"),)), code)
    assert hits(inp(events=(ev(3, status="cancelled"),)), code) == []
    assert hits(inp(events=(ev(3, status="registered", ran=True),)), code)
    assert hits(inp(events=(ev(3, status="registered"),)), code) == []
    for d, expected in ((0, False), (7, True), (8, False)):
        assert bool(hits(inp(events=(ev(d),)), code)) == expected
    assert one(inputs, code).evidence_at == datetime(2026, 11, 13, 23, 59, tzinfo=ZoneInfo(TZ))
    assert one(inp(events=(ev(3, ran=True, run_end=at(3, 10)),)), code).evidence_at == at(3, 10)


TABLE = [
    ("SYM_NEW_SITE", "symptoms_illness"),
    ("SYM_WORSENING", "symptoms_illness"),
    ("SYM_PERSISTING", "symptoms_illness"),
    ("SYM_RECURRENT", "symptoms_illness"),
    ("SYM_MULTIWEEK", "symptoms_illness"),
    ("GAIT_CHANGE", "symptoms_illness"),
    ("GAIT_PERSISTING", "symptoms_illness"),
    ("ILLNESS_POSSIBLE", "symptoms_illness"),
    ("ILLNESS_PRESENT", "symptoms_illness"),
    ("ILLNESS_PROLONGED", "symptoms_illness"),
    ("CLINICIAN_RESTRICTION", "symptoms_illness"),
    ("RPE_ABOVE_INTENT", "training_response"),
    ("RPE_ABOVE_INTENT_REPEATED", "training_response"),
    ("SESSION_FAILED", "training_response"),
    ("SESSION_FAILED_REPEATED", "training_response"),
    ("RESPONSE_MULTIWEEK", "training_response"),
    ("FATIGUE_HIGH", "accumulated_fatigue"),
    ("FATIGUE_PERSISTING", "accumulated_fatigue"),
    ("SIGNALS_CONVERGING", "accumulated_fatigue"),
    ("FATIGUE_PROLONGED", "accumulated_fatigue"),
    ("KEY_SESSION_MISSED", "calendar_disruption"),
    ("RUNS_MISSED_REPEATED", "calendar_disruption"),
    ("HARD_SPACING_TIGHT", "calendar_disruption"),
    ("TRAVEL_REPORTED", "calendar_disruption"),
    ("BLOCK_BENCHMARK_COMPLETED", "post_event"),
    ("BLOCK_BENCHMARK_MISSED", "calendar_disruption"),
    ("POST_EVENT_REVIEW_DUE", "post_event"),
]


def test_hard_rules():
    assert detect(inp(recovery_adverse_dates=frozenset(TODAY - timedelta(days=i) for i in range(14)))) == []
    symptom = detect(inp(checkins=(chk(0, symptoms=(sym(severity=10.0),)),)))
    assert max_severity(*[candidate.severity for candidate in symptom]) == "caution"
    fatigue = detect(inp(checkins=(chk(0, fatigue=10),)))
    assert all(candidate.severity == "observe" for candidate in fatigue)


def test_registry_order():
    assert [code for code, _ in RULES] == [code for code, _ in TABLE]


def test_busy_input_invariants():
    inputs = inp(
        checkins=(
            chk(1, symptoms=(sym(severity=7.0),)),
            chk(0, fatigue=8, tags=("travel", "poor_sleep")),
            chk(2, gait="yes", illness="possible"),
        ),
        runs=(run(2, 6.0, uid="s1", aid="a1"),),
        sessions=(
            ses(2, "REC001", status="completed_as_planned", aid="a1", uid="s1"),
            ses(3, "REC003", status="partial"),
            ses(2, "REC002", status="skipped"),
        ),
        events=(ev(3),),
        block_benchmark=bb("missed"),
        clinician_restriction="Walk only",
        clinician_restriction_at=at(40),
    )
    candidates = detect(inputs)
    categories = dict(TABLE)
    assert all(candidate.rule_code in categories for candidate in candidates)
    assert all(candidate.category == categories[candidate.rule_code] for candidate in candidates)
    keys = [(candidate.rule_code, candidate.entity_key) for candidate in candidates]
    assert len(keys) == len(set(keys))
    assert all(len(candidate.summary) <= 240 for candidate in candidates)
    assert detect(inputs) == detect(inputs)


def test_evidence_cap_and_order():
    candidates = detect(inp(checkins=tuple(chk(day, fatigue=8) for day in range(10))))
    candidate = next(item for item in candidates if item.rule_code == "FATIGUE_PROLONGED")
    assert len(candidate.evidence) == 8
    times = [item["at"] for item in candidate.evidence]
    assert all(newer > older for newer, older in zip(times, times[1:]))
    assert candidate.evidence_at == at(0)
