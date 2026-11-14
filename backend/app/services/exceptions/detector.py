"""Run the exception detector against the database and serialize its state."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from app.exception_models import ExceptionFinding
from app.planning_models import Event
from app.services.calendar import LOCK_ID
from app.services.exceptions.inputs import collect_detection_inputs
from app.services.exceptions.lifecycle import close_finding
from app.services.exceptions.rules import EVENT_REVIEW_DAYS, OBSERVE_EXPIRY_DAYS, detect
from app.services.exceptions.vocab import NON_TERMINAL_FINDING, RULE_VERSION, Severity, max_severity

PROMPTS = {'exception': 'Use $going-bananas-coach for an exception review. Read the open findings in the app and patch only what they require.',
           'block': 'Use $going-bananas-coach for a block review. An exception needs a bigger review.',
           'benchmark': 'Use $going-bananas-coach for a block review. Review the block benchmark.',
           'race': 'Use $going-bananas-coach for a post-race review of {event_name} on {event_date}.',
           'reassess': 'Use $going-bananas-coach to reassess the open exception patch.'}
REASON_EXCEPTION = 'Open findings at caution or hold need an exception review'
REASON_BLOCK = 'A finding needs a bigger review'
REASON_BLOCK_SYMPTOMS = 'A symptom or illness finding needs a bigger review. Outside evaluation may be needed.'
REASON_PATCH = 'Patch reassessment due'
REASON_BENCHMARK = {'BLOCK_BENCHMARK_COMPLETED': 'Block benchmark complete — review the block and recalibrate',
                    'BLOCK_BENCHMARK_MISSED': 'Block benchmark missed — review the block to reschedule it or extend the block',
                    'BLOCK_BENCHMARK_MISSING': 'Training block has no ending benchmark — set one in a block review'}
RECENT_FINDING_DAYS = 28
RECENT_PATCH_DAYS = 14
REVIEW_OPERATIONS = ('review_rolling_plan', 'review_training_block')
FINDING_FIELDS = ('id', 'rule_code', 'category', 'severity', 'status', 'entity_key', 'summary', 'evidence', 'evidence_at',
                  'first_seen_at', 'last_seen_at', 'patch_id', 'version')
PATCH_FIELDS = ('id', 'proposal_id', 'calendar_version_number', 'category', 'severity', 'ladder_level', 'window_start',
                'window_end', 'reassess_on', 'monitor', 'return_criteria', 'escalate_criteria', 'unchanged', 'status',
                'resolved_at', 'resolved_by', 'resolution_note', 'created_at', 'version')


@dataclass(frozen=True)
class Recommendation:
    operation: Literal['exception_review', 'review_training_block', 'post_event_review']
    reason: str
    finding_ids: tuple[uuid.UUID, ...]
    prompt: str

    def to_wire(self) -> dict[str, Any]:
        return {'operation': self.operation, 'reason': self.reason,
                'finding_ids': [str(i) for i in self.finding_ids], 'prompt': self.prompt}


@dataclass(frozen=True)
class DetectionResult:
    new_finding_ids: tuple[uuid.UUID, ...]
    review_recommended: tuple[Recommendation, ...]


def _lock(session: Session) -> None:
    session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': LOCK_ID})


def _event_for(session: Session, entity_key: str) -> Event | None:
    try:
        return session.get(Event, uuid.UUID(entity_key.removeprefix('event:')))
    except ValueError:
        return None


def review_recommended(session: Session, today: date) -> list[Recommendation]:
    return []


def run_detection(session: Session, now: datetime) -> DetectionResult:
    _lock(session)
    inputs = collect_detection_inputs(session, now)
    new_ids: list[uuid.UUID] = []
    for c in detect(inputs):
        same = (ExceptionFinding.rule_code == c.rule_code, ExceptionFinding.entity_key == c.entity_key)
        active = session.scalar(select(ExceptionFinding).where(*same, ExceptionFinding.status.in_(NON_TERMINAL_FINDING)))
        if active is not None:
            active.last_seen_at = now
            active.evidence = c.evidence
            active.summary = c.summary
            active.evidence_at = c.evidence_at
            active.severity = max_severity(cast(Severity, active.severity), c.severity)
            session.flush()
            continue
        terminal = session.scalar(select(ExceptionFinding).where(*same, ExceptionFinding.status.not_in(NON_TERMINAL_FINDING))
                                  .order_by(desc(ExceptionFinding.closed_at).nulls_last(), desc(ExceptionFinding.id)).limit(1))
        if terminal is not None and terminal.closed_at is not None and c.evidence_at <= terminal.closed_at:
            continue
        row = ExceptionFinding(rule_code=c.rule_code, rule_version=RULE_VERSION, category=c.category, severity=c.severity,
                               entity_key=c.entity_key, status='open', summary=c.summary, evidence=c.evidence,
                               evidence_at=c.evidence_at, first_seen_at=now, last_seen_at=now, version=1)
        session.add(row)
        session.flush()
        new_ids.append(row.id)
    for row in session.scalars(select(ExceptionFinding).where(ExceptionFinding.status == 'open')).all():
        stale = row.severity == 'observe' and row.last_seen_at < now - timedelta(days=OBSERVE_EXPIRY_DAYS)
        if not stale and row.rule_code == 'POST_EVENT_REVIEW_DUE':
            event = _event_for(session, row.entity_key)
            stale = event is None or inputs.today > event.event_date + timedelta(days=EVENT_REVIEW_DAYS)
        if stale:
            close_finding(row, 'expired', now=now)
    session.flush()
    return DetectionResult(tuple(new_ids), tuple(review_recommended(session, inputs.today)))
