"""Coach proposal context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import global_write_lock
from app.domain.local_time import date_in_zone
from app.read.calendar import head_version
from app.services.block_benchmark import active_block_version
from app.services.decision_inputs import (
    VerifiedKnowledge,
    collect_decision_inputs,
)
from app.services.profile import current_profile
from app.services.proposals.schema import (
    ActiveBlock,
    HeadSession,
    SnapshotRef,
    ValidationContext,
)


def lock_planning(session: Session) -> Any:
    from app.models import AppState

    global_write_lock(session)
    state = session.get(AppState, 1, with_for_update=True, populate_existing=True)
    assert state is not None
    return state


def snapshot_ref(row: Any) -> SnapshotRef:
    meta = (row.payload or {}).get("snapshot_meta") or {}
    routes = row.kb_routes
    selection = routes.get("selection", []) if isinstance(routes, dict) else routes
    return SnapshotRef(
        row.id,
        row.operation,
        row.as_of,
        row.generated_at,
        row.source_fingerprint,
        tuple(selection),
        row.kb_digest,
        meta.get("safety_guard"),
    )


def active_block(session: Session) -> ActiveBlock | None:
    row = active_block_version(session)
    return ActiveBlock(row.block_uid, row.id, row.version, tuple(row.eligible_recipe_ids)) if row else None


def load_context(
    session: Session, snapshot_id: uuid.UUID, *, now: datetime, kb: VerifiedKnowledge
) -> ValidationContext:
    from app.coach_v2_models import CoachSnapshot
    from app.exception_models import ExceptionFinding, ExceptionPatch
    from app.planning_models import BlockVersion, Event
    from app.services.block_benchmark import benchmark_status
    from app.services.calendar import state_at
    from app.services.timezone import athlete_tz

    snapshot = session.get(CoachSnapshot, snapshot_id)
    tz = athlete_tz(session)
    today = date_in_zone(now, tz)
    head = head_version(session)
    rows = state_at(session, head)
    head_sessions = {
        row["session_uid"]: HeadSession(
            row["session_uid"],
            row["revision"],
            row["local_date"],
            row["slot"],
            row["kind"],
            row.get("recipe_id"),
            row.get("custom", False),
            row.get("placeholder", False),
            row.get("locked", False),
            row.get("legacy_unstructured", False),
            row.get("intent", ""),
            row.get("certainty", ""),
            row.get("planned_duration_s"),
            row.get("planned_distance_m"),
            row.get("structure"),
            row.get("strength_slot_id"),
            row.get("notes"),
        )
        for row in rows
    }
    profile = current_profile(session)
    anchor = profile.cycle_anchor if profile and profile.anchor_confirmed else None
    inputs = (
        collect_decision_inputs(session, snapshot.operation, snapshot.as_of, now=now, kb=kb)
        if snapshot
        else {"source_fingerprint": "", "safety_guard": None}
    )
    active = active_block(session)
    active_row = session.get(BlockVersion, active.version_id) if active else None
    return ValidationContext(
        now,
        today,
        tz,
        snapshot_ref(snapshot) if snapshot else None,
        head,
        head_sessions,
        active,
        anchor,
        inputs["safety_guard"] if isinstance(inputs["safety_guard"], dict) else None,
        str(inputs["source_fingerprint"]),
        kb.digest,
        kb,
        findings={fid: status for fid, status in session.execute(select(ExceptionFinding.id, ExceptionFinding.status))},
        patches={pid: status for pid, status in session.execute(select(ExceptionPatch.id, ExceptionPatch.status))},
        events={
            eid: (status, day) for eid, status, day in session.execute(select(Event.id, Event.status, Event.event_date))
        },
        open_rule_codes=frozenset(
            session.scalars(select(ExceptionFinding.rule_code).where(ExceptionFinding.status == "open"))
        ),
        benchmark=benchmark_status(session, active_row, today) if active_row else None,
    )
