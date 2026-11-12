from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Literal, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.core import envelope, get_context, tz
from app.coaching_models import CoachOutcome, CoachOutcomeEvent, CoachRecommendation
from app.db import bump_data_revision, get_session
from app.services.coaching import ENGINE, daily, fingerprint, weekly
from app.services.knowledge import KnowledgeContext, KnowledgeIntegrityError

router = APIRouter(prefix="/coach", tags=["coaching"])


class DailyRequest(BaseModel):
    as_of: date | None = None
    illness: Literal["unknown", "none", "mild", "systemic"] = "unknown"
    lower_body_soreness: Literal["unknown", "none", "usual", "affects_movement"] = "unknown"
    clinician_restriction: Literal["unknown", "none", "restricted"] = "unknown"


class WeeklyRequest(BaseModel):
    as_of: date | None = None


class OutcomeRequest(BaseModel):
    status: Literal["accepted", "rejected", "completed", "partly_completed", "skipped"]
    effect: Literal["helpful", "neutral", "worse", "unknown"] | None = None
    note: str | None = Field(default=None, max_length=2000)


def _day(session: Session, as_of: date | None) -> tuple[date, date]:
    today = datetime.now(ZoneInfo(tz(session))).date()
    day = as_of or today
    if day > today + timedelta(days=1) or day < today - timedelta(days=365):
        raise HTTPException(
            422, detail={"code": "invalid_as_of", "message": "Coaching dates must be within the last year or tomorrow."}
        )
    return day, today


def _knowledge(workflow: Literal["daily", "weekly"], ids: Iterable[str] = ()) -> KnowledgeContext:
    from app.services.knowledge import load_knowledge

    topics = (
        ("ptt_and_load_tolerance", "recovery_and_daily_adaptation", "hybrid_strength_and_scheduling")
        if workflow == "daily"
        else ("aerobic_progression", "hybrid_strength_and_scheduling")
    )
    try:
        return load_knowledge(workflow, topics=topics, policy_ids=ids)
    except KnowledgeIntegrityError as exc:
        raise HTTPException(
            503, detail={"code": "knowledge_unavailable", "message": "Local research snapshot is missing or corrupt."}
        ) from exc


def _knowledge_info(knowledge) -> dict:
    if knowledge is None:
        return {"available": False, "version": None, "searched_through": None}
    return {
        "available": bool(knowledge.integrity_ok),
        "version": knowledge.package_version,
        "searched_through": knowledge.searched_through,
    }


def _state(
    session: Session, day: date, today: date, workflow: Literal["daily", "weekly"], supplement: dict | None = None
) -> tuple[dict, dict, KnowledgeContext, str]:
    # A preview uses observations through today, never observations dated tomorrow.
    context = get_context(as_of=min(day, today), session=session)["data"]
    now = datetime.now(UTC)
    zone = ZoneInfo(tz(session))
    context["recent_checkins"] = [
        r
        for r in context["recent_checkins"]
        if (
            r["observed_at"]
            if isinstance(r["observed_at"], datetime)
            else datetime.fromisoformat(str(r["observed_at"]))
        ).astimezone(UTC)
        <= now
        and (
            r["observed_at"]
            if isinstance(r["observed_at"], datetime)
            else datetime.fromisoformat(str(r["observed_at"]))
        )
        .astimezone(zone)
        .date()
        <= min(day, today)
    ]
    context["recent_activities"] = [
        a for a in context["recent_activities"] if str(a["local_date"])[:10] <= min(day, today).isoformat()
    ]
    if workflow == "weekly":
        outcomes = session.execute(
            select(CoachRecommendation, CoachOutcomeEvent)
            .join(CoachOutcomeEvent, CoachOutcomeEvent.recommendation_id == CoachRecommendation.id)
            .where(CoachRecommendation.as_of >= day - timedelta(days=13), CoachRecommendation.as_of <= day)
            .where((CoachRecommendation.kind == "daily") | (CoachRecommendation.as_of < day))
            .order_by(desc(CoachOutcomeEvent.recorded_at))
            .limit(40)
        ).all()
        context["prior_coaching_outcomes"] = [
            {
                "as_of": recommendation.as_of,
                "kind": recommendation.kind,
                "decision": recommendation.payload.get("decision"),
                "status": outcome.status,
                "effect": outcome.effect,
            }
            for recommendation, outcome in outcomes
        ]
    supplement = supplement or {}
    payload = daily(context, day, supplement, today=today) if workflow == "daily" else weekly(context, day)
    kb = _knowledge(workflow, payload["references"]["policy_ids"])
    if not kb.integrity_ok:
        raise HTTPException(
            503, detail={"code": "knowledge_integrity", "message": "Research package integrity check failed."}
        )
    policy_map = {p["policy_id"]: p for p in kb.policies}
    payload["references"]["evidence_ids"] = sorted(
        {e for p in payload["references"]["policy_ids"] for e in policy_map[p].get("evidence_ids", [])}
    )
    source_ids = sorted({s for p in kb.policies for s in p.get("source_ids", [])})[:12]
    from app.services.knowledge import load_knowledge

    try:
        kb = load_knowledge(
            workflow,
            topics=("ptt_and_load_tolerance", "recovery_and_daily_adaptation", "hybrid_strength_and_scheduling")
            if workflow == "daily"
            else ("aerobic_progression", "hybrid_strength_and_scheduling"),
            policy_ids=payload["references"]["policy_ids"],
            source_ids=source_ids,
        )
    except KnowledgeIntegrityError as exc:
        raise HTTPException(
            503, detail={"code": "knowledge_unavailable", "message": "Local research snapshot is missing or corrupt."}
        ) from exc
    payload["references"]["source_ids"] = source_ids
    payload["references"]["sources"] = [
        {"id": s["source_id"], "title": s.get("title"), "url": s.get("url") or s.get("doi_url")}
        for s in kb.sources
        if s.get("source_id") in source_ids
    ]
    payload["audit"]["files_sections_loaded"] = kb.selected_files
    stable_context = {k: v for k, v in context.items() if k not in {"generated_at", "data_revision"}}
    input_record = {
        "context": stable_context,
        "supplemental": supplement,
        "as_of": day,
        "knowledge_version": kb.package_version,
        "knowledge_digest": fingerprint(kb.text),
        "engine": ENGINE,
    }
    return context, payload, kb, fingerprint(input_record)


