"""Deterministic daily guidance. Missing measurements remain unknown."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.encoders import jsonable_encoder
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.core import current_profile
from app.calendar_models import SessionCompletion
from app.checkin_models import Checkin, SymptomReport
from app.coach_v2_models import DailyGuidance
from app.models import AppState
from app.models import Checkin as LegacyCheckin
from app.services.calendar import _lock, state_at
from app.services.knowledge import load_knowledge

ENGINE = 'local_rules.v2'


@dataclass(frozen=True)
class DailyInputs:
    today: date
    as_of: date
    session_uid: uuid.UUID | None
    session_kind: str | None
    intent: str | None
    has_plan: bool
    anchor_confirmed: bool
    fatigue: float | None
    illness: str | None
    gait_change: str | None
    symptoms: tuple[dict, ...]
    prior_symptoms: tuple[dict, ...]
    clinical_restriction: str | None
    legacy_safety_active: bool
    missed_committed_runs: int
    delayed_symptom_reported: bool


def references(policy_ids: list[str]) -> dict:
    if not policy_ids:
        return {'policy_ids': [], 'evidence_ids': []}
    context = load_knowledge('daily', policy_ids=policy_ids)
    return {'policy_ids': policy_ids,
            'evidence_ids': sorted({evidence for policy in context.policies
                                    for evidence in policy['evidence_ids']})}


def _instant(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _symptom_state(inputs: DailyInputs) -> tuple[float, bool]:
    severity = max((float(item['severity']) for item in inputs.symptoms), default=0.0)
    worse = False
    for current in inputs.symptoms:
        observed = _instant(current.get('observed_at'))
        if observed is None:
            continue
        current_key = (observed, _instant(current.get('recorded_at')) or observed,
                       str(current.get('id') or ''))
        candidates = []
        for prior in inputs.prior_symptoms:
            if prior.get('site') != current.get('site') or prior.get('side') != current.get('side'):
                continue
            earlier = _instant(prior.get('observed_at'))
            if earlier is None or not observed - timedelta(days=7) <= earlier < observed:
                continue
            key = (earlier, _instant(prior.get('recorded_at')) or earlier,
                   str(prior.get('id') or ''))
            if key < current_key:
                candidates.append((key, prior))
        if candidates and float(current['severity']) > float(max(candidates, key=lambda pair: pair[0])[1]['severity']):
            worse = True
    return severity, worse


def daily_v2(inputs: DailyInputs) -> dict:
    severity, worse = _symptom_state(inputs)
    mild = 0 < severity <= 3
    moderate = 3 < severity < 6.5
    severe = severity >= 6.5
    decision = 'proceed'
    rationale = 'Keep the planned exposure familiar; check effort and symptoms during warm-up.'
    policies: list[str] = []
    if inputs.clinical_restriction and inputs.clinical_restriction.strip():
        decision, rationale, policies = ('seek_clinical_input',
            'Follow the current clinician restriction and clarify allowed activity before training.', ['P018'])
    elif inputs.illness == 'present':
        decision, rationale, policies = ('seek_clinical_input',
            'Systemic illness symptoms need clinical guidance before resuming training.', ['P004', 'P018'])
    elif inputs.legacy_safety_active or inputs.gait_change == 'yes' or ((moderate or severe) and worse):
        decision, rationale, policies = ('seek_clinical_input',
            'Movement change or worsening symptoms need clinical assessment before progressing.', ['P005', 'P018'])
    elif worse or moderate or severe:
        decision, rationale, policies = ('modify',
            'Current symptoms warrant a smaller familiar exposure and delayed reassessment.', ['P005', 'P006', 'P008'])
    elif inputs.illness == 'possible':
        decision, rationale, policies = ('modify',
            'Illness may be developing; use a familiar easy option only if symptoms allow.', ['P001', 'P004', 'P013'])
    elif inputs.session_kind == 'run' and inputs.fatigue is not None and inputs.fatigue >= 7:
        decision, rationale, policies = ('modify',
            'High fatigue calls for a smaller familiar run exposure today.', ['P001'])
    elif inputs.session_kind == 'run' and mild and any(
        word in (inputs.intent or '').casefold() for word in ('quality', 'long')):
        decision, rationale, policies = ('modify',
            'A demanding run with current symptoms needs a familiar easy fallback.', ['P001'])
    if decision == 'proceed' and not inputs.has_plan and not inputs.anchor_confirmed:
        decision, rationale, policies = ('modify',
            'Confirm the run cycle anchor and plan before choosing an exposure.', ['P001', 'P013'])
    if decision == 'proceed' and inputs.as_of > inputs.today:
        decision, rationale, policies = ('modify',
            'A future-day option is provisional until current observations are available.', ['P001'])
    missing = [key for key, value in (
        ('fatigue', inputs.fatigue), ('illness', inputs.illness),
        ('gait_change', inputs.gait_change), ('clinical_restriction', inputs.clinical_restriction),
        ('session', inputs.session_kind)) if value is None]
    triggers = []
    if decision != 'proceed':
        triggers.append('non_proceed')
    if moderate or severe:
        triggers.append('moderate_symptoms')
    if worse:
        triggers.append('worsening_symptoms')
    if inputs.gait_change == 'yes':
        triggers.append('gait_changed')
    if inputs.illness in {'possible', 'present'}:
        triggers.append('illness_reported')
    if inputs.missed_committed_runs >= 2:
        triggers.append('repeated_missed_runs')
    if inputs.delayed_symptom_reported:
        triggers.append('delayed_symptoms_reported')
    refs = references(policies)
    return {'decision': decision, 'rationale': rationale, 'missing_inputs': missing,
        'coach_review_suggested': bool(triggers), 'trigger_codes': triggers,
        **refs}


def _legacy_safety(session: Session, now: datetime) -> tuple[bool, list[dict]]:
    rows = session.scalars(select(LegacyCheckin).where(
        LegacyCheckin.observed_at >= now - timedelta(hours=72),
        LegacyCheckin.observed_at <= now).order_by(LegacyCheckin.observed_at, LegacyCheckin.id)).all()
    facts = [{'id': str(row.id), 'version': row.version, 'observed_at': row.observed_at,
              'symptoms': row.symptoms, 'change': row.change, 'gait': row.gait} for row in rows]
    active = any(row.gait == 'affected' or row.symptoms == 'severe' or
                 (row.symptoms == 'moderate' and row.change == 'worse') for row in rows)
    return active, facts


def _inputs(session: Session, *, today: date, checkin_id: uuid.UUID | None,
            now: datetime) -> tuple[DailyInputs, list[dict]]:
    profile = current_profile(session)
    head = session.get(AppState, 1)
    sessions = state_at(session, head.calendar_head_version if head else 0)
    current_session = next((item for item in sessions if item['local_date'] == today), None)
    zone = ZoneInfo(profile.timezone if profile else 'America/New_York')
    checkin = session.get(Checkin, checkin_id) if checkin_id else session.scalar(
        select(Checkin).where(Checkin.observed_at <= now).order_by(desc(Checkin.observed_at),
        desc(Checkin.recorded_at), desc(Checkin.id)).limit(1))
    if checkin and checkin.observed_at.astimezone(zone).date() != today:
        checkin = None
    symptoms = []
    prior = []
    if checkin:
        for row in session.scalars(select(SymptomReport).where(SymptomReport.checkin_id == checkin.id)):
            symptoms.append({'id': str(row.id), 'site': row.site, 'side': row.side,
                'severity': row.severity, 'observed_at': checkin.observed_at,
                'recorded_at': checkin.recorded_at})
        prior_rows = session.execute(select(SymptomReport, Checkin).join(Checkin,
            SymptomReport.checkin_id == Checkin.id).where(
            Checkin.observed_at >= checkin.observed_at - timedelta(days=7),
            Checkin.observed_at <= checkin.observed_at,
            Checkin.id != checkin.id)).all()
        for row, parent in prior_rows:
            prior.append({'id': str(row.id), 'site': row.site, 'side': row.side,
                'severity': row.severity, 'observed_at': parent.observed_at,
                'recorded_at': parent.recorded_at})
    legacy_active, legacy_facts = _legacy_safety(session, now)
    recent_committed_runs = {item['session_uid'] for item in sessions
        if item['kind'] == 'run' and item['certainty'] == 'committed'
        and today - timedelta(days=7) <= item['local_date'] < today}
    missed = sum(row.session_uid in recent_committed_runs for row in session.scalars(
        select(SessionCompletion).where(SessionCompletion.status.in_(['skipped', 'unknown']))))
    restriction = None
    if profile:
        value = (profile.facts or {}).get('clinician_restriction')
        if isinstance(value, str) and value.strip() not in {'none', 'unknown'}:
            restriction = value
    inputs = DailyInputs(today=today, as_of=today,
        session_uid=current_session['session_uid'] if current_session else None,
        session_kind=current_session['kind'] if current_session else None,
        intent=current_session['intent'] if current_session else None,
        has_plan=bool(sessions), anchor_confirmed=bool(profile and profile.anchor_confirmed),
        fatigue=checkin.fatigue if checkin else None,
        illness=checkin.illness if checkin else None,
        gait_change=checkin.gait_change if checkin else None,
        symptoms=tuple(symptoms), prior_symptoms=tuple(prior),
        clinical_restriction=restriction, legacy_safety_active=legacy_active,
        missed_committed_runs=missed, delayed_symptom_reported=bool(
            checkin and checkin.kind == 'delayed_followup' and symptoms))
    return inputs, legacy_facts


def guidance_data(row: DailyGuidance) -> dict:
    result = {key: getattr(row, key) for key in ('id', 'local_date', 'checkin_id',
        'engine', 'decision', 'session_uid', 'rationale', 'missing_inputs',
        'coach_review_suggested', 'trigger_codes', 'created_at', 'input_hash')}
    result['created_at'] = row.created_at.astimezone(UTC)
    return result


def persist_daily_guidance(session: Session, *, today: date,
        checkin_id: uuid.UUID | None = None, now: datetime) -> dict:
    _lock(session)
    inputs, legacy_facts = _inputs(session, today=today, checkin_id=checkin_id, now=now)
    result = daily_v2(inputs)
    semantic_inputs = asdict(inputs)
    for key in ('symptoms', 'prior_symptoms'):
        semantic_inputs[key] = sorted(({name: value for name, value in item.items()
            if name not in {'id', 'recorded_at'}} for item in semantic_inputs[key]),
            key=lambda item: (str(item.get('observed_at')), str(item.get('site')),
                              str(item.get('side')), float(item.get('severity', 0))))
    payload = {'engine': ENGINE, 'inputs': semantic_inputs, 'policy_ids': result['policy_ids'],
               'evidence_ids': result['evidence_ids'], 'decision': result['decision'],
               'trigger_codes': result['trigger_codes'], 'legacy_facts': legacy_facts}
    digest = hashlib.sha256(json.dumps(jsonable_encoder(payload), sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    existing = session.scalar(select(DailyGuidance).where(DailyGuidance.local_date == today,
        DailyGuidance.input_hash == digest))
    if existing:
        return guidance_data(existing)
    row = DailyGuidance(local_date=today, checkin_id=checkin_id, engine=ENGINE,
        decision=result['decision'], session_uid=inputs.session_uid,
        rationale=result['rationale'], missing_inputs=result['missing_inputs'],
        coach_review_suggested=result['coach_review_suggested'],
        trigger_codes=result['trigger_codes'], created_at=now, input_hash=digest)
    session.add(row)
    session.flush()
    return guidance_data(row)
