"""The model's only route to coaching evidence and pending proposal writes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.api.coach import active_proposal, proposal_detail, resolve_kb
from app.api.metrics import activity_execution, explain_metric, long_run_history, recovery_nights
from app.api.responses import proposal_summary
from app.db import global_write_lock
from app.errors import AppError
from app.services.calendar import calendar_diff
from app.services.coach_chat_store import ChatReview, ChatStore
from app.services.exceptions.detector import exceptions_view, run_detection
from app.services.knowledge import KnowledgeIntegrityError
from app.services.operations import Operation
from app.services.proposals.lifecycle import RevisionRequest, revise_proposal, submit_proposal
from app.services.proposals.schema import DecisionError, ProposalDoc
from app.services.snapshot.build import build_snapshot
from app.services.snapshot.common import EXCEPTION, strip_private
from app.services.timezone import athlete_today


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FindingsInput(ToolInput):
    include: Literal["active", "recent"] = "active"


class SnapshotInput(ToolInput):
    operation: Operation


class ActivityQuery(ToolInput):
    name: Literal["activity_execution"]
    activity_id: UUID


class HistoryQuery(ToolInput):
    name: Literal["long_run_history", "recovery_nights"]
    start: date
    end: date


class CalendarQuery(ToolInput):
    name: Literal["calendar_diff"]
    from_version: int = Field(ge=0)
    to_version: int = Field(ge=0)


class MetricQuery(ToolInput):
    name: Literal["explain_metric"]
    result_id: UUID


class QueryInput(ToolInput):
    name: Literal["activity_execution", "long_run_history", "recovery_nights", "calendar_diff", "explain_metric"]
    activity_id: UUID | None = None
    start: date | None = None
    end: date | None = None
    from_version: int | None = Field(default=None, ge=0)
    to_version: int | None = Field(default=None, ge=0)
    result_id: UUID | None = None


class SaveInput(ToolInput):
    document: dict[str, Any]
    proposal_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def revision_identity(self) -> SaveInput:
        present = [self.proposal_id is not None, self.expected_revision is not None, self.reason is not None]
        if any(present) and not all(present):
            raise ValueError("A revision requires proposal_id, expected_revision and reason")
        return self


_TOOLS: dict[str, tuple[str, type[ToolInput]]] = {
    "active_proposal": ("Read the open draft, current revision and reusable proposal document.", ToolInput),
    "review_findings": (
        "Read deterministic coaching findings, tracked patches and review recommendations.",
        FindingsInput,
    ),
    "coaching_snapshot": ("Get a current, filtered coaching snapshot with verified research excerpts.", SnapshotInput),
    "coaching_query": ("Inspect a drill-down from the snapshot. Supply the fields for that query.", QueryInput),
    "proposal_schema": ("Get the current calendar-authority proposal schema and limits.", ToolInput),
    "save_pending_proposal": (
        "Save the agreed plan for review. Supply proposal_id, expected_revision and reason to revise an open draft.",
        SaveInput,
    ),
}
TOOL_DEFINITIONS = [
    {"name": name, "description": description, "inputSchema": shape.model_json_schema()}
    for name, (description, shape) in _TOOLS.items()
]


def _tool_error(code: str, message: str, fields: list[dict] | None = None) -> dict:
    return {"error": code, "message": message, "errors": fields or []}


def _query(session: Session, args: QueryInput) -> dict:
    raw = args.model_dump(exclude_none=True)
    result: dict | list[dict]
    if args.name == "activity_execution":
        fields = ActivityQuery.model_validate(raw)
        result = activity_execution(session, fields.activity_id)
    elif args.name in ("long_run_history", "recovery_nights"):
        history = HistoryQuery.model_validate(raw)
        if not 0 <= (history.end - history.start).days < 92:
            return _tool_error("invalid_date_window", "Choose a date window of at most 92 days.")
        result = (
            long_run_history(session, history.start, history.end)
            if history.name == "long_run_history"
            else recovery_nights(session, history.start, history.end)
        )
    elif args.name == "calendar_diff":
        versions = CalendarQuery.model_validate(raw)
        result = calendar_diff(session, versions.from_version, versions.to_version)
    else:
        metric = MetricQuery.model_validate(raw)
        result = explain_metric(session, metric.result_id)
    return {"query": args.name, "data": strip_private(result)}


def _read_active(session: Session, review: ChatReview) -> dict:
    global_write_lock(session)
    draft = active_proposal(session)
    review.read_active_proposal = True
    review.observed_proposal = draft.id if draft else None
    if draft is None:
        return {"proposal": None}
    detail = proposal_detail(session, draft)
    review.snapshot_ids.add(draft.snapshot_id)
    review.proposal_id = draft.id
    return {
        "proposal": proposal_summary(draft),
        "proposal_id": draft.id,
        "revision": draft.revision,
        "status": draft.status,
        "is_current": detail["is_current"],
        "document": draft.payload,
    }


def _snapshot(session: Session, args: SnapshotInput, review: ChatReview, now: datetime) -> dict:
    result = build_snapshot(session, args.operation, athlete_today(session, now), now=now)
    session.commit()
    review.snapshot_ids.add(UUID(result["snapshot_id"]))
    return result


def _save(session: Session, args: SaveInput, review: ChatReview, now: datetime) -> dict:
    if not review.read_active_proposal:
        return _tool_error("active_proposal_required", "Read the current draft before saving a proposal.")
    try:
        snapshot_id = UUID(str(args.document.get("snapshot_id")))
    except (ValueError, TypeError):
        return _tool_error("snapshot_required", "Use the snapshot ID returned in this review.")
    if snapshot_id not in review.snapshot_ids:
        return _tool_error("snapshot_required", "Use the snapshot ID returned in this review.")
    global_write_lock(session)
    draft = active_proposal(session)
    if draft is None and (args.proposal_id or review.observed_proposal):
        return _tool_error("proposal_decided", "The open draft was decided. Do not recreate it as a retry.")
    if draft and (args.proposal_id != draft.id or review.observed_proposal != draft.id):
        return _tool_error("active_proposal_exists", "Read the current draft and revise its stable ID.")
    if draft and args.document.get("operation") == EXCEPTION and draft.operation != EXCEPTION:
        return _tool_error("active_proposal_exists", "The athlete must decide on their open draft first.")
    if args.proposal_id is None:
        result = submit_proposal(session, args.document, now=now, resolve_kb=resolve_kb)
    else:
        revision = RevisionRequest.model_validate(args.model_dump(exclude={"proposal_id"}))
        result = revise_proposal(session, args.proposal_id, revision, now=now, resolve_kb=resolve_kb)
    if result.status != "pending":
        return _tool_error(
            "stale_evidence" if result.status == "stale" else "invalid_proposal",
            "The draft did not pass current validation.",
            [issue.to_json() for issue in result.issues],
        )
    session.commit()
    review.proposal_id = result.proposal_id
    review.observed_proposal = result.proposal_id
    return {
        "proposal_id": result.proposal_id,
        "revision": result.revision,
        "status": result.status,
        "review_path": f"/#proposal/{result.proposal_id}",
    }


def _dispatch(session: Session, review: ChatReview, args: ToolInput, name: str, now: datetime) -> dict:
    if name == "active_proposal":
        return _read_active(session, review)
    if isinstance(args, FindingsInput):
        run_detection(session, now)
        result = strip_private(exceptions_view(session, now, args.include))
        session.commit()
        return result
    if isinstance(args, SnapshotInput):
        return _snapshot(session, args, review, now)
    if isinstance(args, QueryInput):
        return _query(session, args)
    if name == "proposal_schema":
        return {
            "protocol": "coach_proposal.v2",
            "activation": "manual",
            "required_authority": "calendar",
            "proposal": ProposalDoc.model_json_schema(),
        }
    assert isinstance(args, SaveInput)
    return _save(session, args, review, now)


def call_coach_tool(
    store: ChatStore,
    session_factory: Callable[[], Session],
    turn_id: UUID,
    name: str,
    arguments: dict,
    *,
    now: datetime,
) -> dict:
    if name not in _TOOLS:
        return _tool_error("unknown_tool", "This app only exposes its listed coaching tools.")
    try:
        args = _TOOLS[name][1].model_validate(arguments)
        # Cancel and save are ordered by the same local lock. The proposal transaction itself
        # still validates and locks the live planning inputs like every other writer.
        with store.transaction() as state, session_factory() as session:
            review = state.review
            if review.active_turn != turn_id or review.status != "running":
                return _tool_error("interrupted", "This coaching turn has stopped.")
            return jsonable_encoder(_dispatch(session, review, args, name, now))
    except ValidationError as exc:
        return _tool_error(
            "invalid_tool_arguments",
            "Check the coaching tool's arguments.",
            [{"path": ".".join(map(str, item["loc"])), "message": item["msg"]} for item in exc.errors()],
        )
    except DecisionError as exc:
        return _tool_error(exc.code, exc.message, [issue.to_json() for issue in exc.fields])
    except AppError as exc:
        return _tool_error(exc.code, exc.message, exc.fields)
    except KnowledgeIntegrityError:
        return _tool_error("knowledge_unavailable", "Verified research is unavailable in this workspace.")
