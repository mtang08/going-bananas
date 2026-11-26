"""Synthetic exception and travel inputs for a same-database Python/Go comparison."""

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

from app.coach_v2_models import CoachProposal, CoachSnapshot
from app.exception_models import ExceptionFinding, ExceptionPatch
from app.models import ImportBatch
from app.planning_models import Event
from app.services.decision_inputs import canonical_json
from app.services.snapshot.inputs import (
    _load_exception_state,
    _load_review_recommended,
    _load_travel_meta,
    _load_trips,
)
from app.travel_models import GcalEvent, Trip, TripLeg

now = datetime(2026, 11, 2, 3, 30, 0, 125000, tzinfo=UTC)
day = timedelta(days=1)
today = now.date()
home = ZoneInfo("America/New_York")


def uid(i):
    return UUID(int=0xAA00000 + i)


def seed(session):
    op = "review_rolling_plan"
    session.add(
        CoachSnapshot(
            id=uid(1),
            operation=op,
            as_of=today,
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
            approx_tokens=1,
        )
    )
    session.flush()
    session.add(
        CoachProposal(
            id=uid(2),
            operation=op,
            snapshot_id=uid(1),
            base_calendar_version=0,
            status="accepted",
            submitted_at=now - day,
            decided_at=now - day,
            headline="Synthetic review",
            confidence={},
            payload={},
            skill_version="test",
            input_hash="context-read-fixture",
        )
    )
    session.add(
        Event(
            id=uid(3),
            name="Sample Race",
            event_date=today - day,
            purpose="training",
            status="completed",
        )
    )
    session.flush()
    session.add(
        ExceptionPatch(
            id=uid(4),
            proposal_id=uid(2),
            calendar_version_number=0,
            category="training_response",
            severity="hold",
            ladder_level="next_days",
            window_start=today - 30 * day,
            window_end=today - 20 * day,
            reassess_on=today,
            status="open",
            monitor=["synthetic"],
            created_at=now - 30 * day,
        )
    )
    session.flush()
    for i, (code, status, severity, age) in enumerate(
        [
            ("SYNTHETIC_CAUTION", "open", "caution", 30),
            ("SYNTHETIC_ESCALATE", "addressed", "escalate", 30),
            ("POST_EVENT_REVIEW_DUE", "open", "observe", 1),
            ("BLOCK_BENCHMARK_MISSED", "open", "observe", 1),
            ("BLOCK_BENCHMARK_COMPLETED", "open", "observe", 1),
            ("RECENT_TERMINAL", "resolved", "hold", 14),
            ("OLD_TERMINAL", "dismissed", "hold", 15),
        ]
    ):
        session.add(
            ExceptionFinding(
                id=uid(10 + i),
                rule_code=code,
                rule_version="test",
                category="symptoms_illness" if i == 1 else "training_response",
                severity=severity,
                status=status,
                summary="Synthetic signal",
                entity_key=f"event:{uid(3)}" if i == 2 else f"fixture:{i}",
                evidence=[{"synthetic": True}],
                evidence_at=now - age * day,
                first_seen_at=now - age * day,
                last_seen_at=now,
                patch_id=uid(4) if i in (0, 1) else None,
            )
        )

    for i, (offset, end, status) in enumerate(
        [
            (-37, None, "pending"),
            (-38, None, "confirmed"),
            (120, 121, "confirmed"),
            (121, 122, "confirmed"),
            (0, None, "dismissed"),
        ]
    ):
        session.add(
            Trip(
                id=uid(30 + i),
                start_date=today + offset * day,
                end_date=today + end * day if end else None,
                source="detected",
                status=status,
                confidence="medium",
                detected={},
                destination_tz="Asia/Tokyo",
                destination_label="Synthetic City",
                gym_access="limited",
                day_availability=[
                    {"date": today.isoformat(), "availability": "reduced"}
                ],
            )
        )
    session.flush()
    for seq, (dep, arr, status) in enumerate(
        [
            ("America/New_York", "Asia/Tokyo", None),
            ("Bad/Zone", "Asia/Tokyo", None),
            ("UTC", "UTC", "declined"),
        ]
    ):
        session.add(
            GcalEvent(
                id=uid(40 + seq),
                google_event_id=f"snapshot-test-{seq}",
                event_type="default",
                google_status="confirmed",
                all_day=False,
                start_at=now + seq * day,
                end_at=now + (seq + 1) * day,
                start_tz=dep,
                end_tz=arr,
                transparency="opaque",
                busy=True,
                category="flight",
                auto_category="flight",
                category_source="auto",
                first_seen_at=now,
                changed_at=now,
                content_hash="test",
                response_status=status,
                summary="Private synthetic text",
            )
        )
        session.flush()
        session.add(
            TripLeg(
                id=uid(50 + seq),
                trip_id=uid(30),
                gcal_event_id=uid(40 + seq),
                seq=seq,
                leg_hash="test",
            )
        )
    for i, status in enumerate(["complete", "failed"]):
        session.add(
            ImportBatch(
                id=uid(60 + i),
                source_kind="google_calendar",
                status=status,
                finished_at=now + i * day,
            )
        )
    session.commit()


def main():
    url = make_url(os.environ["DASHBOARD_TEST_DATABASE_URL"]).set(
        drivername="postgresql+psycopg"
    )
    schema = url.query["search_path"]
    assert url.database == "garmin_test" and url.host in {"localhost", "127.0.0.1"}
    assert re.fullmatch(r"go_parity_[a-f0-9]{32}", schema)
    url = url.difference_update_query(["search_path"]).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    with Session(create_engine(url)) as session:
        assert session.scalar(text("SELECT current_schema()")) == schema
        if len(sys.argv) > 1:
            for model in [
                TripLeg,
                GcalEvent,
                Trip,
                ImportBatch,
                ExceptionFinding,
                ExceptionPatch,
                Event,
                CoachProposal,
                CoachSnapshot,
            ]:
                session.query(model).filter(model.id.between(uid(1), uid(70))).delete(
                    synchronize_session=False
                )
            session.commit()
            return
        seed(session)
        findings, patches = _load_exception_state(session, today, now)
        print(
            canonical_json(
                {
                    "exception_findings": findings,
                    "exception_patches": patches,
                    "review_recommended": _load_review_recommended(session, today),
                    "trips": _load_trips(session, today, home),
                    "travel_meta": _load_travel_meta(session, home),
                }
            )
        )


if __name__ == "__main__":
    main()
