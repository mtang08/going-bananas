"""Synthetic legacy facts spanning accepted plans and a later agent revision."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from app.agent_models import CoachPlanRevision
from app.models import Activity, Checkin, CheckinRevision, CompletionLink, PlannedSession, PlanVersion, ProfileVersion


def seed_legacy(session, today: date) -> dict:
    stamp = datetime.combine(today - timedelta(days=1), datetime.min.time(), UTC)
    profile = ProfileVersion(version=1, effective_at=stamp, timezone='America/New_York',
        anchor_confirmed=True, cycle_anchor=today - timedelta(days=14),
        strength_days_confirmed=True, scheduled_strength_days=[1, 5],
        strength_schedule_mode='alternating', strength_week_a_start=today - timedelta(days=14),
        strength_week_a_days=[1], strength_week_b_days=[5],
        mobility_week_a_days=[3], mobility_week_b_days=[4], mobility_optional_days=[0],
        facts={'synthetic': True}, preferences={}, unknowns=[])
    old = PlanVersion(status='accepted', start_date=today - timedelta(days=7),
        end_date=today + timedelta(days=6), profile_version=1)
    newer = PlanVersion(status='accepted', start_date=today,
        end_date=today + timedelta(days=13), profile_version=1)
    session.add_all([profile, old, newer])
    session.flush()
    old_active = PlannedSession(plan_id=old.id, date=today + timedelta(days=1), kind='run',
        target={'intent': 'Easy run', 'duration_minutes': 30, 'distance_km': 5,
                'steps': ['Easy warmup', 'Steady run'], 'locked': True})
    old_linked = PlannedSession(plan_id=old.id, date=today - timedelta(days=2), kind='run',
        target={'intent': 'Completed run', 'duration_minutes': 25})
    new_active = PlannedSession(plan_id=newer.id, date=today + timedelta(days=2), kind='strength',
        target={'intent': 'Strength A', 'prescription': 'Use existing routine'})
    discarded = PlannedSession(plan_id=old.id, date=today + timedelta(days=3), kind='mobility',
        target={'intent': 'Superseded mobility'})
    activity = Activity(start_at=stamp, original_start=stamp.isoformat(),
        local_date=today - timedelta(days=2), sport='running', timer_s=1500,
        distance_m=4000, resolution_state='resolved')
    checkin = Checkin(idempotency_key='synthetic-legacy', observed_at=stamp,
        symptoms='severe', gait='unaffected', feeling='tired', note='Literal categorical fact')
    session.add_all([old_active, old_linked, new_active, discarded, activity, checkin])
    session.flush()
    link = CompletionLink(planned_session_id=old_linked.id, activity_id=activity.id, confirmed_at=stamp)
    revision = CheckinRevision(checkin_id=checkin.id, version=1,
        payload={'symptoms': 'severe', 'gait': 'unaffected'})
    changed = CoachPlanRevision(plan_id=newer.id, workflow='daily', as_of=today,
        idempotency_key='synthetic-change', evidence_hash='a' * 64,
        summary='Synthetic change', rationale='Synthetic fixture',
        payload={'active_session_ids': [str(old_active.id), str(new_active.id)],
                 'diff': [{'kind': 'run'}], 'before': [], 'after': []}, inputs={})
    session.add_all([link, revision, changed])
    session.flush()
    review = CoachPlanRevision(parent_revision_id=changed.id, plan_id=newer.id,
        workflow='daily', as_of=today, idempotency_key='synthetic-review',
        evidence_hash='b' * 64, summary='No change', rationale='Synthetic review',
        payload={'active_session_ids': [str(old_active.id), str(new_active.id)],
                 'diff': []}, inputs={})
    session.add(review)
    session.flush()
    return {'current': {old_active.id, new_active.id}, 'linked': old_linked.id,
            'discarded': discarded.id, 'activity': activity.id, 'checkin': checkin.id}


def seed_at_0009(connection, today: date) -> dict:
    """Insert actual 0009 columns before additive migrations add modern fields."""
    stamp = datetime.combine(today - timedelta(days=1), datetime.min.time(), UTC)
    profile, old, newer, old_active, old_linked, new_active, activity, checkin, link, revision = (
        uuid.uuid4() for _ in range(10))
    connection.execute(text("""INSERT INTO profile_versions
        (id,version,effective_at,timezone,cycle_anchor,anchor_confirmed,strength_days_confirmed,
         scheduled_strength_days,strength_schedule_mode,strength_week_a_start,strength_week_a_days,
         strength_week_b_days,mobility_week_a_days,mobility_week_b_days,mobility_optional_days,
         facts,preferences,unknowns)
        VALUES (:id,1,:stamp,'America/New_York',:anchor,true,true,'[]'::jsonb,'alternating',
        :anchor,'[1]'::jsonb,'[5]'::jsonb,'[3]'::jsonb,'[4]'::jsonb,'[0]'::jsonb,
        '{}'::jsonb,'{}'::jsonb,'[]'::jsonb)"""),
        {'id': profile, 'stamp': stamp, 'anchor': today - timedelta(days=14)})
    for uid, start, end in ((old, today-timedelta(days=7), today+timedelta(days=6)),
                            (newer, today, today+timedelta(days=13))):
        connection.execute(text("""INSERT INTO plan_versions
            (id,version,status,start_date,end_date,profile_version)
            VALUES (:id,1,'accepted',:start,:end,1)"""),
            {'id': uid, 'start': start, 'end': end})
    for uid, plan, day, kind, target in (
        (old_active, old, today+timedelta(days=1), 'run',
         {'intent': 'Easy run', 'duration_minutes': 30, 'steps': ['Easy warmup']}),
        (old_linked, old, today-timedelta(days=2), 'run', {'intent': 'Completed run'}),
        (new_active, newer, today+timedelta(days=2), 'strength', {'intent': 'Strength A'})):
        connection.execute(text("""INSERT INTO planned_sessions (id,plan_id,date,kind,target)
            VALUES (:id,:plan,:day,:kind,CAST(:target AS jsonb))"""),
            {'id': uid, 'plan': plan, 'day': day, 'kind': kind,
             'target': json.dumps(target)})
    connection.execute(text("""INSERT INTO activities
        (id,start_at,original_start,local_date,sport,canonical_revision,resolution_state,field_provenance)
        VALUES (:id,:stamp,:original,:day,'running',1,'resolved','{}'::jsonb)"""),
        {'id': activity, 'stamp': stamp, 'original': stamp.isoformat(),
         'day': today-timedelta(days=2)})
    connection.execute(text("""INSERT INTO completion_links
        (id,planned_session_id,activity_id,confirmed_at) VALUES (:id,:planned,:activity,:stamp)"""),
        {'id': link, 'planned': old_linked, 'activity': activity, 'stamp': stamp})
    connection.execute(text("""INSERT INTO checkins
        (id,idempotency_key,version,observed_at,symptoms,gait,feeling,note)
        VALUES (:id,'legacy-0009',1,:stamp,'severe','unaffected','tired','literal')"""),
        {'id': checkin, 'stamp': stamp})
    connection.execute(text("""INSERT INTO checkin_revisions
        (id,checkin_id,version,payload) VALUES (:id,:checkin,1,'{"symptoms":"severe"}'::jsonb)"""),
        {'id': revision, 'checkin': checkin})
    connection.execute(text("""INSERT INTO coach_plan_revisions
        (id,plan_id,workflow,as_of,idempotency_key,evidence_hash,summary,rationale,payload,inputs)
        VALUES (:id,:plan,'daily',:day,'legacy-0009-revision',:hash,'Synthetic','Synthetic',
        CAST(:payload AS jsonb),'{}'::jsonb)"""),
        {'id': uuid.uuid4(), 'plan': newer, 'day': today, 'hash': 'c'*64,
         'payload': json.dumps({'active_session_ids': [str(old_active), str(new_active)], 'diff': []})})
    return {'current': {old_active, new_active}, 'linked': old_linked}
