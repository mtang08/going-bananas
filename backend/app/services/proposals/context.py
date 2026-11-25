"""Coach proposal context."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import global_write_lock
from app.domain.athlete_facts import running_restriction
from app.domain.local_time import date_in_zone
from app.domain.running_interruption import running_interruption
from app.read.calendar import head_version
from app.services.block_benchmark import active_block_version, last_credible_result_date
from app.services.decision_inputs import (
    VerifiedKnowledge,
    collect_decision_inputs,
)
from app.services.events import ranked_upcoming
from app.services.profile import current_profile
from app.services.proposals.schema import (
    ActiveBlock,
    EventRef,
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
    return (
        ActiveBlock(row.block_uid, row.id, row.version, tuple(row.eligible_recipe_ids), row.review_date)
        if row
        else None
    )


def _event_refs(session: Session, today: date) -> dict[uuid.UUID, EventRef]:
    from app.planning_models import Event

    rows = list(session.scalars(select(Event)))
    ranks = {row.id: rank for rank, row in ranked_upcoming(rows, today)}
    return {row.id: EventRef(row.status, row.event_date, ranks.get(row.id), row.purpose) for row in rows}


def load_context(
    session: Session, snapshot_id: uuid.UUID, *, now: datetime, kb: VerifiedKnowledge
) -> ValidationContext:
    from app.coach_v2_models import CoachSnapshot
    from app.exception_models import ExceptionFinding, ExceptionPatch
    from app.planning_models import BlockVersion
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
            row.get("brief"),
        )
        for row in rows
    }
    profile = current_profile(session)
    anchor = profile.cycle_anchor if profile and profile.anchor_confirmed else None
    inputs: dict[str, Any] = (
        collect_decision_inputs(session, snapshot.operation, snapshot.as_of, now=now, kb=kb)
        if snapshot
        else {"source_fingerprint": "", "safety_guard": None}
    )
    active = active_block(session)
    active_row = session.get(BlockVersion, active.version_id) if active else None
    strength_schedule = {
        date.fromisoformat(row["local_date"]): row.get("strength_slot_id")
        for row in inputs.get("confirmed_strength_sessions", [])
    }
    accepted_omissions = {
        date.fromisoformat(row["local_date"]): row.get("strength_slot_id")
        for row in inputs.get("source_versions", {}).get("accepted_strength_omissions", [])
    }
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
        events=_event_refs(session, today),
        open_rule_codes=frozenset(
            session.scalars(select(ExceptionFinding.rule_code).where(ExceptionFinding.status == "open"))
        ),
        benchmark=benchmark_status(session, active_row, today) if active_row else None,
        last_benchmark_date=last_credible_result_date(session),
        confirmed_strength_dates=frozenset(strength_schedule),
        confirmed_strength_slot_ids={day: uuid.UUID(slot) for day, slot in strength_schedule.items() if slot},
        running_restriction=running_restriction(profile.facts) if profile else None,
        running_interruption=running_interruption(profile.facts) if profile else None,
        accepted_strength_omission_dates=frozenset(accepted_omissions),
        accepted_strength_omission_slot_ids={day: uuid.UUID(slot) for day, slot in accepted_omissions.items() if slot},
    )
