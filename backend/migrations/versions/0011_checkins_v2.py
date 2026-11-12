from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


def _guard(names, extra=None):
    bind = op.get_bind()
    for name in names:
        if bind.execute(sa.text(f'SELECT EXISTS (SELECT 1 FROM {name})')).scalar():
            raise RuntimeError('restore_required_nonempty_mvp_schema')
    if extra is not None and bind.execute(sa.text(extra)).scalar():
        raise RuntimeError('restore_required_nonempty_mvp_schema')

revision = '0011_checkins_v2'
down_revision = '0010_ingest_fit'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('checkins_v2',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('idempotency_key', sa.String(100), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('fatigue', sa.Numeric(3, 1, asdecimal=False), nullable=True),
        sa.Column('illness', sa.String(10), nullable=True),
        sa.Column('gait_change', sa.String(10), nullable=True),
        sa.Column('context_tags', postgresql.ARRAY(sa.String(30)), nullable=False, server_default='{}'),
        sa.Column('activity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('prompt_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('schema_version', sa.SmallInteger(), nullable=False, server_default='2'),
        sa.CheckConstraint('fatigue IS NULL OR (fatigue >= 0 AND fatigue <= 10)', name='ck_checkins_v2_fatigue'),
        sa.UniqueConstraint('idempotency_key'),
        sa.CheckConstraint("illness IN ('none','possible','present')", name='ck_checkins_v2_illness'),
        sa.CheckConstraint("kind IN ('exception','post_run','delayed_followup')", name='ck_checkins_v2_kind'),
        sa.CheckConstraint("context_tags <@ ARRAY['heat','travel','poor_sleep','unusual_surface','equipment']::varchar[]", name='ck_checkins_v2_context_tags'),
        sa.CheckConstraint("gait_change IN ('yes','no','unsure')", name='ck_checkins_v2_gait_change'),
    )
    op.create_foreign_key('fk_checkins_v2_activity_id', 'checkins_v2', 'activities', ['activity_id'], ['id'])
    op.create_table('checkin_v2_revisions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('checkin_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('checkin_id', 'version'),
    )
    op.create_foreign_key('fk_checkin_v2_revisions_checkin_id', 'checkin_v2_revisions', 'checkins_v2', ['checkin_id'], ['id'])
    op.create_table('symptom_reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('checkin_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('site', sa.String(60), nullable=False),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('severity', sa.Numeric(3, 1, asdecimal=False), nullable=False),
        sa.Column('timing', sa.String(20), nullable=False),
        sa.CheckConstraint("side IN ('left','right','both','na')", name='ck_symptom_reports_side'),
        sa.CheckConstraint('severity IS NULL OR (severity >= 0 AND severity <= 10)', name='ck_symptom_reports_severity'),
        sa.CheckConstraint("timing IN ('during','immediately_after','next_morning','hours_24_48','later','unknown')", name='ck_symptom_reports_timing'),
    )
    op.create_foreign_key('fk_symptom_reports_checkin_id', 'symptom_reports', 'checkins_v2', ['checkin_id'], ['id'])
    op.create_table('session_rpe',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('activity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('strong_workout_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('manual_session_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('rpe', sa.Numeric(3, 1, asdecimal=False), nullable=False),
        sa.Column('source', sa.String(12), nullable=False),
        sa.Column('collected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('collection_delay_s', sa.Integer(), nullable=True),
        sa.CheckConstraint("source IN ('manual','garmin_fit')", name='ck_session_rpe_source'),
        sa.UniqueConstraint('manual_session_id', 'source'),
        sa.UniqueConstraint('strong_workout_id', 'source'),
        sa.UniqueConstraint('activity_id', 'source'),
        sa.CheckConstraint('rpe IS NULL OR (rpe >= 0 AND rpe <= 10)', name='ck_session_rpe_rpe'),
        sa.CheckConstraint('num_nonnulls(activity_id,strong_workout_id,manual_session_id) = 1', name='ck_session_rpe_subject'),
    )
    op.create_foreign_key('fk_session_rpe_activity_id', 'session_rpe', 'activities', ['activity_id'], ['id'])
    op.create_foreign_key('fk_session_rpe_strong_workout_id', 'session_rpe', 'strong_workouts', ['strong_workout_id'], ['id'])
    op.create_foreign_key('fk_session_rpe_manual_session_id', 'session_rpe', 'manual_sessions', ['manual_session_id'], ['id'])


def downgrade():
    _guard(['checkins_v2', 'checkin_v2_revisions', 'symptom_reports', 'session_rpe'])
    op.drop_table('session_rpe')
    op.drop_table('symptom_reports')
    op.drop_table('checkin_v2_revisions')
    op.drop_table('checkins_v2')
