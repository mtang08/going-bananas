"""Synthetic exception detector and API transactions under one outer rollback."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.checkin_models import Checkin, CheckinRevision, SessionRpe, SymptomReport
from app.coach_v2_models import (
    CoachDecisionKey,
    CoachProposal,
    CoachProposalChange,
    CoachProposalRevision,
    CoachSnapshot,
)
from app.exception_models import ExceptionFinding, ExceptionPatch
from app.metric_models import Prompt
from app.models import Activity, AppState, ProfileVersion
from app.planning_models import Block, BlockBenchmarkResult, BlockDecision, BlockVersion, Event, IntensityAnchor
from app.services.exceptions.detector import (
    REASON_BENCHMARK,
    REASON_BLOCK_SYMPTOMS,
    REASON_EXCEPTION,
    finding_data,
    last_review_at,
    run_detection,
)
from app.services.exceptions.inputs import collect_detection_inputs
from app.services.exceptions.lifecycle import close_finding

NOW = datetime(2026, 11, 16, 17, tzinfo=UTC)
TODAY = date(2026, 11, 16)
DELETE_ORDER = (
    ExceptionFinding,
    ExceptionPatch,
    CoachDecisionKey,
    CoachProposalChange,
    CoachProposalRevision,
    CoachProposal,
    CoachSnapshot,
    CheckinRevision,
    SymptomReport,
    Checkin,
    SessionRpe,
    Prompt,
    SessionCompletion,
    CalendarSessionRevision,
    CalendarVersion,
    IntensityAnchor,
    BlockBenchmarkResult,
    Event,
    BlockDecision,
    BlockVersion,
    Block,
)


def local(days_ago, hour):
    return datetime.combine(TODAY - timedelta(days=days_ago), time(hour), ZoneInfo("America/New_York")).astimezone(UTC)


def checkin(observed_at, **fields):
    return Checkin(
        idempotency_key=uuid4().hex,
        kind="exception",
        observed_at=observed_at,
        context_tags=[],
        version=1,
        schema_version=2,
        **fields,
    )


def wire(result):
    return [r.to_wire() for r in result.review_recommended]


def findings(session, rule_code=None):
    query = select(ExceptionFinding).order_by(ExceptionFinding.first_seen_at, ExceptionFinding.id)
    if rule_code:
        query = query.where(ExceptionFinding.rule_code == rule_code)
    return session.scalars(query).all()


@pytest.fixture
def exc_fixture(metrics_disabled, db_connection, session_factory, profile_factory, calendar_state):
    with session_factory() as session:
        for model in DELETE_ORDER:
            session.execute(delete(model))
        calendar_state(session, reset_head=True)
        profile_factory(
            session, effective_at=datetime.now(UTC) - timedelta(days=365), cycle_anchor=datetime.now(UTC).date()
        )
        session.commit()
    return db_connection


def test_detection_is_idempotent(exc_fixture):
    connection = exc_fixture
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(checkin(local(0, 8), fatigue=8.0))
        session.flush()
        first = run_detection(session, NOW)
        rows = findings(session)
        assert [(r.rule_code, r.entity_key, r.severity, r.status) for r in rows] == [
            ("FATIGUE_HIGH", "fatigue", "observe", "open")
        ]
        finding_id = rows[0].id
        assert first.new_finding_ids == (finding_id,)
        assert first.review_recommended == ()
        second = run_detection(session, NOW + timedelta(minutes=5))
        rows = findings(session)
        assert second.new_finding_ids == () and len(rows) == 1 and rows[0].id == finding_id
        assert rows[0].first_seen_at == NOW and rows[0].last_seen_at == NOW + timedelta(minutes=5)
        assert rows[0].version == 1


def test_severity_never_lowers(exc_fixture):
    connection = exc_fixture
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        row = checkin(local(0, 8))
        session.add(row)
        session.flush()
        symptom = SymptomReport(checkin_id=row.id, site="Achilles", side="left", severity=8.0, timing="during")
        session.add(symptom)
        session.flush()
        run_detection(session, NOW)
        finding = findings(session, "SYM_NEW_SITE")[0]
        assert (finding.severity, finding.entity_key) == ("caution", "site:achilles|left")
        symptom.severity = 2.0
        session.flush()
        run_detection(session, NOW + timedelta(minutes=1))
        assert finding.severity == "caution" and finding.version == 1
        assert finding.summary == "New symptom: Left achilles at 2/10."


def test_terminal_blocks_old_evidence_only(exc_fixture):
    connection = exc_fixture
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(checkin(local(0, 8), fatigue=8.0))
        session.flush()
        run_detection(session, NOW)
        close_finding(findings(session, "FATIGUE_HIGH")[0], "dismissed", now=NOW)
        session.flush()
        assert run_detection(session, NOW + timedelta(minutes=1)).new_finding_ids == ()
        session.add(checkin(local(0, 13), fatigue=9.0))
        session.flush()
        result = run_detection(session, NOW + timedelta(hours=2))
        rows = findings(session, "FATIGUE_HIGH")
        assert [r.status for r in rows] == ["dismissed", "open"]
        assert result.new_finding_ids == (rows[1].id,)


def test_collect_sessions_and_key_session_missed(exc_fixture):
    connection = exc_fixture
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        uid = uuid4()
        session.add(CalendarVersion(number=1, kind="bootstrap", actor="system", created_at=NOW - timedelta(days=10)))
        session.flush()
        session.add(
            CalendarSessionRevision(
                session_uid=uid,
                revision=1,
                calendar_version_number=1,
                local_date=TODAY - timedelta(days=2),
                kind="run",
                recipe_id="REC002",
                intent="Long aerobic run",
                certainty="committed",
            )
        )
        session.get(AppState, 1).calendar_head_version = 1
        session.add(SessionCompletion(session_uid=uid, status="skipped", match_method="user_marked", updated_at=NOW))
        session.flush()
        inputs = collect_detection_inputs(session, NOW)
        assert inputs.today == TODAY and inputs.tz == "America/New_York" and len(inputs.sessions) == 1
        row = inputs.sessions[0]
        assert (
            row.session_uid,
            row.session_class,
            row.expected_rpe,
            row.completion_status,
            row.certainty,
            row.planned_at,
            row.completion_updated_at,
        ) == (str(uid), "long", (3.0, 5.0), "skipped", "committed", NOW - timedelta(days=10), NOW)
        run_detection(session, NOW)
        finding = findings(session, "KEY_SESSION_MISSED")[0]
        assert finding.entity_key == f"session:{uid}" and finding.evidence_at == NOW


def test_expiry_and_post_event(exc_fixture):
    connection = exc_fixture
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        old = NOW - timedelta(days=15)
        travel = ExceptionFinding(
            rule_code="TRAVEL_REPORTED",
            category="calendar_disruption",
            entity_key="travel",
            severity="observe",
            status="open",
            last_seen_at=old,
            first_seen_at=old,
            evidence_at=old,
            evidence=[],
            summary="synthetic",
            rule_version="exceptions.v1",
            version=1,
        )
        gait = ExceptionFinding(
            rule_code="GAIT_CHANGE",
            category="symptoms_illness",
            entity_key="gait",
            severity="hold",
            status="open",
            last_seen_at=old,
            first_seen_at=old,
            evidence_at=old,
            evidence=[],
            summary="synthetic",
            rule_version="exceptions.v1",
            version=1,
        )
        old_event = Event(name="Old 5K", event_date=TODAY - timedelta(days=8), purpose="pr", status="completed")
        event = Event(name="Synthetic 10K", event_date=TODAY - timedelta(days=3), purpose="pr", status="completed")
        session.add_all([travel, gait, old_event, event])
        session.flush()
        stale_event = ExceptionFinding(
            rule_code="POST_EVENT_REVIEW_DUE",
            category="post_event",
            entity_key=f"event:{old_event.id}",
            severity="observe",
            status="open",
            last_seen_at=NOW - timedelta(days=1),
            first_seen_at=old,
            evidence_at=old,
            evidence=[],
            summary="synthetic",
            rule_version="exceptions.v1",
            version=1,
        )
        session.add(stale_event)
        session.flush()
        result = run_detection(session, NOW)
        assert (travel.status, travel.closed_at, travel.version) == ("expired", NOW, 2)
        assert gait.status == "open" and stale_event.status == "expired"
        new = next(r for r in findings(session, "POST_EVENT_REVIEW_DUE") if r.entity_key == f"event:{event.id}")
        assert new.status == "open"
        recommendations = wire(result)
        assert {
            "operation": "post_event_review",
            "reason": "Race review due for Synthetic 10K on 2026-11-13",
            "finding_ids": [str(new.id)],
            "prompt": "Use $going-bananas-coach for a post-race review of Synthetic 10K on 2026-11-13.",
        } in recommendations
        assert any(
            r["operation"] == "exception_review"
            and r["reason"] == REASON_EXCEPTION
            and r["finding_ids"] == [str(gait.id)]
            for r in recommendations
        )


def test_is_new_since_last_review(exc_fixture):
    connection = exc_fixture
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(checkin(local(0, 8), fatigue=8.0))
        session.flush()
        run_detection(session, NOW)
        row = findings(session, "FATIGUE_HIGH")[0]
        assert finding_data(row, last_review_at(session))["is_new_since_last_review"] is True
        snapshot = CoachSnapshot(
            operation="review_rolling_plan",
            as_of=TODAY,
            generated_at=NOW,
            calendar_version_number=0,
            data_revision=0,
            payload={},
            source_fingerprint="a" * 64,
            source_versions={},
            kb_digest="b" * 64,
            payload_sha256="c" * 64,
            kb_package_version="test",
            kb_routes=[],
            approx_tokens=0,
        )
        session.add(snapshot)
        session.flush()
        session.add(
            CoachProposal(
                snapshot_id=snapshot.id,
                operation="review_rolling_plan",
                status="accepted",
                decided_at=NOW + timedelta(hours=1),
                input_hash="d" * 64,
                payload={"changes": []},
                confidence={},
                headline="s",
                why=[{"kind": "observation", "text": "r"}],
                skill_version="running-coach.v1",
                base_calendar_version=0,
                submitted_at=NOW,
            )
        )
        session.flush()
        assert last_review_at(session) == NOW + timedelta(hours=1)
        assert finding_data(row, last_review_at(session))["is_new_since_last_review"] is False


def test_block_benchmark_rules_and_event_exclusion(exc_fixture):
    connection = exc_fixture
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        uid = uuid4()
        session.add(Block(block_uid=uid))
        session.flush()
        version = BlockVersion(
            block_uid=uid,
            version=1,
            status="active",
            objective="o",
            why=[{"kind": "inference", "text": "r"}],
            maintained_qualities=[],
            non_goals=[],
            eligible_recipe_ids=[],
            progression_dimension="none",
            constraints={},
            start_date=TODAY - timedelta(days=40),
            review_date=TODAY - timedelta(days=4),
            indicators=[],
            early_review_triggers=[],
            objective_status="unresolved",
            benchmark=None,
        )
        session.add(version)
        session.flush()
        result = run_detection(session, NOW)
        assert findings(session, "BLOCK_BENCHMARK_MISSING") == []
        assert not any(r["operation"] == "review_training_block" for r in wire(result))
        event = Event(name="Synthetic 10K", event_date=TODAY - timedelta(days=5), purpose="pr", status="completed")
        session.add(event)
        session.flush()
        version.benchmark = {
            "kind": "event",
            "event_id": str(event.id),
            "protocol": "Synthetic 10K race",
            "distance_m": 10000,
            "planned_date": (TODAY - timedelta(days=5)).isoformat(),
            "progress_if": "faster",
            "consolidate_if": "similar",
        }
        session.flush()
        result = run_detection(session, NOW)
        missed = findings(session, "BLOCK_BENCHMARK_MISSED")[0]
        assert (missed.status, missed.entity_key, missed.severity) == (
            "open",
            f"block_benchmark_missed:{uid}:1",
            "caution",
        )
        assert not any(r.entity_key == f"event:{event.id}" for r in findings(session, "POST_EVENT_REVIEW_DUE"))
        assert any(r["reason"] == REASON_BENCHMARK["BLOCK_BENCHMARK_MISSED"] for r in wire(result))


def test_clinician_restriction_reader(exc_fixture):
    connection = exc_fixture
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        base = session.scalar(select(func.max(ProfileVersion.version)))
        for number, days, facts in (
            (base + 1, 3, {"clinician_restriction": "Walk only"}),
            (base + 2, 1, {"clinical_restriction": "Walk only"}),
        ):
            session.add(
                ProfileVersion(
                    version=number,
                    effective_at=NOW - timedelta(days=days),
                    recorded_at=NOW - timedelta(days=days),
                    timezone="America/New_York",
                    facts=facts,
                    cycle_anchor=TODAY,
                    anchor_confirmed=True,
                    strength_days_confirmed=True,
                    scheduled_strength_days=[0, 4],
                    preferences={},
                    unknowns=[],
                )
            )
        session.flush()
        inputs = collect_detection_inputs(session, NOW)
        assert inputs.clinician_restriction == "Walk only"
        assert inputs.clinician_restriction_at == NOW - timedelta(days=3)
        result = run_detection(session, NOW)
        finding = findings(session, "CLINICIAN_RESTRICTION")[0]
        assert (finding.severity, finding.entity_key) == ("escalate", "clinician_restriction")
        assert finding.evidence_at == NOW - timedelta(days=3)
        assert any(
            r["operation"] == "review_training_block" and r["reason"] == REASON_BLOCK_SYMPTOMS for r in wire(result)
        )


def _observed():
    return (
        datetime.now(UTC)
        .astimezone(ZoneInfo("America/New_York"))
        .replace(hour=9, minute=0, second=0, microsecond=0)
        .isoformat()
    )


def _body(**changes):
    value = {
        "idempotency_key": "fixture-" + uuid.uuid4().hex,
        "kind": "exception",
        "observed_at": _observed(),
        "fatigue": 7,
        "illness": None,
        "gait_change": None,
        "context_tags": [],
        "symptoms": [{"site": "Achilles", "side": "left", "severity": 3.0, "timing": "during"}],
        "note": "synthetic note",
    }
    value.update(changes)
    return value


def _activity(connection, sport="running"):
    activity_id = uuid.uuid4()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(
            Activity(
                id=activity_id,
                start_at=datetime.now(UTC) - timedelta(hours=1),
                original_start=_observed(),
                local_date=datetime.now(UTC).astimezone(ZoneInfo("America/New_York")).date(),
                sport=sport,
                elapsed_s=1800,
                canonical_revision=1,
                resolution_state="resolved",
                field_provenance={},
            )
        )
        session.commit()
    return activity_id
