"""Snapshot input sections on guarded synthetic state."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.calendar_models import SessionCompletion
from app.checkin_models import Checkin, SymptomReport
from app.coach_v2_models import CoachProposal, CoachSnapshot
from app.metric_models import MetricResult
from app.metrics.engine import REGISTRY, metric_modules
from app.planning_models import Block, BlockVersion, Event, Goal
from app.services import calendar, weekly_digest
from app.services.snapshot.common import ROLLING
from app.services.snapshot.inputs import _load_metrics, load_inputs
from app.services.snapshot.payload import build_payload

NOW = datetime(2026, 11, 16, 15, tzinfo=UTC)
TODAY = date(2026, 11, 16)
BLOCK_WHY = [{"kind": "priority", "text": "Build easy volume first"}]
BLOCK_INDICATORS = [
    {"source": "key_sessions", "label": "Tempo at the same RPE", "progress_when": "pace 2% faster at RPE 7 or lower"}
]
BRIEF = {
    "effort": {"rpe_low": 3, "rpe_high": 4, "feel": "conversational"},
    "focus": ["Relax shoulders"],
    "adjust_if": [{"when": "Calf tight", "then": "walk 5 min"}],
    "why": "Easy aerobic volume",
}


@pytest.fixture
def seeded(proposal_session):
    session = proposal_session
    checkin = Checkin(
        idempotency_key="snapshot-fixture",
        kind="exception",
        observed_at=NOW - timedelta(days=1),
        context_tags=[],
        version=1,
        schema_version=2,
    )
    session.add(checkin)
    block = Block(block_uid=uuid.uuid4())
    session.add(block)
    session.flush()
    session.add(SymptomReport(checkin_id=checkin.id, site="Achilles", side="left", severity=3.0, timing="during"))
    session.add(Goal(text="Synthetic goal", horizon="season", priority=1, status="active"))
    session.add(
        Event(
            name="Synthetic 10K",
            event_date=TODAY + timedelta(days=20),
            distance_m=10000,
            purpose="pr",
            goal_time_s=2700,
            rank=1,
            status="registered",
        )
    )
    session.add(
        BlockVersion(
            block_uid=block.block_uid,
            version=1,
            status="active",
            objective="Build",
            maintained_qualities=[],
            non_goals=[],
            eligible_recipe_ids=["REC001"],
            progression_dimension="duration",
            constraints=[],
            start_date=TODAY,
            review_date=date(2026, 12, 28),
            why=BLOCK_WHY,
            indicators=BLOCK_INDICATORS,
            legacy_text="Earlier rationale",
            early_review_triggers=[],
            objective_status="unresolved",
        )
    )
    run = next(row for row in calendar.state_at(session, 1) if row["kind"] == "run")
    session.add(
        SessionCompletion(session_uid=run["session_uid"], status="skipped", match_method="none", updated_at=NOW)
    )
    session.commit()
    return session


def test_load_inputs_sections(seeded):
    inputs = load_inputs(seeded, TODAY, now=NOW)
    assert len(inputs.checkins) == 1 and inputs.checkins[0]["symptoms"][0]["site"] == "Achilles"
    assert [goal["text"] for goal in inputs.goals] == ["Synthetic goal"]
    assert inputs.events[0]["name"] == "Synthetic 10K"
    assert inputs.active_block["status"] == "active"
    assert inputs.timezone == "America/New_York"


def test_load_inputs_goal_race_and_block_target(seeded):
    inputs = load_inputs(seeded, TODAY, now=NOW)
    event = inputs.events[0]
    assert (event["purpose"], event["rank"], event["goal_time_s"], event["goal_pace_s_per_km"]) == ("pr", 1, 2700, 270)
    assert inputs.active_block["target_event_status"] == "unset"
    assert inputs.active_block["build_outline"] == []
    row = seeded.scalars(select(BlockVersion)).one()
    row.target_event_id = event["event_id"]
    seeded.commit()
    assert load_inputs(seeded, TODAY, now=NOW).active_block["target_event_status"] == "current"


def test_snapshot_metrics_ignore_other_current_versions(seeded, monkeypatch):
    metric_modules()
    activity_key = str(uuid.uuid4())
    long_run = "long_run_exposure"
    rpe = "session_rpe_load"
    old_version = "v1"
    new_version = "v2"
    monkeypatch.setitem(REGISTRY, long_run, replace(REGISTRY[long_run], method_version=new_version))
    monkeypatch.setitem(REGISTRY, rpe, replace(REGISTRY[rpe], method_version=old_version))
    for metric in (long_run, rpe):
        for version in (old_version, new_version):
            seeded.add(
                MetricResult(
                    metric_id=metric,
                    method_version=version,
                    subject_type="activity",
                    subject_key=activity_key,
                    status="available",
                    source_refs={},
                    config_hash="synthetic",
                    dependency_hash="synthetic",
                    timezone="UTC",
                    calculated_at=NOW,
                    is_current=True,
                )
            )
    seeded.flush()

    rows = _load_metrics(seeded, TODAY, [{"activity_id": activity_key}])

    assert [(row["metric_id"], row["method_version"]) for row in rows if row["subject_key"] == activity_key] == [
        (long_run, new_version),
        (rpe, old_version),
    ]


def test_rolling_snapshot_carries_weekly_digest(seeded):
    inputs = load_inputs(seeded, TODAY, now=NOW)
    payload = build_payload(inputs, ROLLING)
    section = payload["weekly_digest"]
    assert section["schema"] == "weekly_digest.v1"
    assert [w["week_start"] for w in section["weeks"]] == ["2026-11-09", "2026-11-16"]
    previous, current = section["weeks"]
    assert (previous["days_elapsed"], current["days_elapsed"]) == (7, 1)
    expected = weekly_digest.load_week(seeded, TODAY, today=TODAY)
    assert current["totals"] == expected["totals"]
    sessions = current["totals"]["sessions"]
    assert (sessions["planned"], sessions["planned_to_date"], sessions["by_outcome"]["missed"]) == (3, 1, 1)
    assert previous["totals"]["sessions"]["planned"] == 0
    assert [row["outcome"] for row in current["not_done"]] == ["missed"]
    assert current["key_sessions"] == []
    assert "quality_sessions" not in payload["exception_summary"]


def test_load_inputs_session_brief_reaches_payload_without_notes(seeded):
    uid = next(
        row["session_uid"]
        for row in calendar.state_at(seeded, 1)
        if row["local_date"] == date(2026, 11, 20) and row["kind"] == "strength"
    )
    calendar.apply_edits(
        seeded, 1, [{"op": "modify", "session_uid": uid, "fields": {"brief": BRIEF}}], "Coach brief", actor="coach"
    )
    seeded.commit()
    inputs = load_inputs(seeded, TODAY, now=NOW)
    row = next(row for row in inputs.sessions if row["session_uid"] == uid)
    assert row["brief"] == BRIEF and "notes" not in row
    assert all(row["brief"] is None for row in inputs.sessions if row["session_uid"] != uid)
    view = next(row for row in build_payload(inputs, ROLLING)["calendar"]["sessions"] if row["session_uid"] == str(uid))
    assert view["brief"] == BRIEF and "notes" not in view


def test_load_inputs_active_block_carries_why_indicators_legacy_text(seeded):
    block = load_inputs(seeded, TODAY, now=NOW).active_block
    assert block["why"] == BLOCK_WHY
    assert block["indicators"] == BLOCK_INDICATORS
    assert block["legacy_text"] == "Earlier rationale"
    assert "rationale" not in block and "completion_indicators" not in block


def test_load_inputs_proposals_carry_headline_and_next_check(seeded):
    snapshot = CoachSnapshot(
        operation=ROLLING,
        as_of=TODAY,
        generated_at=NOW,
        calendar_version_number=1,
        data_revision=0,
        payload={},
        source_fingerprint="a" * 64,
        source_versions={},
        kb_digest="b" * 64,
        payload_sha256="c" * 64,
        kb_package_version="fixture",
        kb_routes=[],
        approx_tokens=1,
    )
    seeded.add(snapshot)
    seeded.flush()
    next_check = {"on": "2026-11-23", "check": "Thu tempo RPE"}
    seeded.add(
        CoachProposal(
            operation=ROLLING,
            snapshot_id=snapshot.id,
            base_calendar_version=1,
            status="accepted",
            submitted_at=NOW,
            decided_at=NOW,
            headline="Hold volume",
            next_check=next_check,
            confidence={},
            evidence_ids=[],
            policy_ids=[],
            recipe_ids=[],
            payload={},
            skill_version="fixture",
            input_hash="d" * 64,
        )
    )
    seeded.commit()
    inputs = load_inputs(seeded, TODAY, now=NOW)
    proposal = inputs.proposals[0]
    assert proposal["headline"] == "Hold volume" and proposal["next_check"] == next_check
    assert "summary" not in proposal and "follow_up" not in proposal
    assert build_payload(inputs, ROLLING)["prior_decisions"][0]["headline"] == "Hold volume"
