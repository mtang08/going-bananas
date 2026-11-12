"""Disposable calendar preview fixture. Caller owns the transaction."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.checkin_models import Checkin, SessionRpe, SymptomReport
from app.fit_models import ActivityLap, ActivityStream, ActivityWorkoutStep
from app.metric_models import MetricResult, Prompt
from app.models import (
    Activity,
    AppState,
    CoverageInterval,
    ProfileVersion,
    RawObject,
    RecoveryObservation,
    SourceAccount,
    SourceRecord,
)
from app.planning_models import StrengthRoutineSlot
from app.services.calendar import apply_edits, seed_demo_calendar, state_at
from app.services.sync import import_activity_page, store_raw

TZ = ZoneInfo('America/New_York')


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), TZ).astimezone(UTC)


def _structure() -> list[dict]:
    def target(cue: str) -> dict:
        return {'modality': 'effort', 'low': None, 'high': None, 'effort_cue': cue}
    return [
        {'type': 'warmup', 'duration_type': 'time', 'duration_value': 600, 'target': target('easy')},
        {'type': 'repeat', 'count': 4, 'steps': [
            {'type': 'work', 'duration_type': 'time', 'duration_value': 300, 'target': target('threshold')},
            {'type': 'recovery', 'duration_type': 'time', 'duration_value': 120, 'target': target('easy jog')},
        ]},
        {'type': 'cooldown', 'duration_type': 'time', 'duration_value': 600, 'target': target('easy')},
    ]


def _runs(today: date) -> list[tuple[int, int, float | None]]:
    result = []
    for ago in range(28, 1, -2):
        if ago == 4:
            continue
        result.append((ago, 4800 if ago == 2 else 2880 if ago == 6 else 3300 if ago == 12 else 1800,
                       None if ago == 20 else 2.8))
    result.append((1, 1800, 2.8))
    return result


def _lap_specs(ago: int, timer: int, speed: float | None) -> list[tuple[int, float | None, int, int | None]]:
    if ago not in (6, 12):
        return [(timer, speed, 140, None)]
    reps = 4 if ago == 6 else 5
    work = [3.6, 3.6, 3.4, 3.6] if ago == 6 else [3.5] * 5
    specs: list[tuple[int, float | None, int, int | None]] = [(600, 2.8, 140, 0)]
    for k in range(reps):
        specs.extend([(300, work[k], 156 + 2 * (k + 1) if ago == 6 else 158, 1),
                      (120, 2.5, 140, 2)])
    specs.append((600, 2.8, 140, 4))
    if sum(row[0] for row in specs) != timer:
        raise ValueError('demo_lap_duration_mismatch')
    return specs


def _fit_rows(session: Session, activity: Activity, ago: int, timer: int, speed: float | None) -> None:
    if session.scalar(select(ActivityLap.id).where(ActivityLap.activity_id == activity.id).limit(1)):
        return
    specs = _lap_specs(ago, timer, speed)
    seconds: list[int] = []
    hr: list[int] = []
    speeds: list[float | None] = []
    distances: list[float | None] = []
    distance = 0.0
    offset = 0
    for index, (duration, lap_speed, bpm, step) in enumerate(specs):
        session.add(ActivityLap(activity_id=activity.id, lap_index=index,
            start_at=activity.start_at + timedelta(seconds=offset), timer_s=duration,
            elapsed_s=duration, distance_m=duration * lap_speed if lap_speed is not None else None,
            avg_speed_mps=lap_speed, avg_hr_bpm=bpm, max_hr_bpm=bpm,
            lap_trigger='session_end' if index == len(specs)-1 else 'time', wkt_step_index=step))
        for sec in range(offset, offset + duration):
            seconds.append(sec)
            hr.append(bpm)
            speeds.append(lap_speed)
            if lap_speed is None:
                distances.append(None)
            else:
                distance += lap_speed
                distances.append(distance)
        offset += duration
    session.add(ActivityStream(activity_id=activity.id, t_s=seconds, hr_bpm=hr,
        speed_mps=speeds, distance_m=distances, altitude_m=[None]*timer,
        cadence=[None]*timer, timer_on=[[0, timer]], sample_count=timer, max_gap_s=1,
        quality_flags=[]))
    if ago in (6, 12):
        steps = [
            ('Warm up', 'warmup', 'time', 600, None, None, None, None, None),
            ('Work', 'active', 'time', 300, 'speed', 3.4, 3.8, None, None),
            ('Recover', 'recovery', 'time', 120, None, None, None, None, None),
            (None, None, 'repeat_until_steps_cmplt', None, None, None, None, 1, 4 if ago == 6 else 5),
            ('Cool down', 'cooldown', 'time', 600, None, None, None, None, None),
        ]
        for index, (name, intensity, kind, step_duration, target, low, high, repeat_from, count) in enumerate(steps):
            session.add(ActivityWorkoutStep(activity_id=activity.id, message_index=index,
                step_name=name, intensity=intensity, duration_type=kind, duration_value=step_duration,
                target_type=target, target_low=low, target_high=high,
                repeat_from=repeat_from, repeat_count=count))


def _recovery(session: Session, private_dir: Path, today: date, now: datetime) -> None:
    account = session.scalar(select(SourceAccount).where(SourceAccount.provider == 'demo_fixture',
        SourceAccount.account_scope == 'synthetic-demo'))
    if account is None:
        raise ValueError('demo_source_account_missing')
    specs = [('sleep', 's', 'main_sleep_duration', 'garmin_sleep_calendar_date', lambda i: 25200 + (i % 3)*300),
             ('hrv', 'ms', 'last_night_average', 'garmin_hrv_calendar_date', lambda i: 60 + i % 3),
             ('resting_hr', 'bpm', 'daily_resting', 'garmin_heart_rate_calendar_date', lambda i: 52 + i % 2)]
    for i in range(1, 43):
        if i in (4, 6):
            continue
        day = today - timedelta(days=i)
        for metric, unit, statistic, semantics, value in specs:
            if session.scalar(select(RecoveryObservation.id).where(
                RecoveryObservation.source_account_id == account.id,
                RecoveryObservation.metric == metric, RecoveryObservation.source_date == day,
                RecoveryObservation.statistic == statistic).limit(1)):
                continue
            payload = json.dumps({'date': day.isoformat(), 'metric': metric, 'value': value(i)}, sort_keys=True).encode()
            digest, relative = store_raw(private_dir, payload)
            raw = session.scalar(select(RawObject).where(RawObject.sha256 == digest))
            if raw is None:
                raw = RawObject(sha256=digest, relative_path=relative, byte_size=len(payload),
                                media_type='application/json')
                session.add(raw)
                session.flush()
            source = SourceRecord(source_account_id=account.id, raw_object_id=raw.id,
                source_identity=f'demo-recovery:{day}:{metric}', payload_hash=digest,
                fetched_at=now, parser_version='demo-seed-v1', source_kind='demo_fixture',
                fields={'metric': metric, 'source_date': day.isoformat(), 'value': value(i)})
            session.add(source)
            session.flush()
            session.add(RecoveryObservation(source_account_id=account.id, source_record_id=source.id,
                metric=metric, source_date=day, time_semantics=semantics, value=value(i),
                unit=unit, statistic=statistic, source_revision=digest))
    for dataset in ('activities', 'sleep', 'hrv', 'resting_hr'):
        if session.scalar(select(CoverageInterval.id).where(CoverageInterval.dataset == dataset,
            CoverageInterval.start_date == today-timedelta(days=42),
            CoverageInterval.end_date == today-timedelta(days=1)).limit(1)):
            continue
        session.add(CoverageInterval(dataset=dataset, start_date=today-timedelta(days=42),
            end_date=today-timedelta(days=1), observed_start=today-timedelta(days=42),
            observed_end=today-timedelta(days=1), status='complete', completed_at=now,
            reason=None, fully_enumerated=True))


def _history(today: date, slots: dict[str, StrengthRoutineSlot]) -> list[dict]:
    entries: list[tuple[date, int, str, str, int, str | None, uuid.UUID | None, list[dict] | None]] = []
    for ago in (14, 10, 8, 4, 2, 12, 6):
        day = today - timedelta(days=ago)
        recipe = 'REC002' if ago == 2 else 'REC003' if ago in (12, 6) else 'REC001'
        entries.append((day, 0, 'run', 'Threshold 4 × 5 min' if recipe == 'REC003' else
                        'Long run' if recipe == 'REC002' else 'Easy run',
                        4800 if ago == 2 else 2880 if recipe == 'REC003' else 1800,
                        recipe, None, _structure() if recipe == 'REC003' else None))
    for ago in range(14, 0, -1):
        day = today - timedelta(days=ago)
        if day.weekday() in (0, 4):
            label = 'Full body A' if day.weekday() == 0 else 'Full body B'
            entries.append((day, 1, 'strength', label, 3600, None, slots[label].id, None))
    edits = []
    for day, slot, kind, intent, duration, recipe_id, strength_id, structure in entries:
        uid = uuid.uuid5(uuid.NAMESPACE_URL, f'going-bananas-demo:{day}:{kind}:{slot}')
        edits.append({'op': 'add', 'session_uid': str(uid), 'fields': {
            'local_date': day.isoformat(), 'slot': slot, 'kind': kind, 'recipe_id': recipe_id,
            'custom': False, 'intent': intent, 'planned_duration_s': duration,
            'planned_distance_m': None, 'structure': structure,
            'strength_slot_id': str(strength_id) if strength_id else None, 'notes': None}})
    if len({item['session_uid'] for item in edits}) != len(edits):
        raise ValueError('demo_duplicate_session_uid')
    return edits


def seed_demo(session: Session, private_dir: Path, today: date) -> dict[str, int]:
    state = session.get(AppState, 1)
    if state is None or state.planning_authority != 'calendar':
        raise ValueError('calendar_preview_authority_required')
    now = datetime.now(UTC)
    first_run = state.calendar_head_version == 0
    if first_run:
        latest = session.scalar(select(ProfileVersion).order_by(ProfileVersion.version.desc()).limit(1))
        session.add(ProfileVersion(version=(latest.version+1 if latest else 1), effective_at=now,
            timezone='America/New_York', cycle_anchor=today-timedelta(days=28),
            anchor_confirmed=True, strength_days_confirmed=True, scheduled_strength_days=[0,4],
            facts=latest.facts if latest else {},
            preferences={**(latest.preferences if latest else {}), 'weekly_review_weekday': 6},
            unknowns=latest.unknowns if latest else []))
        slots = {}
        for label, weekday in (('Full body A', 0), ('Full body B', 4)):
            slot = StrengthRoutineSlot(label=label, default_weekday=weekday,
                lower_body_cost='moderate', typical_duration_s=3600,
                main_lower_body_lifts=[], active=True, version=1)
            session.add(slot)
            slots[label] = slot
        session.flush()
    else:
        slots = {row.label: row for row in session.scalars(select(StrengthRoutineSlot).where(
            StrengthRoutineSlot.label.in_(['Full body A', 'Full body B']),
            StrengthRoutineSlot.version == 1)).all()}
    if set(slots) != {'Full body A', 'Full body B'}:
        raise ValueError('demo_strength_slots_missing')
    records = []
    for ago, timer, speed in _runs(today):
        day = today-timedelta(days=ago)
        stamp = _at(day, 7, 30 if ago == 1 else 0).isoformat().replace('+00:00', 'Z')
        record = {'activityId': 3000+ago, 'startTimeGMT': stamp,
            'activityType': {'typeKey': 'treadmill_running' if ago == 20 else 'running'},
            'elapsedDuration': timer, 'movingDuration': timer}
        if speed is not None:
            record['distance'] = timer * speed
        records.append(record)
    import_activity_page(session, private_dir, records, account_scope='synthetic-demo',
                         source_kind='demo_fixture')
    session.flush()
    for ago, timer, speed in _runs(today):
        activity = session.scalar(select(Activity).where(Activity.garmin_id == str(3000+ago)).limit(1))
        if activity is None:
            raise ValueError('demo_activity_import_failed')
        activity.timer_s = timer
        activity.end_at = activity.start_at + timedelta(seconds=timer)
        activity.fit_status = 'decoded'
        if ago == 20:
            activity.distance_m = None
        if ago == 10:
            activity.workout_rpe = 4.0
        _fit_rows(session, activity, ago, timer, speed)
        if ago == 10 and not session.scalar(select(SessionRpe.id).where(
            SessionRpe.activity_id == activity.id, SessionRpe.source == 'garmin_fit').limit(1)):
            session.add(SessionRpe(activity_id=activity.id, rpe=4.0, source='garmin_fit',
                collected_at=activity.end_at, collection_delay_s=0))
    _recovery(session, private_dir, today, now)
    if first_run:
        checkin = Checkin(idempotency_key='demo-seed-checkin-t5', kind='exception',
            observed_at=_at(today-timedelta(days=5), 8), recorded_at=now,
            context_tags=[], fatigue=None, illness=None, gait_change=None,
            activity_id=None, prompt_id=None, note=None)
        session.add(checkin)
        session.flush()
        session.add(SymptomReport(checkin_id=checkin.id, site='posterior tibial tendon',
            side='left', severity=2.0, timing='next_morning'))
        seed_demo_calendar(session, anchor_date=today-timedelta(days=28), start_date=today,
            now=_at(today, 12), history_edits=_history(today, slots))
        historical_long = today - timedelta(days=2)
        week_start = historical_long - timedelta(days=historical_long.weekday())
        duplicate = next((row for row in state_at(session, state.calendar_head_version)
            if row['local_date'] > today and row['recipe_id'] == 'REC002'
            and week_start <= row['local_date'] <= week_start + timedelta(days=6)), None)
        if duplicate:
            apply_edits(session, state.calendar_head_version, [{
                'op': 'modify', 'session_uid': str(duplicate['session_uid']),
                'fields': {'recipe_id': 'REC001', 'intent': 'Easy run'},
            }], reason='synthetic fixture: retain one planned long run per week', actor='system')
    session.flush()
    from app.metrics.engine import ensure_windows, recompute
    from app.services.prompts import generate_prompts
    recompute(session, 'all:'+ (today-timedelta(days=42)).isoformat())
    ensure_windows(session, as_of=today)
    generate_prompts(session, now=now)
    session.flush()
    planned = uuid.uuid5(uuid.NAMESPACE_URL,
        f'going-bananas-demo:{today-timedelta(days=6)}:run:0')
    if not session.scalar(select(SessionCompletion.id).where(
        SessionCompletion.session_uid == planned, SessionCompletion.activity_id.is_not(None)).limit(1)):
        raise ValueError('demo_structured_match_missing')
    return demo_totals(session)


def demo_totals(session: Session) -> dict[str, int]:
    """Whole-table totals; call after commit to include commit-time derived refresh."""
    tables = {
        'activities': Activity, 'activity_laps': ActivityLap,
        'activity_streams': ActivityStream, 'activity_workout_steps': ActivityWorkoutStep,
        'calendar_session_revisions': CalendarSessionRevision, 'calendar_versions': CalendarVersion,
        'checkins_v2': Checkin, 'coverage_intervals': CoverageInterval,
        'metric_results': MetricResult, 'prompts': Prompt,
        'recovery_observations': RecoveryObservation,
        'session_completions': SessionCompletion, 'session_rpe': SessionRpe,
        'strength_routine_slots': StrengthRoutineSlot,
    }
    return {name: session.scalar(select(func.count()).select_from(model)) or 0
            for name, model in sorted(tables.items())}
