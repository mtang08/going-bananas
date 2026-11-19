"""Session reassessment preview and apply against synthetic PostgreSQL state."""

import json
import sys
import uuid
from datetime import timedelta

from sqlalchemy import select
from test_metrics_flow import NOW, TODAY, seed
from test_metrics_flow import db as db

from app import cli
from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.metric_models import MetricResult
from app.metrics import intervals, planned_actual
from app.models import AppState


def test_reassess_session_preview_then_apply(db, tmp_path, monkeypatch, capsys):
    activity_id = seed(db, tmp_path)[-1]
    uid = uuid.uuid4()
    with db() as session:
        session.info['metrics_now'] = NOW
        session.get(AppState, 1).calendar_head_version = 1
        session.add(CalendarVersion(number=1, kind='bootstrap', actor='system'))
        session.flush()
        session.add(CalendarSessionRevision(
            session_uid=uid, revision=1, calendar_version_number=1, local_date=TODAY,
            kind='run', intent='Synthetic run', planned_duration_s=3600, certainty='committed',
        ))
        completion = SessionCompletion(
            session_uid=uid, activity_id=activity_id, status='unknown', match_method='explicit',
            version=1, input_version=1, updated_at=NOW,
        )
        session.add(completion)
        session.commit()
        assert completion.status == 'completed_as_planned'
        completion.status = 'unknown'
        session.commit()

    def persisted():
        with db() as session:
            completion = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == uid))
            rows = session.execute(select(MetricResult.__table__).where(
                MetricResult.subject_key.in_([str(activity_id), str(uid)]),
                MetricResult.metric_id.in_([intervals.METRIC_ID, planned_actual.METRIC_ID]),
                MetricResult.is_current.is_(True),
            )).mappings()
            return completion.status, completion.version, {row['metric_id']: dict(row) for row in rows}

    before_status, before_version, before_rows = persisted()
    assert set(before_rows) == {intervals.METRIC_ID, planned_actual.METRIC_ID}

    db.configure(info={'metrics_now': NOW + timedelta(days=1)})
    monkeypatch.setattr(cli, 'SessionLocal', db)
    args = ['app.cli', 'metrics-assess-session', '--session-uid', str(uid)]
    monkeypatch.setattr(sys, 'argv', args)
    assert cli.main() == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview['applied'] is False
    assert preview['session_uid'] == str(uid)
    assert preview['activity_id'] == str(activity_id)
    assert preview['before']['completion_status'] == before_status == 'unknown'
    assert preview['before']['completion_version'] == before_version
    assert preview['before']['interval'] == {
        'status': 'not_applicable',
        'reason_codes': ['NO_STRUCTURED_PLAN'],
        'quality_flags': [],
        'step_completion_ratio': None,
        'config_hash': before_rows[intervals.METRIC_ID]['config_hash'],
    }
    assert preview['after']['planned_actual']['overall_status'] == 'completed_as_planned'
    assert persisted() == (before_status, before_version, before_rows)

    monkeypatch.setattr(sys, 'argv', [*args, '--apply'])
    assert cli.main() == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied['applied'] is True
    assert applied['before'] == preview['before']
    assert applied['after'] == preview['after']
    status, version, rows = persisted()
    assert status == applied['after']['completion_status'] == 'completed_as_planned'
    assert version == applied['after']['completion_version'] == before_version + 1
    current_comparison = rows[planned_actual.METRIC_ID]
    assert applied['after']['planned_actual'] == {
        'status': current_comparison['status'],
        'overall_status': current_comparison['value']['overall_status'],
        'components': current_comparison['value']['components'],
        'reason_codes': current_comparison['reason_codes'],
        'config_hash': current_comparison['config_hash'],
    }
    assert current_comparison['id'] != before_rows[planned_actual.METRIC_ID]['id']
    with db() as session:
        previous = session.get(MetricResult, before_rows[planned_actual.METRIC_ID]['id'])
        assert previous is not None and previous.is_current is False

    assert cli.main() == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated['before'] == repeated['after']
    assert persisted() == (status, version, rows)


def test_reassess_unknown_session_uid(db, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'SessionLocal', db)
    monkeypatch.setattr(sys, 'argv', ['app.cli', 'metrics-assess-session', '--session-uid', str(uuid.uuid4())])

    assert cli.main() != 0
    captured = capsys.readouterr()
    assert captured.out == ''
    assert json.loads(captured.err) == {'error': 'completion_not_found'}
