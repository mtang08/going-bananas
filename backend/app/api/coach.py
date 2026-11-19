"""Inspectable coaching changesets and explicit, transactional decisions."""
from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.core import envelope
from app.coach_v2_models import CoachProposal, CoachProposalChange, CoachProposalRevision, CoachSnapshot
from app.db import get_session, global_write_lock
from app.errors import AppError, fail
from app.exception_models import ExceptionPatch
from app.read.calendar import head_version
from app.services import calendar, knowledge, proposals
from app.services.decision_inputs import VerifiedKnowledge
from app.services.proposals.schema import AnchorChange, DecisionError, SessionFields, anchor_key
from app.services.timezone import athlete_tz

router = APIRouter(prefix='/coach', tags=['coach'])


def resolve_kb(selection: tuple[dict, ...]) -> VerifiedKnowledge:
    return VerifiedKnowledge(**knowledge.verify_selection(selection))


def proposal_summary(proposal: CoachProposal) -> dict:
    return {**{key: getattr(proposal, key) for key in (
        'id', 'revision', 'operation', 'status', 'submitted_at', 'decided_at', 'discarded_at', 'summary', 'base_calendar_version')},
        'change_count': len(proposal.payload.get('changes', []))}


def proposal_detail(session: Session, proposal: CoachProposal) -> dict:
    # Serialize read freshness against source writers before reading head/fingerprint.
    global_write_lock(session)
    session.refresh(proposal)
    head = head_version(session, populate_existing=True)
    head_sessions = {row['session_uid']: row for row in calendar.state_at(session, head)}
    snapshot = session.get(CoachSnapshot, proposal.snapshot_id)
    is_current = False
    if snapshot and proposal.status == 'pending':
        try:
            ref = proposals._snapshot_ref(snapshot)
            context = proposals.load_context(session, proposal.snapshot_id, now=datetime.now(UTC),
                kb=resolve_kb(ref.kb_routes))
            is_current = not proposals.proposal_freshness(
                ref, context, base_calendar_version=proposal.base_calendar_version,
                base_block_version_id=proposal.base_block_version_id)
        except knowledge.KnowledgeIntegrityError:
            # Saved proposals stay readable when their research package changes.
            is_current = False
    data = {key: getattr(proposal, key) for key in (
        'id', 'revision', 'operation', 'snapshot_id', 'status', 'submitted_at', 'decided_at', 'discarded_at', 'summary', 'rationale',
        'confidence', 'evidence_ids', 'policy_ids', 'recipe_ids', 'follow_up', 'escalation',
        'base_calendar_version', 'base_block_version_id', 'block_change', 'validation_errors', 'skill_version')}
    data['decision_result'] = {'proposal_id': proposal.id, **proposal.decision_result} if proposal.decision_result else None
    data['revisions'] = [{key: getattr(row, key) for key in (
        'revision', 'saved_at', 'reason', 'changed_change_ids', 'changed_fields')}
        for row in session.scalars(select(CoachProposalRevision)
            .where(CoachProposalRevision.proposal_id == proposal.id).order_by(CoachProposalRevision.revision.desc()))]
    data['anchor_changes'] = [{**item, 'anchor_key': anchor_key(
        AnchorChange.model_validate(item), athlete_tz(session))} for item in cast(list[dict[str, Any]], proposal.anchor_changes or [])]
    stored = {item['change_id']: item for item in proposal.payload.get('changes', [])}
    changes = list(session.scalars(select(CoachProposalChange).where(CoachProposalChange.proposal_id == proposal.id)))
    changes.sort(key=lambda row: int(row.change_id[1:]))
    data.update(head=head, is_current=is_current, changes=[{
        **{key: getattr(row, key) for key in ('change_id', 'op', 'session_uid', 'before', 'after', 'reason', 'decision')},
        'material_flags': stored.get(row.change_id, {}).get('material_flags', []),
        'current': {key: value for key, value in head_sessions[row.session_uid].items()
                    if key in SessionFields.model_fields} if row.session_uid in head_sessions else None,
    } for row in changes])
    data['exception'] = proposal.payload.get('exception')
    data['event_review'] = proposal.payload.get('event_review')
    data['patch_resolutions'] = proposal.payload.get('patch_resolutions', [])
    patch = session.scalar(select(ExceptionPatch).where(ExceptionPatch.proposal_id == proposal.id))
    data['patch'] = {column.name: getattr(patch, column.name) for column in ExceptionPatch.__table__.columns} if patch else None
    return data


