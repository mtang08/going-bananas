"""Seed synthetic feedback, then read the reference projections for the Go parity test."""

import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "backend"))

from app.checkin_models import Checkin, SymptomReport
from app.domain.first_steps import WALKING_NOTES
from app.metric_models import Prompt
from app.models import Activity
from app.services.decision_inputs import canonical_json
from app.services.snapshot.inputs import _load_checkins, _load_prompts

now = datetime(2026, 11, 2, 3, 30, 0, 125000, tzinfo=UTC)
day = timedelta(days=1)
url = make_url(os.environ["DASHBOARD_TEST_DATABASE_URL"]).set(
    drivername="postgresql+psycopg"
)
assert url.database == "garmin_test" and url.host in {"localhost", "127.0.0.1"}
schema = url.query["search_path"]
assert re.fullmatch(r"go_parity_[a-f0-9]{32}", schema)
url = url.difference_update_query(["search_path"]).update_query_dict(
    {"options": f"-csearch_path={schema}"}
)
with Session(create_engine(url)) as session:
    schema = session.scalar(text("SELECT current_schema()"))
    assert re.fullmatch(r"go_parity_[a-f0-9]{32}", schema)
    activity = UUID(int=100)
    session.add(
        Activity(
            id=activity,
            sport="running",
            original_start="test",
            start_at=now - day,
            end_at=now - timedelta(hours=1.25),
            local_date=now.date(),
        )
    )
    session.flush()
    observations = [
        (0, now - 120 * day, now, WALKING_NOTES[None], []),
        (1, now, now, WALKING_NOTES["eased"], [2.5]),
        (2, now, now, "Private synthetic text", [1, 3]),
        (3, now, now, WALKING_NOTES["eased"], [1, 2]),
        (4, now - 121 * day, now, None, []),
        (5, now, now + day, None, []),
        (6, now + day, now, None, []),
        (7, now, now, WALKING_NOTES[None], []),
    ]
    for i, observed, recorded, note, symptoms in observations:
        checkin = UUID(int=200 + i)
        key = "different-form" if i == 7 else f"phone-first-steps:{i}"
        session.add(
            Checkin(
                id=checkin,
                idempotency_key=key,
                kind="exception",
                observed_at=observed,
                recorded_at=recorded,
                activity_id=activity if i < 2 else None,
                note=note,
                fatigue=4.5 if i == 1 else None,
            )
        )
        session.flush()
        for j, severity in reversed(list(enumerate(symptoms))):
            session.add(
                SymptomReport(
                    id=UUID(int=1000 + i * 10 + j),
                    checkin_id=checkin,
                    site="ankle",
                    side="left",
                    severity=severity,
                    timing="next_morning",
                )
            )
    for i, (opens, closes, status) in enumerate(
        [
            (now - 120 * day, now, "open"),
            (now, None, "open"),
            (now, now - day, "answered"),
            (now + day, None, "open"),
            (now - 121 * day, None, "open"),
        ]
    ):
        session.add(
            Prompt(
                id=UUID(int=300 + i),
                kind="delayed_symptom",
                session_uid=UUID(int=400 + i),
                opens_at=opens,
                closes_at=closes,
                status=status,
            )
        )
    session.commit()
    print(
        canonical_json(
            {
                "checkins": _load_checkins(session, now, ZoneInfo("America/New_York")),
                "prompts": _load_prompts(session, now),
            }
        )
    )