def _latest(session: Session, kind: str, day: date) -> CoachRecommendation | None:
    return session.scalar(
        select(CoachRecommendation)
        .where(CoachRecommendation.kind == kind, CoachRecommendation.as_of == day)
        .order_by(desc(CoachRecommendation.selected_at), desc(CoachRecommendation.generated_at), desc(CoachRecommendation.id))
        .limit(1)
    )


def _format(session: Session, row: CoachRecommendation | None, current_hash: str | None = None, knowledge=None) -> dict:
    if row is None:
        return {"item": None, "knowledge": _knowledge_info(knowledge)}
    outcome = session.scalar(select(CoachOutcome).where(CoachOutcome.recommendation_id == row.id))
    stale_reasons = []
    if current_hash is not None and row.input_hash != current_hash:
        stale_reasons.append("Inputs, plan, profile, or knowledge changed since generation.")
    if row.as_of < datetime.now(ZoneInfo(tz(session))).date():
        stale_reasons.append("Recommendation date has passed.")
    return {
        "item": {
            "id": row.id,
            "kind": row.kind,
            "as_of": row.as_of,
            "generated_at": row.generated_at,
            "stale": bool(stale_reasons),
            "stale_reasons": stale_reasons,
            "engine": row.engine,
            "knowledge_version": row.knowledge_version,
            "payload": row.payload,
            "supplemental_inputs": row.inputs.get("supplemental") or {},
            "outcome": {
                "status": outcome.status,
                "effect": outcome.effect,
                "note": outcome.note,
                "recorded_at": outcome.recorded_at,
            }
            if outcome
            else None,
        },
        "knowledge": _knowledge_info(knowledge),
    }


def _get(session: Session, workflow: Literal["daily", "weekly"], as_of: date | None) -> dict:
    day, today = _day(session, as_of)
    row = _latest(session, workflow, day)
    if row is None:
        try:
            kb = _knowledge(workflow)
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
            return envelope(session, {"item": None, "knowledge": {"available": False, "version": None, "searched_through": None}})
        return envelope(session, _format(session, None, knowledge=kb))
    # Recompute from the stored supplemental inputs; later calls never assume absent fields became normal.
    supplement = row.inputs.get("supplemental") or {}
    try:
        _, _, kb, hash_now = _state(session, day, today, workflow, supplement)
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        data = _format(session, row)
        data["knowledge"] = {"available": False, "version": None, "searched_through": None}
        data["item"]["stale"] = True
        data["item"]["stale_reasons"].append("Local research snapshot is unavailable or corrupt.")
        return envelope(session, data)
    return envelope(session, _format(session, row, hash_now, kb))