@router.get('/proposals')
def get_proposals(status: Literal['open', 'pending', 'accepted', 'partially_accepted', 'rejected', 'stale', 'invalid', 'discarded'] | None = None,
                  session: Session = Depends(get_session)) -> dict:
    query = select(CoachProposal).order_by(CoachProposal.submitted_at.desc(), CoachProposal.id.desc()).limit(50)
    if status == 'open':
        query = query.where(CoachProposal.status.in_(('pending', 'stale', 'invalid')))
    elif status:
        query = query.where(CoachProposal.status == status)
    else:
        query = query.where(CoachProposal.status != 'discarded')
    items = []
    for proposal in session.scalars(query):
        item = proposal_summary(proposal)
        item['change_count'] = len(proposal.payload.get('changes', []))
        items.append(item)
    return envelope(session, {'items': items})


@router.get('/proposals/active')
def get_active_proposal(session: Session = Depends(get_session)) -> dict:
    proposal = session.scalar(select(CoachProposal).where(
        CoachProposal.status.in_(('pending', 'stale', 'invalid')))
        .order_by(CoachProposal.submitted_at.desc(), CoachProposal.id.desc()))
    return envelope(session, {'proposal': proposal_summary(proposal) if proposal else None})


@router.delete('/proposals/{proposal_id}')
def delete_proposal(proposal_id: uuid.UUID, expected_revision: int = Query(..., gt=0),
                    session: Session = Depends(get_session)) -> dict:
    try:
        result = proposals.discard_proposal(session, proposal_id, expected_revision, now=datetime.now(UTC))
    except DecisionError as exc:
        session.rollback()
        raise AppError(exc.code, exc.message, exc.http_status, [issue.to_json() for issue in exc.fields]) from exc
    session.commit()
    return envelope(session, {'proposal_id': result.proposal_id, 'revision': result.revision, 'status': result.status})


@router.get('/proposals/{proposal_id}')
def get_proposal(proposal_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    proposal = session.get(CoachProposal, proposal_id)
    if proposal is None:
        fail('proposal_not_found', 'Proposal not found', 404)
    return envelope(session, proposal_detail(session, proposal))


@router.post('/proposals/{proposal_id}/decision')
def post_decision(proposal_id: uuid.UUID, body: proposals.DecisionRequest,
                  session: Session = Depends(get_session)) -> dict:
    try:
        result = proposals.decide_proposal(session, proposal_id, body, now=datetime.now(UTC), resolve_kb=resolve_kb)
    except DecisionError as exc:
        if exc.commit:
            session.commit()
        else:
            session.rollback()
        raise AppError(exc.code, exc.message, exc.http_status, [issue.to_json() for issue in exc.fields]) from exc
    except knowledge.KnowledgeIntegrityError as exc:
        session.rollback()
        raise AppError('knowledge_unavailable', 'Research package changed; create a fresh coaching review', 409) from exc
    session.commit()
    return envelope(session, asdict(result))


@router.get('/proposals/{proposal_id}/document')
def get_proposal_document(proposal_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    proposal = session.get(CoachProposal, proposal_id)
    if proposal is None:
        fail('proposal_not_found', 'Proposal not found', 404)
    detail = proposal_detail(session, proposal)
    return envelope(session, {'proposal_id': proposal.id, 'revision': proposal.revision,
        'status': proposal.status, 'is_current': detail['is_current'], 'document': proposal.payload})


@router.get('/proposals/{proposal_id}/revisions/{revision}')
def get_proposal_revision(proposal_id: uuid.UUID, revision: int, session: Session = Depends(get_session)) -> dict:
    row = session.get(CoachProposalRevision, (proposal_id, revision))
    if row is None:
        fail('proposal_revision_not_found', 'Proposal revision not found', 404)
    return envelope(session, {'proposal_id': proposal_id, 'revision': revision,
        'saved_at': row.saved_at, 'reason': row.reason, 'document': row.payload})


@router.post('/proposals/{proposal_id}/revise')
def post_revision(proposal_id: uuid.UUID, body: proposals.RevisionRequest,
                  session: Session = Depends(get_session)) -> dict:
    try:
        result = proposals.revise_proposal(session, proposal_id, body, now=datetime.now(UTC), resolve_kb=resolve_kb)
    except DecisionError as exc:
        session.rollback()
        raise AppError(exc.code, exc.message, exc.http_status, [issue.to_json() for issue in exc.fields]) from exc
    except knowledge.KnowledgeIntegrityError as exc:
        session.rollback()
        raise AppError('knowledge_unavailable', 'Research package changed; refresh the coaching context before revising', 409) from exc
    session.commit()
    return envelope(session, {'proposal_id': result.proposal_id, 'revision': result.revision,
        'status': result.status, 'errors': [issue.to_json() for issue in result.issues]})
