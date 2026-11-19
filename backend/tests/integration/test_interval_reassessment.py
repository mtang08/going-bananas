"""Reassess a linked synthetic workout while preserving prior metric history."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from test_metrics_flow import NOW, TODAY, db, seed  # noqa: F401

from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.fit_models import ActivityLap, ActivityStream, ActivityWorkoutStep
from app.metric_models import MetricResult
from app.metrics import engine, intervals
from app.metrics.contract import config_hash
from app.models import Activity, AppState


@pytest.mark.parametrize('short_work, expected', [(False, 'completed_as_planned'), (True, 'completed_modified')])
def test_interval_reassessment_preserves_history(db, tmp_path, short_work, expected):  # noqa: F811
    activity_id = seed(db, tmp_path)[-1]
    uid = uuid.uuid4()
    with db() as session:
        session.info['metrics_now'] = NOW
        activity = session.get(Activity, activity_id)
        durations = [300, 300, 300, 120, 300, 120, 300, 120, 300, 120, 300, 600]
        if short_work:
            durations[4] = 200
        total = sum(durations)
        activity.timer_s = total
        activity.end_at = activity.start_at + timedelta(seconds=total)
        refs = [0, 0, 1, 2, 1, 2, 1, 2, 1, 2, 1, 4]
        offset = 0
        for index, (duration, ref) in enumerate(zip(durations, refs)):
            session.add(ActivityLap(activity_id=activity_id, lap_index=index,
                start_at=activity.start_at + timedelta(seconds=offset), timer_s=duration,
                elapsed_s=duration, distance_m=duration * 3, wkt_step_index=ref))
            offset += duration
        for index, intensity, duration_type, value, repeat_from, count in [
            (0, 'warmup', 'time', 600, None, None), (1, 'active', 'time', 300, None, None),
            (2, 'recovery', 'time', 120, None, None), (3, None, 'repeat_until_steps_cmplt', None, 1, 5),
            (4, 'cooldown', 'time', 600, None, None),
        ]:
            session.add(ActivityWorkoutStep(activity_id=activity_id, message_index=index,
                intensity=intensity, duration_type=duration_type, duration_value=value,
                repeat_from=repeat_from, repeat_count=count))
        session.add(ActivityStream(activity_id=activity_id, t_s=list(range(total + 1)),
            hr_bpm=[150] * (total + 1), speed_mps=[3.0] * (total + 1),
            distance_m=[None] * (total + 1), altitude_m=[None] * (total + 1),
            cadence=[None] * (total + 1), timer_on=[[0, total]], sample_count=total + 1,
            max_gap_s=1, quality_flags=[]))
        session.get(AppState, 1).calendar_head_version = 1
        session.add(CalendarVersion(number=1, kind='bootstrap', actor='system'))
        session.flush()
        structure = [
            {'type': 'warmup', 'duration_type': 'time', 'duration_value': 600, 'target': None},
            {'type': 'repeat', 'count': 5, 'steps': [
                {'type': 'work', 'duration_type': 'time', 'duration_value': 300, 'target': {'modality': 'effort', 'effort_cue': 'steady'}},
                {'type': 'recovery', 'duration_type': 'time', 'duration_value': 120, 'target': None},
            ]},
            {'type': 'cooldown', 'duration_type': 'time', 'duration_value': 600, 'target': None},
        ]
        session.add(CalendarSessionRevision(session_uid=uid, revision=1, calendar_version_number=1,
            local_date=TODAY, kind='run', intent='Synthetic intervals', planned_duration_s=3420,
            certainty='committed', structure=structure))
        completion = SessionCompletion(session_uid=uid, activity_id=activity_id, status='unknown',
            match_method='auto_same_day', modification_reason=None, version=1, input_version=1, updated_at=NOW)
        session.add(completion)
        stale = MetricResult(metric_id=intervals.METRIC_ID, method_version=intervals.METHOD_VERSION,
            subject_type='activity', subject_key=str(activity_id), status='not_assessable', value=None,
            reason_codes=['LAP_STEP_ORDER_MISMATCH'], quality_flags=[], source_refs={}, anchor_keys=[],
            config_hash='0' * 64, dependency_hash='1' * 64, calculated_at=NOW, timezone='UTC', is_current=True)
        session.add(stale)
        session.flush()
        initial_version = completion.version
        engine.assess_completion(session, uid)
        session.flush()
        current = session.scalar(select(MetricResult).where(MetricResult.metric_id == intervals.METRIC_ID,
            MetricResult.subject_key == str(activity_id), MetricResult.is_current.is_(True)))
        assert current.config_hash == config_hash(intervals.CONFIG)
        assert current.value['step_completion_ratio'] == (0.8 if short_work else 1.0)
        assert {'LAP_SPLIT_MERGED', 'NONWORK_STEP_OMITTED'} <= set(current.quality_flags)
        assert session.get(MetricResult, stale.id).is_current is False
        planned = session.scalar(select(MetricResult).where(MetricResult.metric_id == 'planned_actual_session',
            MetricResult.subject_key == str(uid), MetricResult.is_current.is_(True)))
        assert planned.value['overall_status'] == expected
        assert completion.status == expected
        assert completion.version == initial_version + 1
        assert completion.match_method == 'auto_same_day'
        assert completion.activity_id == activity_id
        assert completion.modification_reason is None
