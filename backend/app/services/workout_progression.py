"""Same-workout progression read model over WC interval results (TI D1–D7)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar_models import SessionCompletion
from app.metrics import intervals
from app.metrics.engine import current_results
from app.models import Activity, AppState
from app.services.calendar import state_at
from app.services.calendar_structure import expand_structure, work_signature
from app.services.timezone import athlete_tz, local_date

ASSESSABLE = ('available', 'partial')


def plan_facts(structure: list[dict] | None) -> dict | None:
    signature = work_signature(structure)
    if signature is None:
        return None
    steps = expand_structure(structure)  # type: ignore[arg-type]
    work = [i for i, step in enumerate(steps) if step['type'] == 'work']
    between = [step for step in steps[work[0]:work[-1] + 1] if step['type'] == 'recovery']
    return {'signature': signature, 'n_work': len(work),
            'recovery_s': (sum(step['duration_value'] for step in between)
                           if all(step['duration_type'] == 'time' for step in between) else None),
            'target_modalities': sorted({(steps[i].get('target') or {}).get('modality', 'effort') for i in work})}


def _weighted(reps: list[dict], key: str) -> float | None:
    weight = sum(rep['actual_timer_s'] for rep in reps)
    return sum(rep[key] * rep['actual_timer_s'] for rep in reps) / weight if weight > 0 else None


def _round(value: float | None, places: int) -> float | None:
    return round(value, places) if value is not None else None


def session_point(planned: dict, completion: dict | None, activity: dict | None,
                  interval: dict | None) -> dict[str, Any]:
    facts = plan_facts(planned['structure'])
    if facts is None:
        raise ValueError('unstructured_session')
    point: dict[str, Any] = {
        'session_uid': str(planned['session_uid']),
        'activity_id': str(activity['id']) if activity else None,
        'local_date': (activity['local_date'] if activity else planned['local_date']).isoformat(),
        'planned_date': planned['local_date'].isoformat(),
        'recipe_id': planned.get('recipe_id'), 'intent': planned.get('intent'),
        'signature': facts['signature'], 'recovery_s': facts['recovery_s'],
        'target_modalities': facts['target_modalities'],
        'sport': activity['sport'] if activity else None,
        'completion_status': completion['status'] if completion else None,
        'status': 'missing', 'reason_codes': [],
        'quality_flags': ['TREADMILL'] if activity and activity['sport'] == 'treadmill_running' else [],
        'n_planned': facts['n_work'], 'n_completed': None, 'step_completion_ratio': None,
        'reps_used': 0, 'reps_used_hr': 0, 'work_speed_mps': None, 'work_hr_bpm': None,
        'work_m_per_beat': None, 'cv_speed': None, 'last_first_change_pct': None,
        'target_coverage': None, 'interval_result_id': str(interval['id']) if interval else None,
    }
    if activity is None:
        point['reason_codes'] = ['NO_LINKED_ACTIVITY']
        return point
    if interval is None:
        point['reason_codes'] = ['INTERVAL_RESULT_MISSING']
        return point
    value = interval['value']
    if value is None:
        point.update(status='not_assessable', reason_codes=sorted(interval['reason_codes']))
        return point
    usable = [rep for rep in value['reps'] if rep['fully_completed'] and rep['speed_status'] == 'available'
              and rep['mean_speed_mps'] is not None and rep['actual_timer_s'] is not None
              and rep['actual_timer_s'] > 0]
    with_hr = [rep for rep in usable if rep['hr_median_bpm'] is not None]
    hr = _weighted(with_hr, 'hr_median_bpm')
    hr_speed = _weighted(with_hr, 'mean_speed_mps')
    reasons = set(interval['reason_codes'])
    if len(usable) < value['n_completed']:
        reasons.add('REPS_EXCLUDED')
    full = interval['status'] == 'available' and len(usable) == value['n_planned']
    point.update(status='available' if full else 'partial', reason_codes=sorted(reasons),
                 n_planned=value['n_planned'], n_completed=value['n_completed'],
                 step_completion_ratio=value['step_completion_ratio'],
                 reps_used=len(usable), reps_used_hr=len(with_hr),
                 work_speed_mps=_round(_weighted(usable, 'mean_speed_mps'), 3),
                 work_hr_bpm=_round(hr, 1),
                 work_m_per_beat=_round(60 * hr_speed / hr, 3) if hr_speed is not None and hr else None,
                 cv_speed=value['cv_speed'], last_first_change_pct=value['last_first_change_pct'],
                 target_coverage=value['target_coverage'])
    return point


def assemble_groups(points: list[dict], group_by: str) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for point in sorted(points, key=lambda p: (p['local_date'], p['session_uid'])):
        key = (f"recipe:{point['recipe_id']}" if group_by == 'recipe' and point['recipe_id']
               else f"sig:{point['signature']}")
        groups.setdefault(key, []).append(point)
    result = [{'group_key': key, 'group_by': 'recipe' if key.startswith('recipe:') else 'signature',
               'signature': None if key.startswith('recipe:') else items[0]['signature'],
               'signatures': sorted({p['signature'] for p in items}),
               'recipe_ids': sorted({p['recipe_id'] for p in items if p['recipe_id']}),
               'sessions_total': len(items),
               'sessions_assessable': sum(p['status'] in ASSESSABLE for p in items),
               'latest_date': items[-1]['local_date'], 'points': items}
              for key, items in groups.items()]
    return sorted(result, key=lambda g: (g['latest_date'], g['group_key']), reverse=True)


RUN_SPORTS = ('running', 'trail_running', 'treadmill_running')
HISTORY_LOOKBACK_DAYS = 365
HISTORY_LOOKAHEAD_DAYS = 7


def _head_rows(session: Session) -> list[dict]:
    head = session.scalar(select(AppState.calendar_head_version).where(AppState.id == 1)) or 0
    return state_at(session, head) if head else []


def _structured_plans(session: Session, start: date, end: date) -> list[dict]:
    return [row for row in _head_rows(session)
            if row['kind'] == 'run' and start <= row['local_date'] <= end and work_signature(row['structure'])]


def _linked(session: Session, plans: list[dict]) -> tuple[dict, dict]:
    uids = [row['session_uid'] for row in plans]
    completions = {row.session_uid: row for row in session.scalars(
        select(SessionCompletion).where(SessionCompletion.session_uid.in_(uids)))} if uids else {}
    ids = [row.activity_id for row in completions.values() if row.activity_id]
    activities = {row.id: row for row in session.scalars(select(Activity).where(
        Activity.id.in_(ids), Activity.sport.in_(RUN_SPORTS)))} if ids else {}
    return completions, activities


def linked_run_ids(session: Session, start: date, end: date) -> list[UUID]:
    _, activities = _linked(session, _structured_plans(session, start, end))
    return sorted(activities, key=str)


def progression_points(session: Session, start: date, end: date) -> list[dict]:
    plans = _structured_plans(session, start, end)
    completions, activities = _linked(session, plans)
    rows = current_results(session, intervals.METRIC_ID, [str(uid) for uid in activities])
    tz = athlete_tz(session)
    points = []
    for plan in plans:
        completion = completions.get(plan['session_uid'])
        activity = activities.get(completion.activity_id) if completion and completion.activity_id else None
        row = rows.get(str(activity.id)) if activity else None
        points.append(session_point(
            plan, {'status': completion.status} if completion else None,
            {'id': activity.id, 'local_date': local_date(activity.start_at, tz), 'sport': activity.sport}
            if activity else None,
            {'id': row.id, 'status': row.status, 'reason_codes': list(row.reason_codes), 'value': row.value}
            if row else None))
    return sorted(points, key=lambda point: (point['local_date'], point['session_uid']))


def progression_groups(session: Session, start: date, end: date, group_by: str) -> list[dict]:
    return assemble_groups(progression_points(session, start, end), group_by)


def history_window(session: Session, activity: Activity) -> tuple[date, date]:
    day = local_date(activity.start_at, athlete_tz(session))
    return day - timedelta(days=HISTORY_LOOKBACK_DAYS), day + timedelta(days=HISTORY_LOOKAHEAD_DAYS)


def workout_history(session: Session, activity: Activity, limit: int) -> dict:
    result: dict[str, Any] = {'activity_id': str(activity.id), 'signature': None, 'reason': None, 'points': []}
    completion = session.scalar(select(SessionCompletion).where(SessionCompletion.activity_id == activity.id))
    plan = next((row for row in _head_rows(session)
                 if completion and row['session_uid'] == completion.session_uid), None)
    if plan is None or plan['kind'] != 'run':
        return {**result, 'reason': 'NO_PLAN_LINK'}
    if plan['structure'] is None:
        return {**result, 'reason': 'NO_STRUCTURED_PLAN'}
    signature = work_signature(plan['structure'])
    if signature is None:
        return {**result, 'reason': 'NO_WORK_STEPS'}
    start, end = history_window(session, activity)
    day = local_date(activity.start_at, athlete_tz(session)).isoformat()
    points = [p for p in progression_points(session, start, end)
              if p['signature'] == signature and p['local_date'] <= day]
    return {**result, 'signature': signature, 'points': points[-limit:]}
