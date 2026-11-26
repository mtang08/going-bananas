"""Compare live decision inputs and saved snapshot freshness on an isolated test DB.

Run in APP_MODE=test with DATABASE_URL for the local garmin_test database,
using the backend Python environment and Go on PATH.
"""

import os
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
DAY = date(2026, 11, 19)
NOW = datetime(2026, 11, 19, 16, 22, 0, 123456, UTC)
OP = "proceed_or_modify_today"


def exercise(engine, env, scratch):
    from app.api.coach import resolve_kb
    from app.calendar_models import CalendarSessionRevision, CalendarVersion
    from app.coach_v2_models import CoachProposal, CoachProposalChange, CoachSnapshot
    from app.demo_seed import seed_demo
    from app.fit_models import FitFile
    from app.models import (
        Activity,
        ActivityAnnotation,
        ManualSession,
        RawObject,
        SourceRecord,
    )
    from app.planning_models import Block, BlockVersion, Event, Goal, IntensityAnchor
    from app.services.decision_inputs import canonical_json, collect_decision_inputs
    from app.services.proposals.lifecycle import submit_proposal
    from app.services.snapshot.build import build_snapshot
    from app.strong_models import StrongWorkoutRow

    def snapshot():
        with Session(engine) as s, s.begin():
            return UUID(build_snapshot(s, OP, DAY, now=NOW)["snapshot_id"])

    def compare(sid, label, fresh=True):
        with Session(engine) as s:
            snap = s.get(CoachSnapshot, sid)
            kb = resolve_kb(tuple(snap.kb_routes))
            d = collect_decision_inputs(s, OP, DAY, now=NOW, kb=kb)
            assert (snap.source_fingerprint == d["source_fingerprint"]) == fresh, label
            sample = {
                "Operation": OP,
                "AsOf": DAY.isoformat(),
                "Now": NOW.isoformat(),
                "Selection": snap.kb_routes,
                "SavedHash": snap.source_fingerprint,
                "Fresh": fresh,
                "Sources": d["source_versions"],
                "Guard": d["safety_guard"],
                "Schedule": d["confirmed_strength_sessions"],
                "CurrentHash": d["source_fingerprint"],
            }
            (scratch / "reference.json").write_text(canonical_json(sample))
        subprocess.run(
            [
                "go",
                "test",
                "-count=1",
                "-run",
                "^TestPythonDecisionInputs$",
                "./internal/coaching/evidence",
            ],
            cwd=ROOT / "backend-go",
            env=env,
            check=True,
        )
        print("PASS", label, flush=True)
        return d

    initial = snapshot()
    with Session(engine) as s, s.begin():
        draft = submit_proposal(
            s,
            {
                "schema_version": "coach_proposal.v2",
                "operation": OP,
                "snapshot_id": str(initial),
                "base_calendar_version": 0,
                "base_block_version_id": None,
                "headline": "Easy day",
                "why": [{"kind": "observation", "text": "Synthetic session"}],
                "uncertainty": ["Synthetic uncertainty"],
                "change_triggers": [{"when": "Energy drops", "then": "Rest"}],
                "next_check": {"on": DAY.isoformat(), "check": "Review response"},
                "confidence": {
                    "decision": "moderate",
                    "evidence": "moderate",
                    "data": "moderate",
                },
                "changes": [
                    {
                        "change_id": "c1",
                        "op": "add",
                        "after": {
                            "local_date": DAY.isoformat(),
                            "kind": "rest",
                            "intent": "Recovery",
                        },
                        "reason": "Recovery day",
                    }
                ],
                "evidence_ids": [],
                "policy_ids": [],
                "recipe_ids": [],
                "skill_version": "running-coach.v1",
            },
            now=NOW,
            resolve_kb=resolve_kb,
        )
        assert draft.status == "pending", draft.issues
    compare(initial, "fresh Python-created pending draft")
    with Session(engine) as s, s.begin():
        s.add(
            Goal(
                text="Initial synthetic goal",
                horizon="season",
                priority=1,
                status="active",
            )
        )
    compare(initial, "pending draft becomes stale after first goal", False)
    with Session(engine) as s, s.begin():
        # Freeze only the demo seed's real-time calendar protection check.
        with patch("app.services.calendar.calendar_today", return_value=DAY):
            seed_demo(s, scratch, DAY)
        s.execute(
            text("""update profile_versions set effective_at='2026-11-01T21:00:00Z',
            facts='{"clinician_restriction":"synthetic","old_number": 9007199254740993,"threshold": 1.0}',
            unknowns='["unknown"]', strength_schedule_mode='alternating',strength_week_a_start='2026-11-09',
            strength_week_a_days='[0,4]',strength_week_b_days='[1,5]'""")
        )
        s.execute(
            text(
                """update checkins_v2 set observed_at=:cutoff, illness='present',gait_change='yes'"""
            ),
            {"cutoff": NOW - timedelta(hours=72)},
        )
        activity = s.scalars(select(Activity).order_by(Activity.id)).first()
        raw = RawObject(
            sha256="f" * 64,
            relative_path="synthetic.fit",
            byte_size=1,
            media_type="application/zip",
        )
        unrelated = RawObject(
            sha256="e" * 64,
            relative_path="unselected.bin",
            byte_size=2,
            media_type="application/octet-stream",
        )
        s.add_all([raw, unrelated])
        s.flush()
        src = s.scalars(select(SourceRecord).order_by(SourceRecord.id)).first()
        s.add(
            FitFile(
                raw_object_id=raw.id,
                activity_id=activity.id,
                zip_sha256=raw.sha256,
                fit_sha256="a" * 64,
                message_inventory={},
                device={},
            )
        )
        s.add(
            StrongWorkoutRow(
                source_account_id=src.source_account_id,
                source_identity="synthetic-strength",
                source_record_id=src.id,
                raw_object_id=raw.id,
                payload_hash="b" * 64,
                local_date=DAY,
                local_start=DAY.isoformat() + " 12:00:00",
                workout_name="Synthetic",
                sets=[],
                row_count=1,
            )
        )
        s.add(
            IntensityAnchor(
                anchor_key="synthetic-anchor",
                kind="hr_aerobic_upper",
                value_low=145,
                value_high=149.5,
                unit="bpm",
                protocol="manual",
                confidence="moderate",
                status="active",
                calibrated_at=NOW,
                valid_from=DAY,
                review_after=DAY + timedelta(days=28),
            )
        )
        block = Block(block_uid=uuid4())
        s.add(block)
        s.flush()
        s.add(
            BlockVersion(
                block_uid=block.block_uid,
                version=1,
                status="active",
                objective="Synthetic",
                progression_dimension="none",
                constraints=[],
                start_date=DAY,
                review_date=DAY + timedelta(days=30),
                objective_status="unresolved",
            )
        )
        unrelated_id = str(unrelated.id)
        s.add(
            ActivityAnnotation(
                activity_id=activity.id,
                version=1,
                workout_label="synthetic",
                excluded=False,
            )
        )
        s.add(ManualSession(date=DAY, kind="strength", effort=3, duration_s=1200.0))
        s.add(
            Goal(text="Synthetic goal", horizon="season", priority=1, status="active")
        )
        s.add(
            Event(
                name="Synthetic 10K",
                event_date=DAY + timedelta(days=12),
                purpose="pr",
                status="registered",
            )
        )
    original = snapshot()
    decision = compare(original, "populated Python snapshot")
    proven = decision["source_versions"]
    for key in (
        "activities",
        "checkins",
        "recovery",
        "goals",
        "coverage",
        "anchors",
        "annotations",
        "symptoms",
        "fit_files",
        "activity_sources",
        "source_records",
        "raw_objects",
        "completions",
        "session_rpe",
        "manual_sessions",
        "strong_workouts",
        "routine_slots",
        "events",
        "trips",
        "block",
        "profile",
    ):
        assert proven[key], key
    assert unrelated_id not in {r["id"] for r in proven["raw_objects"]}
    assert decision["safety_guard"]["max_symptom_severity"] == 2.0
    assert decision["safety_guard"]["clinical_restriction_active"]
    with Session(engine) as s, s.begin():
        s.execute(
            text("update goals set version=version+1,text='Revised synthetic goal'")
        )
    compare(original, "changed source makes original stale", False)
    with Session(engine) as s, s.begin():
        lift = next(
            r
            for r in decision["confirmed_strength_sessions"]
            if r["local_date"] >= DAY.isoformat()
        )
        p = CoachProposal(
            operation=OP,
            snapshot_id=original,
            base_calendar_version=decision["source_versions"]["calendar"],
            submitted_at=NOW,
            decided_at=NOW,
            headline="Synthetic decision",
            confidence={},
            skill_version="reference",
            input_hash="1" * 64,
            status="accepted",
            payload={
                "changes": [
                    {"change_id": "c1", "material_flags": ["strength_omission"]}
                ]
            },
        )
        s.add(p)
        s.flush()
        s.add(
            CoachProposalChange(
                proposal_id=p.id,
                change_id="c1",
                op="add",
                after=lift,
                reason="Synthetic omission",
                decision="accepted",
            )
        )
    revised = snapshot()
    d = compare(revised, "accepted strength omission")
    assert (
        d["source_versions"]["accepted_strength_omissions"][0]["reason"]
        == "Synthetic omission"
    )

    with Session(engine) as s, s.begin():
        head = proven["calendar"]
        version = CalendarVersion(
            number=head + 1, parent_number=head, kind="manual_edit", actor="user"
        )
        s.add(version)
        s.flush()
        omitted_day = date.fromisoformat(lift["local_date"])
        # The original slot was restored on another day of the same week.
        moved_day = omitted_day + timedelta(
            days=1 if omitted_day.weekday() != 6 else -1
        )
        s.add(
            CalendarSessionRevision(
                session_uid=uuid4(),
                revision=1,
                calendar_version_number=head + 1,
                local_date=moved_day,
                kind="strength",
                strength_slot_id=UUID(lift["strength_slot_id"]),
                intent="Synthetic reinstatement",
                certainty="committed",
            )
        )
    retired = compare(revised, "reinstated weekly slot retires the omission", False)
    assert "accepted_strength_omissions" not in retired["source_versions"]


