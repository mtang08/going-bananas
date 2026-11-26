"""Compare the composed inputs with Python and expose the owner-provided inputs separately."""

import os
import re
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "backend"))
from app.models import Activity, CoverageInterval, ProfileVersion
from app.services.decision_inputs import (
    VerifiedKnowledge,
    canonical_json,
    collect_decision_inputs,
)
from app.services.running_interruption import return_view
from app.services.snapshot.inputs import load_inputs

as_of = date(2027, 3, 14)
now = datetime(2027, 3, 14, 14, 0, tzinfo=UTC)
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
    s.add(
        ProfileVersion(
            version=s.scalar(
                text("SELECT coalesce(max(version),0)+1 FROM profile_versions")
            ),
            timezone="America/New_York",
            effective_at=now - timedelta(days=14),
            anchor_confirmed=True,
            strength_days_confirmed=True,
            scheduled_strength_days=[1, 3],
            facts={
                "running_interruption": {
                    "starts_on": "2027-03-13",
                    "review_on": "2027-03-17",
                    "reason": "schedule",
                }
            },
        )
    )
    s.add(
        Activity(
            sport="running",
            original_start="fixture",
            start_at=now - timedelta(days=3),
            local_date=as_of - timedelta(days=3),
            timer_s=1500,
            distance_m=3920,
        )
    )
    for first, last in ((120, 51), (50, 0)):
        s.add(
            CoverageInterval(
                dataset="activities",
                start_date=as_of - timedelta(days=first),
                end_date=as_of - timedelta(days=last),
                status="complete",
                fully_enumerated=True,
            )
        )
    s.commit()
    inputs = load_inputs(s, as_of, now=now)
    decision = collect_decision_inputs(
        s,
        "review_rolling_plan",
        as_of,
        now=now,
        kb=VerifiedKnowledge("fixture", (), (), frozenset(), frozenset(), frozenset()),
    )
    inputs.confirmed_strength_sessions = decision["confirmed_strength_sessions"]
    inputs.accepted_strength_omissions = decision["source_versions"].get(
        "accepted_strength_omissions", []
    )
    print(
        canonical_json(
            {
                "expected": asdict(inputs),
                "weeks": inputs.weekly_digest,
                "return_view": return_view(s, as_of),
                "confirmed": inputs.confirmed_strength_sessions,
                "omissions": inputs.accepted_strength_omissions,
            }
        )
    )
