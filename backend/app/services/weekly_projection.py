"""Read-only, athlete-local projection of this week's running distance."""
from __future__ import annotations

import math
import statistics
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.core import current_profile
from app.calendar_models import SessionCompletion
from app.metrics.engine import activities_coverage_complete, load_runs
from app.models import AppState, ManualSession
from app.services import calendar
from app.services.calendar_structure import StructureError, expand_structure


def _positive(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
        return float(value)
    return None


def _nonnegative(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def planned_distance(row: dict, pace_mps: float | None) -> tuple[float | None, bool]:
    """Return distance and whether any speed assumption was used."""
    direct = _positive(row.get('planned_distance_m'))
    if direct is not None:
        return direct, False
    structure = row.get('structure')
    if structure is not None:
        try:
            steps = expand_structure(structure)
        except StructureError:
            return None, False
        distance = 0.0
        elapsed = 0.0
        estimated = False
        all_time = all(step['duration_type'] == 'time' for step in steps)
        for step in steps:
            amount = float(step['duration_value'])
            if step['duration_type'] == 'distance':
                distance += amount
                continue
            elapsed += amount
            target = step.get('target') or {}
            speed = None
            if target.get('modality') == 'speed':
                low, high = _nonnegative(target.get('low')), _nonnegative(target.get('high'))
                if low is not None and high is not None:
                    speed = (low + high) / 2
            if speed is None:
                speed = pace_mps
            estimated = True
            if speed is None:
                return None, False
            distance += amount * speed
        remainder = max(0, float(row.get('planned_duration_s') or 0) - elapsed) if all_time else 0
        if remainder:
            if pace_mps is None:
                return None, False
            distance += remainder * pace_mps
            estimated = True
        return distance, estimated
    duration = _positive(row.get('planned_duration_s'))
    if duration is not None and pace_mps is not None:
        return duration * pace_mps, True
    return None, False


def weekly_projection(session: Session) -> dict:
    # Calendar writers use the exclusive variant of this transaction lock.
    session.execute(text('SELECT pg_advisory_xact_lock_shared(:key)'), {'key': calendar.LOCK_ID})
    today = calendar._today(session)
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    profile = current_profile(session)
    timezone = profile.timezone if profile else 'America/New_York'
    state = session.get(AppState, 1)
    head = state.calendar_head_version if state else 0
    planned = calendar.state_at(session, head)
    plan_through = max((row['local_date'] for row in planned), default=None)
    recent = load_runs(session, min(week_start, today - timedelta(days=27)), today + timedelta(days=1))
    speeds = [float(run.distance_m) / float(run.timer_s) for run in recent
              if run.local_date >= today - timedelta(days=27)
              if _positive(run.distance_m) is not None and _positive(run.timer_s) is not None
              and run.distance_m is not None and run.timer_s is not None]
    pace = statistics.median(speeds) if speeds else None
    actual = [run for run in recent if week_start <= run.local_date <= today]
    actual_distance = sum(run.distance_m or 0 for run in actual
                          if run.distance_m == 0 or _positive(run.distance_m) is not None)
    missing_actual = sum(run.distance_m != 0 and _positive(run.distance_m) is None for run in actual)
    completions = {row.session_uid: row for row in session.scalars(select(SessionCompletion)).all()}
    remaining_distance = 0.0
    remaining_runs = estimated_runs = missing_planned = unrecorded_past = 0
    for row in planned:
        if row['kind'] != 'run' or not week_start <= row['local_date'] <= week_end:
            continue
        completion = completions.get(row['session_uid'])
        if completion:
            if completion.status == 'skipped':
                continue
            if completion.status in {'completed_as_planned', 'completed_modified', 'partial', 'moved', 'extra'}:
                continue
            if completion.status == 'unknown':
                if row['local_date'] < today:
                    unrecorded_past += 1
                else:
                    missing_planned += 1
                continue
        if row['local_date'] < today:
            unrecorded_past += 1
            continue
        remaining_runs += 1
        distance, estimated = planned_distance(row, pace)
        if distance is None:
            missing_planned += 1
        else:
            remaining_distance += distance
            estimated_runs += int(estimated)
    # Standalone manual runs have no distance field; count each unless linked to a canonical run.
    manuals = session.scalars(select(ManualSession).where(ManualSession.kind == 'run',
        ManualSession.date >= week_start, ManualSession.date <= today)).all()
    missing_manuals = sum(manual.linked_activity_id is None
                          for manual in manuals)
    missing_actual += missing_manuals
    return {'week_start': week_start, 'week_end': week_end, 'today': today,
            'timezone': timezone, 'calendar_version': head,
            'actual_distance_m': actual_distance, 'remaining_distance_m': remaining_distance,
            'projected_distance_m': actual_distance + remaining_distance,
            'actual_runs': len(actual) + missing_manuals, 'remaining_runs': remaining_runs,
            'estimated_runs': estimated_runs, 'missing_actual_runs': missing_actual,
            'missing_planned_runs': missing_planned, 'unrecorded_past_runs': unrecorded_past,
            'pace_sample_count': len(speeds), 'pace_mps': pace,
            'plan_available': head > 0, 'plan_through': plan_through,
            'activity_coverage_complete': activities_coverage_complete(session, week_start, today + timedelta(days=1))}