def _post(session: Session, workflow: Literal["daily", "weekly"], as_of: date | None, supplement: dict | None) -> dict:
    from app.services.legacy_cutover import require_legacy_write
    require_legacy_write(session)
    day, today = _day(session, as_of)
    context, payload, kb, input_hash = _state(session, day, today, workflow, supplement)
    row = session.scalar(
        select(CoachRecommendation).where(
            CoachRecommendation.kind == workflow,
            CoachRecommendation.as_of == day,
            CoachRecommendation.input_hash == input_hash,
        )
    )
    if row is None:
        row = CoachRecommendation(
            kind=workflow,
            as_of=day,
            engine=ENGINE,
            knowledge_version=kb.package_version,
            data_revision=context["data_revision"],
            profile_version=context["profile_version"],
            plan_version=context["plan_version"],
            input_hash=input_hash,
            inputs={
                "supplemental": supplement or {},
                "data_revision": context["data_revision"],
                "profile_version": context["profile_version"],
                "plan_version": context["plan_version"],
                "knowledge_digest": fingerprint(kb.text),
                "context_snapshot": jsonable_encoder({k: v for k, v in context.items() if k != "generated_at"}),
            },
            payload=jsonable_encoder(payload),
        )
        session.add(row)
        session.commit()
    else:
        row.selected_at = datetime.now(UTC)
        session.commit()
    return envelope(session, _format(session, row, input_hash, kb))


@router.get("/daily")
def get_daily(as_of: date | None = None, session: Session = Depends(get_session)) -> dict:
    return _get(session, "daily", as_of)


@router.post("/daily")
def post_daily(body: DailyRequest, session: Session = Depends(get_session)) -> dict:
    return _post(session, "daily", body.as_of, body.model_dump(exclude={"as_of"}))


@router.get("/weekly")
def get_weekly(as_of: date | None = None, session: Session = Depends(get_session)) -> dict:
    return _get(session, "weekly", as_of)


@router.post("/weekly")
def post_weekly(body: WeeklyRequest, session: Session = Depends(get_session)) -> dict:
    return _post(session, "weekly", body.as_of, None)


@router.post("/recommendations/{recommendation_id}/outcome")
def post_outcome(recommendation_id: uuid.UUID, body: OutcomeRequest, session: Session = Depends(get_session)) -> dict:
    from app.services.legacy_cutover import require_legacy_write
    require_legacy_write(session)
    row = session.get(CoachRecommendation, recommendation_id)
    if row is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Recommendation not found."})
    today = datetime.now(ZoneInfo(tz(session))).date()
    if body.status in {"accepted", "rejected"}:
        if row.as_of != today:
            raise HTTPException(
                409,
                detail={
                    "code": "stale_recommendation",
                    "message": "Only a current-day recommendation can be accepted or rejected.",
                },
            )
        _, _, _, current_hash = _state(session, row.as_of, today, cast(Literal["daily", "weekly"], row.kind), row.inputs.get("supplemental"))
        if row.input_hash != current_hash:
            raise HTTPException(
                409,
                detail={
                    "code": "stale_recommendation",
                    "message": "Regenerate this recommendation after the latest data change.",
                },
            )
    if body.status in {"completed", "partly_completed", "skipped"} and row.as_of > today:
        raise HTTPException(
            409, detail={"code": "future_outcome", "message": "Completion cannot be recorded for a future session."}
        )
    outcome = session.scalar(select(CoachOutcome).where(CoachOutcome.recommendation_id == recommendation_id))
    if outcome is None:
        outcome = CoachOutcome(recommendation_id=recommendation_id)
        session.add(outcome)
    outcome.status, outcome.effect, outcome.note = body.status, body.effect, body.note
    outcome.recorded_at = datetime.now(UTC)
    session.add(
        CoachOutcomeEvent(
            recommendation_id=recommendation_id,
            status=body.status,
            effect=body.effect,
            note=body.note,
            recorded_at=outcome.recorded_at,
        )
    )
    bump_data_revision(session)
    session.commit()
    return envelope(
        session,
        {
            "recommendation_id": recommendation_id,
            "status": outcome.status,
            "effect": outcome.effect,
            "note": outcome.note,
            "recorded_at": outcome.recorded_at,
            "plan_changed": False,
        },
    )


@router.get("/context")
def get_coach_context(
    workflow: Literal["daily", "weekly"] = "daily", as_of: date | None = None, session: Session = Depends(get_session)
) -> dict:
    day, today = _day(session, as_of)
    context, payload, kb, _ = _state(session, day, today, workflow)
    return envelope(
        session,
        {
            "workflow": workflow,
            "as_of": day,
            "context": context,
            "knowledge": _knowledge_info(kb),
            "selected_files": kb.selected_files,
            "policy_ids": payload["references"]["policy_ids"],
            "prose": kb.text,
        },
    )
