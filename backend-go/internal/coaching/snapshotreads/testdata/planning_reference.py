"""Exercise head selection, date bounds, and the source priority for a recorded lift."""
import os
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "backend"))

from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.checkin_models import SessionRpe
from app.models import AppState, RawObject, SourceAccount, SourceRecord
from app.planning_models import Goal, StrengthRoutineSlot
from app.services.decision_inputs import canonical_json
from app.services.snapshot.inputs import (
    _load_completions, _load_goals, _load_sessions, _load_strength_slots, _load_strong_workouts,
)
from app.strong_models import StrongWorkoutRow

day = date(2026, 3, 8)
now = datetime(2026, 3, 8, tzinfo=UTC)
with Session(create_engine(os.environ["DATABASE_URL"])) as session:
    assert session.scalar(text("SELECT current_database()")) == "garmin_test"
    assert re.fullmatch(r"go_parity_[a-f0-9]{32}", session.scalar(text("SELECT current_schema()")))
    state = session.get(AppState, 1)
    base = session.scalar(text("SELECT coalesce(max(number), 0) FROM calendar_versions"))
    for n in (1, 2, 3):
        session.add(CalendarVersion(number=base+n, kind="manual_edit", actor="user"))
    session.flush()
    state.calendar_head_version = head = base + 2
    for n, revision, version, offset, deleted in [
        (1,1,1,0,False), (1,2,2,7,False), (1,3,3,0,False),
        (2,1,1,-120,False), (3,1,1,-121,False), (4,1,1,42,False), (5,1,1,43,False),
        (6,1,1,1,False), (6,2,2,1,True),
    ]:
        session.add(CalendarSessionRevision(session_uid=UUID(int=16000+n), revision=revision,
                    calendar_version_number=base+version, deleted=deleted, local_date=day+timedelta(days=offset),
                    kind="run", intent="Synthetic", certainty="committed"))
    session.add(SessionCompletion(session_uid=UUID(int=16001), status="skipped", match_method="user_marked", updated_at=now))
    for priority,status in [(1,"active"), (2,"paused")]:
        session.add(Goal(text="Synthetic goal", horizon="season", priority=priority, status=status))
    session.add(StrengthRoutineSlot(label="Synthetic", default_weekday=1, lower_body_cost="low",
                                    main_lower_body_lifts=[]))
    account = SourceAccount(provider="strong", account_scope="snapshot-parity")
    raw = RawObject(sha256="c"*64, relative_path="synthetic", byte_size=0, media_type="text/csv")
    session.add_all([account,raw])
    session.flush()
    record = SourceRecord(source_account_id=account.id, raw_object_id=raw.id, source_identity="synthetic",
                          payload_hash="b"*64, fetched_at=now, parser_version="1", source_kind="strength")
    session.add(record)
    session.flush()
    for i, offset, resolution in [(1,0,"resolved"), (2,-121,"resolved"), (3,1,"resolved")]:
        workout = StrongWorkoutRow(source_account_id=account.id, source_record_id=record.id, raw_object_id=raw.id,
            source_identity=str(i), payload_hash="b"*64, local_date=day+timedelta(days=offset),
            local_start="2026-03-08T08:00:00", workout_name="Synthetic", duration_s=1200, sets=[], row_count=1,
            resolution_state=resolution)
        session.add(workout)
        session.flush()
        for source,rpe in [("manual",3),("garmin_fit",6)]:
            session.add(SessionRpe(strong_workout_id=workout.id, rpe=rpe, source=source, collected_at=now))
    session.commit()
    first = day - timedelta(days=120)
    workouts = session.scalars(select(StrongWorkoutRow).where(StrongWorkoutRow.resolution_state=="resolved",
        StrongWorkoutRow.local_date.between(first,day)).order_by(StrongWorkoutRow.local_date,StrongWorkoutRow.id)).all()
    print(canonical_json(dict(sessions=_load_sessions(session,head,first,day),
        completions=sorted(_load_completions(session),key=lambda r:str(r["session_uid"])), goals=_load_goals(session),
        strength_slots=_load_strength_slots(session), strong_workouts=_load_strong_workouts(workouts,session.scalars(
            select(SessionRpe).order_by(SessionRpe.collected_at,SessionRpe.id)).all()))))
