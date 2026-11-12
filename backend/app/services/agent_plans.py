"""Validate and persist Codex-authored prescriptions. No model is run here.

The safety bounds below are rejection guards, not a training algorithm. Immutable
revision snapshots and membership retain old session ownership and completion IDs.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from statistics import mean
from typing import Any, Literal, NoReturn
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.orm import Session

from app.agent_models import CoachPlanRevision
from app.api.core import current_profile, get_context, get_recovery, plan_data, tz, weekly_data
from app.domain.cycle import opportunities, recurring_sessions
from app.models import Activity, CompletionLink, PlannedSession, PlanVersion
from app.services.coaching import fingerprint
from app.services.knowledge import KnowledgeIntegrityError, load_knowledge

ENGINE = 'codex_skill.v1'
RUN_SPORTS = {'running', 'trail_running', 'treadmill_running'}


class Prescription(BaseModel):
    model_config = ConfigDict(extra='forbid')
    intent: Literal['easy', 'quality', 'long', 'rest']
    purpose: str = Field(min_length=3, max_length=1000)
    prescription: str = Field(min_length=5, max_length=5000)
    intensity: str = Field(min_length=3, max_length=1000)
    reason: str = Field(min_length=5, max_length=2000)
    duration_minutes: float | None = Field(default=None, ge=5, le=180, allow_inf_nan=False)
    distance_km: float | None = Field(default=None, ge=.5, le=35, allow_inf_nan=False)
    steps: list[str] = Field(default_factory=list, max_length=30)
    locked: bool = False


class SessionProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    date: date
    kind: Literal['run'] = 'run'
    target: Prescription


class Review(BaseModel):
    actual_vs_plan: str = Field(min_length=5, max_length=5000)
    progression: str = Field(min_length=5, max_length=5000)
    recovery: str = Field(min_length=5, max_length=5000)
    symptoms: str = Field(min_length=5, max_length=5000)
    strength: str = Field(min_length=5, max_length=5000)
    weekly_strategy: str = Field(min_length=5, max_length=5000)
    uncertainty: list[str] = Field(default_factory=list, max_length=30)
    follow_up: list[str] = Field(default_factory=list, max_length=30)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=40)

    @field_validator('evidence')
    @classmethod
    def validate_reference_lists(cls, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for claim in evidence:
            for field in ('activity_ids', 'checkin_ids', 'source_ids'):
                if field in claim and (not isinstance(claim[field], list)
                        or any(not isinstance(value, str) for value in claim[field])):
                    raise ValueError(f'{field} must be an array of string references.')
        return evidence


class Proposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    workflow: Literal['weekly', 'daily']
    as_of: date
    evidence_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    expected_revision_id: uuid.UUID | None = None
    idempotency_key: str = Field(min_length=8, max_length=100)
    summary: str = Field(min_length=5, max_length=2000)
    rationale: str = Field(min_length=5, max_length=5000)
    source_ids: list[str] = Field(min_length=1, max_length=12)
    review: Review
    sessions: list[SessionProposal] = Field(max_length=7)


def fail(code: str, message: str, status: int = 422) -> NoReturn:
    raise HTTPException(status, detail={'code': code, 'message': message})


def latest(session: Session) -> CoachPlanRevision | None:
    return session.scalar(select(CoachPlanRevision).order_by(desc(CoachPlanRevision.created_at), desc(CoachPlanRevision.id)).limit(1))


def format_revision(row: CoachPlanRevision) -> dict:
    return {'id': row.id, 'parent_revision_id': row.parent_revision_id, 'plan_id': row.plan_id,
            'workflow': row.workflow, 'as_of': row.as_of, 'created_at': row.created_at,
            'summary': row.summary, 'rationale': row.rationale, 'engine': ENGINE,
            'status': 'applied', 'evidence_hash': row.evidence_hash,
            **{k: row.payload.get(k) for k in ('diff', 'review', 'source_ids', 'rollback_of_id', 'warnings')}}


def is_active_session(session: Session, session_id: uuid.UUID) -> bool:
    row = latest(session)
    return bool(row and str(session_id) in row.payload.get('active_session_ids', []))


def _knowledge(workflow: Literal['daily', 'weekly'], source_ids: list[str] | None = None):
    try:
        return load_knowledge(workflow, topics=('aerobic_progression', 'recovery_and_daily_adaptation',
                              'ptt_and_load_tolerance', 'hybrid_strength_and_scheduling'),
                              source_ids=source_ids or ['S001', 'S002'])
    except (ValueError, KnowledgeIntegrityError) as exc:
        fail('knowledge_unavailable', str(exc), 503)


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in {'generated_at', 'data_revision'}}
    if isinstance(value, list):
        return [_stable(x) for x in value]
    return value


def agent_context(session: Session, workflow: Literal['daily', 'weekly'], day: date) -> dict:
    today = datetime.now(ZoneInfo(tz(session))).date()
    if day > today or day < today - timedelta(days=365):
        fail('invalid_as_of', 'Context date must be today or within the preceding year.')
    context = get_context(as_of=day, include_notes=True, session=session)['data']
    # Exclude future timestamps even when they share today's local date.
    now = datetime.now(UTC)
    context['recent_checkins'] = [c for c in context['recent_checkins'] if c['observed_at'] <= now]
    context['recent_activities'] = [a for a in context['recent_activities'] if not a.get('start_at') or a['start_at'] <= now]
    previous_monday = day - timedelta(days=day.weekday() + 7)
    context['previous_completed_week'] = weekly_data(session, previous_monday)
    recovery = get_recovery(start_date=day-timedelta(days=41), end_date=day, session=session)['data']
    baselines = {}
    for metric, points in recovery.get('series', {}).items():
        valid = [p for p in points if p.get('value') is not None]
        baseline = [p['value'] for p in valid if str(p['date'])[:10] < (day-timedelta(days=6)).isoformat()]
        recent = [p['value'] for p in valid if str(p['date'])[:10] >= (day-timedelta(days=6)).isoformat()]
        baselines[metric] = {'baseline_mean': round(mean(baseline), 2) if baseline else None,
                             'baseline_count': len(baseline), 'recent_7_mean': round(mean(recent), 2) if recent else None,
                             'recent_7_count': len(recent), 'unit': valid[-1].get('unit') if valid else None}
    context['recovery_baselines'] = {'window_days': 42, 'baseline_excludes_recent_7': True, 'metrics': baselines}
    runs = [a for a in context['recent_activities'] if a.get('sport') in RUN_SPORTS]
    context['run_response_summary'] = {'runs_with_hr': sum(a.get('avg_hr_bpm') is not None for a in runs),
                                      'run_count': len(runs),
                                      'interpretation_limit': 'Summary HR/pace only; route, weather, effort and sensor differences are uncontrolled. No zones, laps or drift inferred.'}
    rows = session.scalars(select(CoachPlanRevision).where(CoachPlanRevision.as_of <= day)
                           .order_by(desc(CoachPlanRevision.created_at)).limit(15)).all()
    context['prior_agent_reviews'] = [format_revision(r) for r in rows]
    context['active_weekly_strategy'] = next((r.payload.get('review', {}).get('weekly_strategy') for r in rows if r.workflow == 'weekly'), None)
    context['structured_profile_authority'] = 'Confirmed structured profile fields supersede conflicting dated free-text facts; preserve uncertainty in old notes.'
    context['prescription_window'] = {'start': day, 'end': day+timedelta(days=13)}
    profile = current_profile(session)
    context['run_opportunities'] = opportunities(day, day+timedelta(days=13), profile.cycle_anchor if profile and profile.anchor_confirmed else None)
    # External observations define evidence. Our own plan writes and review history
    # do not create fresh evidence or trigger another model decision on page views.
    excluded = {'generated_at', 'data_revision', 'plan_version', 'next_14_days_plan', 'recent_14_days_plan',
                'recurring_sessions', 'prior_agent_reviews', 'active_weekly_strategy', 'previous_completed_week'}
    evidence = {k: v for k, v in context.items() if k not in excluded}
    evidence['previous_completed_week_actuals'] = context['previous_completed_week']['summary']
    evidence['confirmed_completions'] = [
        {'id': link.id, 'planned_session_id': link.planned_session_id, 'activity_id': link.activity_id,
         'manual_session_id': link.manual_session_id}
        for link in session.scalars(select(CompletionLink).join(PlannedSession,
            PlannedSession.id == CompletionLink.planned_session_id).where(
            PlannedSession.date >= day-timedelta(days=13), PlannedSession.date <= day)
            .order_by(CompletionLink.id)).all()]
    agent_plan_ids = select(CoachPlanRevision.plan_id).where(CoachPlanRevision.plan_id.is_not(None))
    manual_plans = session.scalars(select(PlanVersion).where(PlanVersion.id.not_in(agent_plan_ids),
                                  PlanVersion.status.in_(['accepted', 'superseded'])).order_by(PlanVersion.id)).all()
    evidence['manual_plans'] = [{'id': p.id, 'sessions': [
        {'id': x['id'], 'date': x['date'], 'kind': x['kind'], 'target': x['target']}
        for x in plan_data(session, p)['sessions']]} for p in manual_plans]
    # Another workflow's plan change (or a rollback) changes the decision
    # starting point. Ignore this workflow's own output so an immediate repeat
    # remains idempotent without hiding later calendar changes from the coach.
    plan_epoch = session.scalar(select(CoachPlanRevision).where(
        CoachPlanRevision.workflow != workflow,
        or_(CoachPlanRevision.workflow == 'rollback',
            func.jsonb_array_length(CoachPlanRevision.payload['diff']) > 0),
    ).order_by(desc(CoachPlanRevision.created_at), desc(CoachPlanRevision.id)).limit(1))
    evidence['plan_decision_epoch'] = str(plan_epoch.id) if plan_epoch else None
    kb = _knowledge(workflow)
    current = latest(session)
    return {'workflow': workflow, 'as_of': day, 'context': context,
            'current_revision_id': current.id if current else None,
            'evidence_hash': fingerprint({'context': _stable(evidence), 'knowledge': kb.text, 'workflow': workflow}),
            'knowledge': {'available': True, 'version': kb.package_version, 'searched_through': kb.searched_through},
            'selected_files': kb.selected_files, 'prose': kb.text,
            'source_ids': [s['source_id'] for s in kb.sources],
            'schema_url': '/api/v1/coach/agent/schema'}


def _active(session: Session) -> tuple[list[PlanVersion], list[dict]]:
    plans = session.scalars(select(PlanVersion).where(PlanVersion.status == 'accepted').order_by(PlanVersion.start_date)).all()
    items = [x for p in plans for x in plan_data(session, p)['sessions']]
    return list(plans), items


def _public_target(target: dict) -> dict:
    return {k: v for k, v in target.items() if k not in {'provenance', 'revision_id'}}


def validate_proposal(body: Proposal, context: dict, before: list[dict]) -> list[str]:
    profile = context['profile']
    anchor = profile.get('cycle_anchor')
    if not profile.get('anchor_confirmed') or not anchor or not profile.get('strength_days_confirmed'):
        fail('schedule_unconfirmed', 'Confirmed run anchor and strength recurrence are required.')
    expected = {str(x['date']) for x in context['run_opportunities']}
    supplied = [s.date.isoformat() for s in body.sessions]
    if len(supplied) != len(set(supplied)):
        fail('duplicate_session', 'Only one running prescription per date is allowed.')
    if body.workflow == 'weekly' and set(supplied) != expected:
        fail('incomplete_horizon', 'Weekly proposals must cover every run opportunity in the rolling 14-day window, using rest where needed.')
    if any(d not in expected for d in supplied):
        fail('run_parity', 'A proposed run date is outside the confirmed every-other-day cycle.')
    prior = {(str(s['date']), s['kind']): s for s in before}
    runs = [a for a in context['recent_activities'] if a.get('sport') in RUN_SPORTS and not a.get('annotations', {}).get('excluded')]
    baseline_max = max((a.get('elapsed_s') or 0 for a in runs), default=0) / 60
    warnings = []
    baseline_distance = max((a.get('distance_m') or 0 for a in runs), default=0) / 1000
    baseline_total = sum(a.get('elapsed_s') or 0 for a in runs) / 60
    baseline_total_distance = sum(a.get('distance_m') or 0 for a in runs) / 1000
    candidate = {str(s['date']): s['target'] for s in before if s['kind'] == 'run' and str(s['date']) >= body.as_of.isoformat()}
    for item in body.sessions:
        target = item.target.model_dump(exclude_none=True)
        previous = prior.get((item.date.isoformat(), 'run'))
        changed = not previous or _public_target(previous['target']) != target
        recorded_same_date = any(str(a['local_date']) == item.date.isoformat() for a in runs)
        if previous and changed and recorded_same_date and not previous.get('completion_link_id'):
            fail('actual_requires_matching', 'A recorded run already exists on this date; confirm its plan completion link before changing the prescription.')
        if previous and changed and (previous.get('completion_link_id') or previous['target'].get('locked')):
            fail('protected_session', 'Completed or locked sessions cannot be changed.')
        if item.target.intent == 'rest' and (item.target.duration_minutes is not None or item.target.distance_km is not None or item.target.steps):
            fail('contradictory_rest', 'Rest prescriptions cannot contain running duration, distance or repetition targets.')
        if item.target.intent != 'rest' and item.target.duration_minutes is None and item.target.distance_km is None:
            fail('missing_exposure', 'Each running session needs a usable duration or distance target.')
        if item.target.intent == 'long' and item.date.weekday() not in (5, 6):
            fail('long_run_weekend', 'Long runs must be on Saturday or Sunday.')
        if item.target.duration_minutes and baseline_max and item.target.duration_minutes > max(30, baseline_max * 1.6):
            fail('load_jump', 'Proposed duration exceeds the broad recent-exposure safety bound; consolidate observed tolerance first.')
        if item.target.duration_minutes and not baseline_max and item.target.duration_minutes > 30:
            fail('unknown_baseline', 'Without observed running duration, keep the initial prescription at 30 minutes or less.')
        if item.target.distance_km and baseline_distance and item.target.distance_km > max(5, baseline_distance * 1.6):
            fail('load_jump', 'Proposed distance exceeds the broad recent-exposure safety bound.')
        if item.target.distance_km and not baseline_distance and item.target.distance_km > 5:
            fail('unknown_baseline', 'Without observed running distance, keep the initial distance at 5 km or less.')
        candidate[item.date.isoformat()] = target
    proposed_total = sum(t.get('duration_minutes') or 0 for d, t in candidate.items()
                         if body.as_of.isoformat() <= d <= (body.as_of+timedelta(days=13)).isoformat()
                         and t.get('intent') != 'rest')
    if not baseline_total and proposed_total > 105:
        fail('unknown_baseline', 'Without observed duration, keep the initial rolling 14-day total at 105 minutes or less.')
    if baseline_total and proposed_total > max(105, baseline_total * 1.6):
        fail('load_jump', 'The rolling 14-day prescription exceeds the broad recent-duration safety bound.')
    proposed_distance = sum(t.get('distance_km') or 0 for d, t in candidate.items()
                            if body.as_of.isoformat() <= d <= (body.as_of+timedelta(days=13)).isoformat()
                            and t.get('intent') != 'rest')
    if proposed_distance > max(15, baseline_total_distance * 1.6):
        fail('load_jump', 'The rolling 14-day prescription exceeds the broad recent-distance safety bound.')
    demanding_by_day = {d: t['intent'] for d, t in candidate.items() if t.get('intent') in {'long', 'quality'}}
    for activity in runs:
        observed_day = str(activity['local_date'])
        if observed_day <= body.as_of.isoformat() and activity.get('workout_label') in {'quality', 'long'}:
            demanding_by_day[observed_day] = activity['workout_label']
    demanding = sorted((date.fromisoformat(d), intent) for d, intent in demanding_by_day.items())
    for (first, intent), (second, next_intent) in zip(demanding, demanding[1:]):
        # Past spacing is evidence, not something a future proposal can repair.
        if second < body.as_of or (second == body.as_of and any(str(a['local_date']) == second.isoformat() for a in runs)):
            continue
        if (second-first).days < (3 if intent == next_intent == 'quality' else 2):
            fail('hard_spacing', 'Demanding runs need at least 48 hours separation, and quality runs 72 hours.')
    for item in body.sessions:
        if item.target.intent in {'quality', 'long'} and any(str(s['date']) == item.date.isoformat() and s['kind'] == 'strength' for s in context['recurring_sessions']):
            warnings.append(f'{item.date}: demanding run shares a full-body strength day; preserve the commitment and explain sequencing in the prescription.')
    # Physiological scores alone never decide this guard. Current reported function
    # protects against incompatible hard work; unknown feedback stays unknown.
    same_day = [c for c in context['recent_checkins'] if c['observed_at'].astimezone(ZoneInfo(context['timezone'])).date() == body.as_of]
    if same_day and (same_day[0].get('gait') == 'affected' or same_day[0].get('symptoms') == 'severe'):
        effective_today = candidate.get(body.as_of.isoformat())
        if effective_today and effective_today.get('intent') != 'rest':
            fail('current_symptoms', 'Affected gait or severe current symptoms requires a rest prescription today.')
    return warnings


def _persist(session: Session, *, day: date, workflow: str, summary: str, rationale: str, evidence_hash: str,
             key: str, current: CoachPlanRevision | None, before: list[dict], updates: list[dict], inputs: dict,
             review: dict, source_ids: list[str], warnings: list[str], rollback_of_id: str | None = None) -> dict:
    from app.services.legacy_cutover import require_legacy_write
    require_legacy_write(session)
    profile = current_profile(session)
    revision_id = uuid.uuid4()
    before_by = {(str(s['date']), s['kind']): s for s in before}
    recorded_dates = {a.start_at.astimezone(ZoneInfo(tz(session))).date().isoformat()
        for a in session.scalars(select(Activity).where(Activity.local_date >= day-timedelta(days=1),
            Activity.local_date <= day+timedelta(days=13), Activity.start_at <= datetime.now(UTC), Activity.sport.in_(RUN_SPORTS))).all()}
    after_by = dict(before_by)
    diff = []
    for item in updates:
        slot = (str(item['date']), item['kind'])
        old = before_by.get(slot)
        target = item['target']
        if old and _public_target(old['target']) == _public_target(target):
            continue
        if old and item['kind'] == 'run' and slot[0] in recorded_dates and not old.get('completion_link_id'):
            fail('actual_requires_matching', 'Confirm the recorded run completion link before changing this date.')
        if old and (str(old['date']) < day.isoformat() or old.get('completion_link_id') or old['target'].get('locked')):
            fail('protected_session', 'Historical, completed or locked sessions cannot be changed.')
        diff.append({'date': slot[0], 'kind': slot[1], 'before': old['target'] if old else None,
                     'after': target, 'reason': target.get('reason') or rationale})
        after_by[slot] = {'date': slot[0], 'kind': slot[1], 'target': target}
    plan = session.get(PlanVersion, current.plan_id) if current and current.plan_id else None
    if diff:
        end = max(day+timedelta(days=13), *(date.fromisoformat(d) for d, _ in after_by))
        start = min(day, *(date.fromisoformat(d) for d, _ in after_by))
        plan = PlanVersion(id=uuid.uuid4(), version=(plan.version+1 if plan else 1), parent_id=plan.id if plan else None,
                           status='accepted', start_date=start, end_date=end, profile_version=profile.version if profile else 0,
                           anchor_date=profile.cycle_anchor if profile else None, reason=rationale, decided_at=datetime.now(UTC))
        session.add(plan)
        session.flush()
        for active in session.scalars(select(PlanVersion).where(PlanVersion.status == 'accepted', PlanVersion.id != plan.id)).all():
            active.status = 'superseded'
        for slot, item in after_by.items():
            if item.get('id'):
                continue
            target = {**item['target'], 'provenance': ENGINE, 'revision_id': str(revision_id)}
            row = PlannedSession(id=uuid.uuid4(), plan_id=plan.id, date=date.fromisoformat(slot[0]), kind=item['kind'], target=target)
            session.add(row)
            item.update({'id': str(row.id), 'target': target})
    # Membership keeps original source session rows, linked actuals, and old plans
    # intact. Changed sessions are new rows; old snapshots remain inspectable.
    revision = CoachPlanRevision(id=revision_id, parent_revision_id=current.id if current else None,
        plan_id=plan.id if plan else None, workflow=workflow, as_of=day, created_at=datetime.now(UTC), idempotency_key=key,
        evidence_hash=evidence_hash, summary=summary, rationale=rationale,
        inputs=jsonable_encoder(inputs), payload=jsonable_encoder({'diff': diff, 'review': review,
            'source_ids': source_ids, 'warnings': warnings, 'rollback_of_id': rollback_of_id,
            'before': before, 'after': list(after_by.values()),
            'active_session_ids': [str(s['id']) for s in after_by.values() if s.get('id')]}))
    session.add(revision)
    from app.db import bump_data_revision
    bump_data_revision(session)
    session.commit()
    return {'revision': format_revision(revision), 'plan': plan_data(session, plan) if plan else None, 'unchanged': not diff}


def _replayed(session: Session, row: CoachPlanRevision) -> dict:
    current = latest(session)
    active_plan = session.scalar(select(PlanVersion).where(PlanVersion.status == 'accepted')
                                 .order_by(desc(PlanVersion.decided_at), desc(PlanVersion.created_at)).limit(1))
    revision = format_revision(row)
    revision['superseded_by_revision_id'] = current.id if current and current.id != row.id else None
    return {'revision': revision, 'plan': plan_data(session, active_plan) if active_plan else None,
            'unchanged': True, 'replayed': True, 'current_revision_id': current.id if current else None}


def submit(session: Session, body: Proposal) -> dict:
    # One transaction lock also serializes initial creation and identical retries.
    session.execute(text('SELECT pg_advisory_xact_lock(71382413)'))
    from app.services.legacy_cutover import require_legacy_write
    require_legacy_write(session)
    cached = session.scalar(select(CoachPlanRevision).where(CoachPlanRevision.idempotency_key == body.idempotency_key))
    if cached:
        if cached.inputs.get('proposal_hash') != fingerprint(body.model_dump(mode='json')):
            fail('idempotency_conflict', 'This request key was already used for a different proposal.', 409)
        return _replayed(session, cached)
    today = datetime.now(ZoneInfo(tz(session))).date()
    if body.as_of != today:
        fail('historical_write', 'Agent plans may be activated only for today.', 409)
    current = latest(session)
    state = agent_context(session, body.workflow, body.as_of)
    if state['evidence_hash'] != body.evidence_hash:
        fail('stale_evidence', 'Activities, recovery, feedback, profile, plan starting point or research changed. Reload context.', 409)
    repeated = session.scalar(select(CoachPlanRevision).where(CoachPlanRevision.workflow == body.workflow,
        CoachPlanRevision.as_of == body.as_of, CoachPlanRevision.evidence_hash == body.evidence_hash))
    if repeated:
        return _replayed(session, repeated)
    if body.expected_revision_id != (current.id if current else None):
        fail('revision_conflict', 'The active coaching revision changed. Reload context.', 409)
    _, before = _active(session)
    if body.workflow == 'daily' and not any(s['kind'] == 'run'
            and body.as_of.isoformat() <= str(s['date']) <= (body.as_of+timedelta(days=13)).isoformat()
            for s in before):
        fail('missing_weekly_plan', 'Create the weekly running plan before making a daily decision.', 409)
    warnings = validate_proposal(body, state['context'], before)
    kb = _knowledge(body.workflow, body.source_ids)
    known_activities = {str(a['id']) for a in state['context']['recent_activities']}
    known_checkins = {str(c['id']) for c in state['context']['recent_checkins']}
    for evidence in body.review.evidence:
        if any(str(x) not in known_activities for x in evidence.get('activity_ids', [])):
            fail('invalid_evidence', 'A review references an activity absent from the supplied context.')
        if any(str(x) not in known_checkins for x in evidence.get('checkin_ids', [])):
            fail('invalid_evidence', 'A review references a check-in absent from the supplied context.')
        if any(x not in body.source_ids for x in evidence.get('source_ids', [])):
            fail('invalid_evidence', 'Review sources must be included in the selected source IDs.')
    updates = [s.model_dump(mode='json', exclude_none=True) for s in body.sessions]
    if body.workflow == 'weekly':
        # Existing calendar suppresses recurrence inside accepted plan ranges.
        # Materialize the unchanged commitments alongside running prescriptions.
        profile = current_profile(session)
        existing = {(str(s['date']), s['kind']) for s in before}
        for slot in recurring_sessions(body.as_of, body.as_of+timedelta(days=13), profile):
            if (slot['date'], slot['kind']) not in existing:
                updates.append({'date': slot['date'], 'kind': slot['kind'],
                    'target': {'optional': slot['optional'], 'source': 'recurring_schedule',
                               'reason': 'Preserve the confirmed strength and mobility rotation.'}})
    return _persist(session, day=body.as_of, workflow=body.workflow, summary=body.summary, rationale=body.rationale,
                    evidence_hash=body.evidence_hash, key=body.idempotency_key, current=current,
                    before=before, updates=updates,
                    inputs={'context_snapshot': state, 'proposal': body.model_dump(mode='json'),
                            'proposal_hash': fingerprint(body.model_dump(mode='json')), 'selected_source_records': kb.sources,
                            'knowledge_version': kb.package_version, 'knowledge_digest': fingerprint(kb.text)},
                    review=body.review.model_dump(), source_ids=body.source_ids, warnings=warnings)


def revertible(session: Session, current: CoachPlanRevision | None = None) -> CoachPlanRevision | None:
    cursor = current or latest(session)
    while cursor and cursor.workflow != 'rollback':
        if cursor.payload.get('diff'):
            return cursor
        cursor = session.get(CoachPlanRevision, cursor.parent_revision_id) if cursor.parent_revision_id else None
    return None


def rollback(session: Session, revision_id: uuid.UUID, expected_revision_id: uuid.UUID, reason: str) -> dict:
    session.execute(text('SELECT pg_advisory_xact_lock(71382413)'))
    from app.services.legacy_cutover import require_legacy_write
    require_legacy_write(session)
    current = latest(session)
    target = revertible(session, current)
    if not current or current.id != expected_revision_id or not target or revision_id != target.id:
        fail('revision_conflict', 'Only the latest changed revision can be rolled back; reload history.', 409)
    day = datetime.now(ZoneInfo(tz(session))).date()
    _, before = _active(session)
    originals = {(str(x['date']), x['kind']): x for x in target.payload.get('before', [])}
    updates = []
    for item in before:
        if str(item['date']) < day.isoformat() or item.get('completion_link_id') or item['target'].get('locked'):
            continue
        original = originals.get((str(item['date']), item['kind']))
        if original:
            updates.append({'date': str(item['date']), 'kind': item['kind'], 'target': original['target']})
        elif item['kind'] == 'run':
            updates.append({'date': str(item['date']), 'kind': 'run', 'target': {
                'intent': 'rest', 'purpose': 'Withdraw the rolled-back prescription',
                'prescription': 'No running prescription is active for this opportunity; ask the coach to replan.',
                'intensity': 'No exercise target.', 'reason': reason}})
    return _persist(session, day=day, workflow='rollback', summary='Rolled back: '+target.summary,
                    rationale=reason, evidence_hash=fingerprint({'rollback': str(target.id)}), key='rollback-'+str(target.id),
                    current=current, before=before, updates=updates, inputs={'rollback_of_id': str(target.id)},
                    review=current.payload.get('review', {}), source_ids=current.payload.get('source_ids', []),
                    warnings=['Completed, locked and historical sessions were preserved.'], rollback_of_id=str(target.id))
