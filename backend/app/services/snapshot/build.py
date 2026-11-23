"""Snapshot build."""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.coach_v2_models import CoachSnapshot
from app.db import global_write_lock
from app.models import AppState
from app.services.decision_inputs import VerifiedKnowledge, canonical_json, collect_decision_inputs
from app.services.knowledge import load_route, verify_selection
from app.services.snapshot.common import (
    BLOCK,
    DAILY,
    EXCEPTION,
    MISSING,
    POST_EVENT,
    QUALITY_OP,
    ROLLING,
    source_provenance,
)
from app.services.snapshot.inputs import load_inputs
from app.services.snapshot.payload import build_payload
from app.services.snapshot.topics import select_conditional_topics, select_recipe_ids


def build_snapshot(
    session: Session, operation: str, as_of: date, *, now: datetime, kb_root: Path | None = None
) -> dict:
    from app.metrics.refresh import ensure_nights, ensure_windows

    global_write_lock(session)
    session.execute(select(AppState.id).where(AppState.id == 1).with_for_update())
    previous_now = session.info.get("metrics_now", MISSING)
    session.info["metrics_now"] = now
    try:
        ensure_windows(session, as_of)
        if operation in {DAILY, ROLLING, QUALITY_OP, BLOCK, EXCEPTION, POST_EVENT}:
            days = {DAILY: 3, ROLLING: 14, QUALITY_OP: 14, BLOCK: 28, EXCEPTION: 3, POST_EVENT: 14}[operation]
            ensure_nights(session, as_of - timedelta(days=days - 1), as_of)
        if operation in {EXCEPTION, POST_EVENT, ROLLING, BLOCK}:
            from app.services.exceptions.detector import run_detection

            run_detection(session, now)
        inputs = load_inputs(session, as_of, now=now)
        bundle = load_route(
            operation,
            recipe_ids=select_recipe_ids(inputs, operation),
            conditional_topics=select_conditional_topics(inputs, operation),
            root=kb_root,
        )
        kb = VerifiedKnowledge(**verify_selection(tuple(bundle.routes), root=kb_root))
        decision = collect_decision_inputs(session, operation, as_of, now=now, kb=kb)
        inputs.confirmed_strength_sessions = decision.get("confirmed_strength_sessions", [])
        inputs.accepted_strength_omissions = decision["source_versions"].get("accepted_strength_omissions", [])
        payload = build_payload(inputs, operation)
        meta = payload["snapshot_meta"]
        meta["source_fingerprint"] = decision["source_fingerprint"]
        meta["source_provenance"] = source_provenance(decision["source_versions"])
        meta["safety_guard"] = decision["safety_guard"]
        meta["knowledge"] = {"digest": kb.digest, "selected_records": list(kb.selected_records)}
        payload_json = canonical_json(payload)
        approx_tokens = math.ceil((len(payload_json) + bundle.chars) / 4)
        row = CoachSnapshot(
            operation=operation,
            as_of=as_of,
            generated_at=now,
            calendar_version_number=inputs.calendar_version or 0,
            block_version_id=inputs.active_block.get("version_id") if inputs.active_block else None,
            data_revision=inputs.data_revision,
            payload=payload,
            payload_sha256=hashlib.sha256(payload_json.encode()).hexdigest(),
            kb_package_version=bundle.package_version,
            kb_routes=list(kb.selection),
            kb_digest=kb.digest,
            source_fingerprint=decision["source_fingerprint"],
            source_versions=decision["source_versions"],
            approx_tokens=approx_tokens,
        )
        session.add(row)
        session.flush()
    finally:
        if previous_now is MISSING:
            session.info.pop("metrics_now", None)
        else:
            session.info["metrics_now"] = previous_now
    return {
        "snapshot_id": str(row.id),
        "payload": payload,
        "kb": {"package_version": bundle.package_version, "excerpts": [e.to_json() for e in bundle.excerpts]},
        "approx_tokens": approx_tokens,
    }