def main():
    url = make_url(os.environ["DATABASE_URL"])
    if (
        os.getenv("APP_MODE") != "test"
        or url.database != "garmin_test"
        or url.host not in ("localhost", "127.0.0.1")
    ):
        raise ValueError("requires the isolated local garmin_test database")
    pg = url.set(drivername="postgresql").render_as_string(hide_password=False)
    schema = "go_evidence_" + uuid4().hex
    (ROOT / "private").mkdir(exist_ok=True)
    with psycopg.connect(pg, autocommit=True) as admin, ExitStack() as stack:
        scratch = Path(
            stack.enter_context(tempfile.TemporaryDirectory(dir=ROOT / "private"))
        )
        admin.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
        stack.callback(
            admin.execute,
            sql.SQL("drop schema {} cascade").format(sql.Identifier(schema)),
        )
        options = "-csearch_path=" + schema + " -cTimeZone=Asia/Kathmandu"
        target = url.update_query_dict({"options": options})
        env = dict(
            os.environ,
            PRIVATE_DIR=str(scratch),
            DATABASE_URL=target.render_as_string(hide_password=False),
            PGOPTIONS=options,
            EVIDENCE_REFERENCE=str(scratch / "reference.json"),
            EVIDENCE_DATABASE_URL=pg,
        )
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "backend",
            env=env,
            check=True,
        )
        engine = create_engine(target)
        stack.callback(engine.dispose)
        with engine.connect() as c:
            assert c.execute(text("select current_schema()")).scalar_one() == schema
        exercise(engine, env, scratch)


if __name__ == "__main__":
    main()
