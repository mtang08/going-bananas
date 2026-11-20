"""Run the exception detector against the database and serialize its state."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.calendar_models import CalendarSessionRevision
from app.coach_v2_models import CoachProposal
from app.db import global_write_lock
from app.exception_models import ExceptionFinding, ExceptionPatch
from app.planning_models import Event
from app.services.exceptions.inputs import collect_detection_inputs
from app.services.exceptions.lifecycle import close_finding
from app.services.exceptions.rules import EVENT_REVIEW_DAYS, OBSERVE_EXPIRY_DAYS, detect
from app.services.exceptions.vocab import (
    NON_TERMINAL_FINDING,
    RULE_VERSION,
    SEVERITY,
    Severity,
    max_severity,
    severity_rank,
)
from app.services.timezone import athlete_today

PROMPTS = {
    "exception": "Use $going-bananas-coach for an exception review. Read the open findings in the app and patch only what they require.",
    "block": "Use $going-bananas-coach for a block review. An exception needs a bigger review.",
    "benchmark": "Use $going-bananas-coach for a block review. Review the block benchmark.",
    "race": "Use $going-bananas-coach for a post-race review of {event_name} on {event_date}.",
    "reassess": "Use $going-bananas-coach to reassess the open exception patch.",
}
REASON_EXCEPTION = "Open findings at caution or hold need an exception review"
REASON_BLOCK = "A finding needs a bigger review"
REASON_BLOCK_SYMPTOMS = "A symptom or illness finding needs a bigger review. Outside evaluation may be needed."
REASON_PATCH = "Patch reassessment due"
REASON_BENCHMARK = {
    "BLOCK_BENCHMARK_COMPLETED": "Block benchmark complete — review the block and recalibrate",
    "BLOCK_BENCHMARK_MISSED": "Block benchmark missed — review the block to reschedule it or extend the block",
}
RECENT_FINDING_DAYS = 28
RECENT_PATCH_DAYS = 14
REVIEW_OPERATIONS = ("review_rolling_plan", "review_training_block")
FINDING_FIELDS = (
    "id",
    "rule_code",
    "category",
    "severity",
    "status",
    "entity_key",
    "summary",
    "evidence",
    "evidence_at",
    "first_seen_at",
    "last_seen_at",
    "patch_id",
    "version",
)
PATCH_FIELDS = (
    "id",
    "proposal_id",
    "calendar_version_number",
    "category",
    "severity",
    "ladder_level",
    "window_start",
    "window_end",
    "reassess_on",
    "monitor",
    "return_criteria",
    "escalate_criteria",
    "unchanged",
    "status",
    "resolved_at",
    "resolved_by",
    "resolution_note",
    "created_at",
    "version",
)


@dataclass(frozen=True)
class Recommendation:
    operation: Literal["exception_review", "review_training_block", "post_event_review"]
    reason: str
    finding_ids: tuple[uuid.UUID, ...]
    prompt: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "reason": self.reason,
            "finding_ids": [str(i) for i in self.finding_ids],
            "prompt": self.prompt,
        }


@dataclass(frozen=True)
class DetectionResult:
    new_finding_ids: tuple[uuid.UUID, ...]
    review_recommended: tuple[Recommendation, ...]


def _event_for(session: Session, entity_key: str) -> Event | None:
    try:
        return session.get(Event, uuid.UUID(entity_key.removeprefix("event:")))
    except ValueError:
        return None


def review_recommended(session: Session, today: date) -> list[Recommendation]:
    findings = session.scalars(
        select(ExceptionFinding)
        .where(ExceptionFinding.status.in_(NON_TERMINAL_FINDING))
        .order_by(ExceptionFinding.first_seen_at, ExceptionFinding.id)
    ).all()
    open_rows = [f for f in findings if f.status == "open"]
    out: list[Recommendation] = []
    caution = tuple(f.id for f in open_rows if f.severity in ("caution", "hold"))
    if caution:
        out.append(Recommendation("exception_review", REASON_EXCEPTION, caution, PROMPTS["exception"]))
    escalate = [f for f in findings if f.severity == "escalate"]
    if escalate:
        reason = REASON_BLOCK_SYMPTOMS if any(f.category == "symptoms_illness" for f in escalate) else REASON_BLOCK
        out.append(Recommendation("review_training_block", reason, tuple(f.id for f in escalate), PROMPTS["block"]))
    for f in open_rows:
        event = _event_for(session, f.entity_key) if f.rule_code == "POST_EVENT_REVIEW_DUE" else None
        if event is not None:
            day = event.event_date.isoformat()
            out.append(
                Recommendation(
                    "post_event_review",
                    f"Race review due for {event.name} on {day}",
                    (f.id,),
                    PROMPTS["race"].format(event_name=event.name, event_date=day),
                )
            )
    for code, reason in REASON_BENCHMARK.items():
        ids = tuple(f.id for f in open_rows if f.rule_code == code)
        if ids:
            out.append(Recommendation("review_training_block", reason, ids, PROMPTS["benchmark"]))
    due = set(
        session.scalars(
            select(ExceptionPatch.id).where(ExceptionPatch.status == "open", ExceptionPatch.reassess_on <= today)
        ).all()
    )
    if due:
        out.append(
            Recommendation(
                "exception_review",
                REASON_PATCH,
                tuple(f.id for f in findings if f.patch_id in due),
                PROMPTS["reassess"],
            )
        )
    return out


def run_detection(session: Session, now: datetime) -> DetectionResult:
    global_write_lock(session)
    inputs = collect_detection_inputs(session, now)
    new_ids: list[uuid.UUID] = []
    for c in detect(inputs):
        same = (ExceptionFinding.rule_code == c.rule_code, ExceptionFinding.entity_key == c.entity_key)
        active = session.scalar(
            select(ExceptionFinding).where(*same, ExceptionFinding.status.in_(NON_TERMINAL_FINDING))
        )
        if active is not None:
            active.last_seen_at = now
            active.evidence = c.evidence
            active.summary = c.summary
            active.evidence_at = c.evidence_at
            active.severity = max_severity(cast(Severity, active.severity), c.severity)
            session.flush()
            continue
        terminal = session.scalar(
            select(ExceptionFinding)
            .where(*same, ExceptionFinding.status.not_in(NON_TERMINAL_FINDING))
            .order_by(desc(ExceptionFinding.closed_at).nulls_last(), desc(ExceptionFinding.id))
            .limit(1)
        )
        if terminal is not None and terminal.closed_at is not None and c.evidence_at <= terminal.closed_at:
            continue
        row = ExceptionFinding(
            rule_code=c.rule_code,
            rule_version=RULE_VERSION,
            category=c.category,
            severity=c.severity,
            entity_key=c.entity_key,
            status="open",
            summary=c.summary,
            evidence=c.evidence,
            evidence_at=c.evidence_at,
            first_seen_at=now,
            last_seen_at=now,
            version=1,
        )
        session.add(row)
        session.flush()
        new_ids.append(row.id)
    for row in session.scalars(select(ExceptionFinding).where(ExceptionFinding.status == "open")).all():
        stale = row.severity == "observe" and row.last_seen_at < now - timedelta(days=OBSERVE_EXPIRY_DAYS)
        if not stale and row.rule_code == "POST_EVENT_REVIEW_DUE":
            event = _event_for(session, row.entity_key)
            stale = event is None or inputs.today > event.event_date + timedelta(days=EVENT_REVIEW_DAYS)
        if stale:
            close_finding(row, "expired", now=now)
    session.flush()
    return DetectionResult(tuple(new_ids), tuple(review_recommended(session, inputs.today)))


def last_review_at(session: Session) -> datetime | None:
    return session.scalar(
        select(func.max(CoachProposal.decided_at)).where(
            CoachProposal.status.in_(("accepted", "partially_accepted")),
            CoachProposal.operation.in_(REVIEW_OPERATIONS),
            CoachProposal.decided_at.is_not(None),
        )
    )


def finding_data(row: ExceptionFinding, last_review: datetime | None) -> dict[str, Any]:
    return {
        **{key: getattr(row, key) for key in FINDING_FIELDS},
        "is_new_since_last_review": last_review is None or row.first_seen_at > last_review,
    }


def patch_data(session: Session, row: ExceptionPatch, today: date) -> dict[str, Any]:
    uids = sorted(
        {
            str(uid)
            for uid in session.scalars(
                select(CalendarSessionRevision.session_uid).where(
                    CalendarSessionRevision.calendar_version_number == row.calendar_version_number
                )
            )
        }
    )
    return {
        **{key: getattr(row, key) for key in PATCH_FIELDS},
        "session_uids": uids,
        "reassess_due": row.status == "open" and row.reassess_on <= today,
    }


def exceptions_view(session: Session, now: datetime, include: str) -> dict[str, Any]:
    today = athlete_today(session, now)
    last_review = last_review_at(session)
    wanted: ColumnElement[bool] = ExceptionFinding.status.in_(NON_TERMINAL_FINDING)
    if include == "recent":
        wanted = or_(wanted, ExceptionFinding.closed_at >= now - timedelta(days=RECENT_FINDING_DAYS))
    rows = session.scalars(
        select(ExceptionFinding).where(wanted).order_by(desc(ExceptionFinding.evidence_at), ExceptionFinding.id)
    ).all()
    rows = sorted(rows, key=lambda f: -severity_rank(cast(Severity, f.severity)))
    patches = session.scalars(
        select(ExceptionPatch)
        .where(
            or_(
                ExceptionPatch.status.in_(("open", "escalated")),
                and_(
                    ExceptionPatch.status == "resolved",
                    ExceptionPatch.resolved_at >= now - timedelta(days=RECENT_PATCH_DAYS),
                ),
            )
        )
        .order_by(desc(ExceptionPatch.created_at), ExceptionPatch.id)
    ).all()
    counts = {s: 0 for s in SEVERITY}
    for f in rows:
        if f.status == "open":
            counts[cast(Severity, f.severity)] += 1
    return {
        "rule_version": RULE_VERSION,
        "findings": [finding_data(f, last_review) for f in rows],
        "patches": [patch_data(session, p, today) for p in patches],
        "review_recommended": [r.to_wire() for r in review_recommended(session, today)],
        "counts": counts,
    }


def detection_payload(result: DetectionResult) -> dict[str, Any]:
    return {
        "new_finding_ids": [str(i) for i in result.new_finding_ids],
        "review_recommended": [r.to_wire() for r in result.review_recommended],
    }
