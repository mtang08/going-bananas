"""Compare synthetic block and race inputs with the Python snapshot readers."""

import os
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "backend"))

from app.calendar_models import (
    CalendarSessionRevision,
    CalendarVersion,
    SessionCompletion,
)
from app.checkin_models import SessionRpe
from app.coach_v2_models import CoachProposal, CoachProposalChange, CoachSnapshot
from app.models import Activity, ActivityAnnotation, AppState
from app.planning_models import (
    Block,
    BlockBenchmarkResult,
    BlockDecision,
    BlockVersion,
    Event,
    IntensityAnchor,
)
from app.services.decision_inputs import canonical_json
from app.services.snapshot.inputs import (
    _load_active_block,
    _load_anchors,
    _load_benchmark_history,
    _load_block_decisions,
    _load_events,
    _load_proposals,
)

day = date(2026, 11, 1)
now = datetime(2026, 11, 2, 3, 30, 0, 123400, tzinfo=UTC)


def uid(n):
    return UUID(int=90_000 + n)


def seed(s):
    for i, (days, status, rank) in enumerate(
        [
            (0, "registered", 2),
            (8, "planned", 1),
            (-28, "completed", None),
            (-29, "cancelled", None),
        ]
    ):
        s.add(
            Event(
                id=uid(i),
                name=f"Fixture race {i}",
                event_date=day + timedelta(days=days),
                status=status,
                purpose="benchmark",
                rank=rank,
                distance_m=5000,
                goal_time_s=1103,
                result_s=1100 if i == 0 else None,
            )
        )
    for i, distance in enumerate([5100.5, 8000, 5300.5]):
        s.add(
            Activity(
                id=uid(10 + i),
                sport="running",
                original_start="test",
                start_at=now - timedelta(minutes=i),
                local_date=day + timedelta(days=1),
                distance_m=distance,
                timer_s=1200.5,
                workout_rpe=6,
            )
        )
    s.flush()
    s.add(ActivityAnnotation(activity_id=uid(11), version=1, excluded=True))
    s.add(SessionRpe(activity_id=uid(12), source="manual", rpe=8, collected_at=now))
    s.add(Block(block_uid=uid(20)))
    s.flush()
    s.add(
        BlockVersion(
            id=uid(21),
            block_uid=uid(20),
            version=1,
            status="active",
            objective="Race benchmark",
            start_date=day - timedelta(days=21),
            review_date=day + timedelta(days=3),
            progression_dimension="none",
            objective_status="unresolved",
            constraints={},
            target_event_id=uid(0),
            benchmark={
                "kind": "event",
                "event_id": str(uid(0)),
                "planned_date": day.isoformat(),
                "protocol": "race_5k",
            },
        )
    )
    s.add(
        BlockBenchmarkResult(
            id=uid(22),
            block_uid=uid(20),
            block_version=1,
            match_method="auto",
            activity_id=uid(10),
            protocol="race_5k",
            distance_m=5000,
            local_date=day,
            outcome="progress",
            result_s=1103,
        )
    )
    s.add(
        BlockDecision(
            block_uid=uid(20),
            decision="start",
            to_version=1,
            rationale="Fixture",
            confidence="moderate",
            decided_at=now,
        )
    )
    s.add(
        IntensityAnchor(
            anchor_key="fixture",
            kind="hr_aerobic_upper",
            value_low=140,
            unit="bpm",
            protocol="manual",
            confidence="low",
            status="provisional",
            calibrated_at=now,
            valid_from=day,
            review_after=day + timedelta(days=10),
        )
    )
    s.add(
        CoachSnapshot(
            id=uid(30),
            operation="review_rolling_plan",
            as_of=day,
            generated_at=now,
            calendar_version_number=0,
            data_revision=0,
            payload={},
            source_fingerprint="fixture",
            source_versions={},
            kb_digest="fixture",
            payload_sha256="fixture",
            kb_package_version="fixture",
            kb_routes={},
            approx_tokens=0,
        )
    )
    s.flush()
    for i in range(21):
        changes = (
            [{"change_id": "C2", "material_flags": ["strength_omission"]}]
            if i == 20
            else []
        )
        s.add(
            CoachProposal(
                id=uid(40 + i),
                operation="review_rolling_plan",
                snapshot_id=uid(30),
                base_calendar_version=0,
                status="accepted",
                submitted_at=now,
                headline="Fixture",
                confidence={},
                payload={"changes": changes},
                skill_version="fixture",
                input_hash=f"fixture-block-{i}",
            )
        )
    s.flush()
    for change in ("C2", "C1"):
        s.add(
            CoachProposalChange(
                proposal_id=uid(60),
                change_id=change,
                op="add",
                decision="accepted",
                reason="Fixture",
            )
        )


url = make_url(os.environ["DASHBOARD_TEST_DATABASE_URL"]).set(
    drivername="postgresql+psycopg"
)
assert url.database == "garmin_test" and url.host in {"localhost", "127.0.0.1"}
schema = url.query["search_path"]
assert re.fullmatch(r"go_parity_[a-f0-9]{32}", schema)
engine = create_engine(
    url.difference_update_query(["search_path"]).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
)
with Session(engine) as s:
    assert s.scalar(text("SELECT current_schema()")) == schema
    phase = sys.argv[1]
    if phase == "event":
        seed(s)
    if phase == "manual":
        s.get(BlockBenchmarkResult, uid(22)).match_method = "manual"
    if phase in {"pending", "missed"}:
        s.get(BlockBenchmarkResult, uid(22)).match_method = "auto"
        s.get(BlockVersion, uid(21)).benchmark = {
            "kind": "time_trial",
            "protocol": "time_trial_5k",
            "planned_date": day.isoformat(),
        }
    if phase == "trial":
        state = s.get(AppState, 1)
        version = s.scalar(
            text("SELECT coalesce(max(number),0)+1 FROM calendar_versions")
        )
        s.add(
            CalendarVersion(
                id=uid(71),
                number=version,
                parent_number=state.calendar_head_version,
                kind="manual_edit",
                actor="user",
            )
        )
        s.flush()
        state.calendar_head_version = version
        s.add(
            CalendarSessionRevision(
                id=uid(72),
                session_uid=uid(70),
                revision=1,
                calendar_version_number=version,
                local_date=day,
                kind="run",
                recipe_id="REC009",
                intent="Trial",
                certainty="committed",
            )
        )
        s.add(
            SessionCompletion(
                id=uid(73),
                session_uid=uid(70),
                activity_id=uid(12),
                status="completed_as_planned",
                match_method="explicit",
                updated_at=now,
            )
        )
    if phase == "not_set":
        state = s.get(AppState, 1)
        version = s.get(CalendarVersion, uid(71))
        state.calendar_head_version = version.parent_number
        s.delete(s.get(SessionCompletion, uid(73)))
        s.delete(s.get(CalendarSessionRevision, uid(72)))
        s.flush()
        s.delete(version)
        s.get(BlockVersion, uid(21)).benchmark = None
    if phase == "archived":
        s.get(BlockVersion, uid(21)).status = "ended"
    s.commit()
    as_of = day + timedelta(days=6) if phase == "missed" else day
    events = _load_events(s, as_of)
    top = next((e["event_id"] for e in events if e["rank"] == 1), None)
    versions, active = _load_active_block(s, as_of, top)
    print(
        canonical_json(
            {
                "active_block": active,
                "block_decisions": _load_block_decisions(s),
                "benchmark_history": _load_benchmark_history(s, versions),
                "events": events,
                "anchors": _load_anchors(s),
                "proposals": _load_proposals(s),
            }
        )
    )
