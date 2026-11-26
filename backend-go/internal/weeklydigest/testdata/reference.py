"""Seed shared weekly-digest integration scenarios in a disposable PostgreSQL schema."""

import os
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

root = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(root / "backend"), str(root / "backend/tests/integration")]
from app.calendar_models import (
    CalendarSessionRevision,
    CalendarVersion,
    SessionCompletion,
)
from app.checkin_models import Checkin, SessionRpe, SymptomReport
from app.coach_v2_models import CoachProposal, CoachProposalChange, CoachSnapshot
from app.models import ActivityAnnotation, AppState, CoverageInterval, ManualSession
from app.services.decision_inputs import canonical_json
from app.services.weekly_digest import load_week
from test_weekly_digest import _activity, _metric, _revision, _strong

url = make_url(os.environ["DASHBOARD_TEST_DATABASE_URL"]).set(
    drivername="postgresql+psycopg"
)
assert url.database == "garmin_test" and url.host in {"localhost", "127.0.0.1"}
schema = url.query["search_path"]
assert re.fullmatch(r"go_parity_[a-f0-9]{32}", schema)
engine = create_engine(
    url.difference_update_query(["search_path"]).update_query_dict(
        {"options": f"-csearch_path={schema} -cTimeZone=Asia/Kathmandu"}
    )
)
today = date(2030, 1, 9)
now = datetime(2030, 1, 9, 18, 30, tzinfo=UTC)
with Session(engine) as s:
    assert s.scalar(text("SELECT current_schema()")) == schema
    snapshot = CoachSnapshot(
        operation="review_rolling_plan",
        as_of=today,
        generated_at=now,
        calendar_version_number=0,
        data_revision=0,
        payload={},
        source_fingerprint="weekly",
        source_versions={},
        kb_digest="fixture",
        payload_sha256="weekly",
        kb_package_version="fixture",
        kb_routes={},
        approx_tokens=0,
    )
    s.add(snapshot)
    s.flush()
    p = CoachProposal(
        snapshot_id=snapshot.id,
        operation="review_rolling_plan",
        base_calendar_version=0,
        status="accepted",
        submitted_at=now - timedelta(days=7),
        decided_at=now - timedelta(days=5),
        headline="Synthetic",
        confidence={},
        next_check={"when": "post-run"},
        payload={},
        skill_version="fixture",
        input_hash="weekly-digest-fixture",
    )
    s.add(p)
    s.flush()
    v = s.scalar(text("SELECT coalesce(max(number),0)+1 FROM calendar_versions"))
    s.add_all(
        [
            CalendarVersion(
                number=v, kind="proposal_accept", actor="user", proposal_id=p.id
            ),
            CalendarVersion(
                number=v + 1, kind="manual_edit", actor="user", parent_number=v
            ),
        ]
    )
    s.flush()
    state = s.get(AppState, 1)
    state.calendar_head_version = v + 1
    ids = [uuid4() for _ in range(9)]
    for i, (day, kind, intent, recipe, duration) in enumerate(
        [
            (7, "run", "Long", "REC002", 1800),
            (8, "run", "Tempo", "REC003", 1200),
            (8, "strength", "Lift", None, None),
            (9, "run", "Easy", None, 1000),
            (12, "run", "Future", None, None),
            (11, "run", "Moved", None, 1600),
            (7, "mobility", "Mobility", None, None),
            (8, "run", "Removed", None, None),
            (8, "run", "Self-reported", None, 1800),
        ]
    ):
        _revision(
            s, ids[i], v, 1, day, kind, intent=intent, recipe=recipe, duration=duration
        )
    _revision(
        s,
        ids[1],
        v + 1,
        2,
        8,
        "run",
        intent="Tempo modified",
        recipe="REC003",
        duration=1500,
        distance=5000,
    )
    _revision(s, ids[7], v + 1, 2, 9, "run", intent="Removed", deleted=True)
    s.flush()
    accepted = s.scalar(
        select(CalendarSessionRevision).where(
            CalendarSessionRevision.session_uid == ids[1],
            CalendarSessionRevision.revision == 1,
        )
    )
    accepted.brief = {"effort": "Firm"}
    s.add(
        CoachProposalChange(
            proposal_id=p.id,
            change_id="C1",
            session_uid=ids[1],
            op="modify",
            decision="accepted",
            reason="Adjust dose",
        )
    )
    a, b, early = [
        _activity(s, day, timer, dist)
        for day, timer, dist in [(7, 1800, 4100), (8, 1050, 3800), (6, 1550, 3700)]
    ]
    b.end_at = b.start_at + timedelta(seconds=1050)
    b.moving_s = 990
    b.avg_hr_bpm = 133
    s.add(SessionRpe(activity_id=b.id, rpe=6.5, source="manual", collected_at=now))
    s.add(
        ActivityAnnotation(
            activity_id=_activity(s, 8, 900, 9999).id, version=1, excluded=True
        )
    )
    _activity(s, 7, 350, 999)
    _activity(s, 7, 200, 400, hour=2)  # Previous athlete-local week despite stored date.
    lift = _strong(s, 8, 3000)
    for i, sub, status, method in [
        (0, {"activity_id": a.id}, "completed_as_planned", "explicit"),
        (1, {"activity_id": b.id}, "completed_modified", "explicit"),
        (2, {"strong_workout_id": lift.id}, "completed_as_planned", "explicit"),
        (5, {"activity_id": early.id}, "moved", "confirmed_move"),
        (8, {}, "completed_as_planned", "user_marked"),
    ]:
        s.add(
            SessionCompletion(
                session_uid=ids[i],
                status=status,
                match_method=method,
                updated_at=now,
                **sub,
            )
        )
    s.add(ManualSession(date=today, kind="cross", duration_s=600))
    s.add(
        ManualSession(date=today, kind="run", duration_s=150, linked_activity_id=b.id)
    )
    s.add(
        CoverageInterval(
            dataset="activities",
            start_date=today - timedelta(days=3),
            end_date=today,
            status="complete",
            fully_enumerated=True,
        )
    )
    _metric(
        s,
        "planned_actual_session",
        "v2",
        "session",
        str(ids[1]),
        {"components": [{"name": "time", "value": 0.8, "status": "met"}]},
    )
    _metric(
        s,
        "work_interval_execution",
        "v2",
        "activity",
        str(b.id),
        {"n_planned": 4, "n_completed": 3},
    )
    check = Checkin(
        idempotency_key="weekly-digest",
        kind="delayed_followup",
        activity_id=b.id,
        observed_at=now - timedelta(minutes=20),
        recorded_at=now,
        pain_reported=True,
        gait_change="no",
    )
    s.add(check)
    s.flush()
    s.add(
        SymptomReport(
            checkin_id=check.id,
            site="ankle",
            side="left",
            severity=2.5,
            timing="next_morning",
        )
    )
    s.commit()
    print(
        canonical_json(
            [
                load_week(s, date.fromisoformat(week), today=today, now=now)
                for week in ["2030-01-07", "2029-12-31", "2030-01-14"]
            ]
        )
    )
