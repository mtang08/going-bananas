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

revision = '0010_ingest_fit'
down_revision = '0009_agent_plan'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('activities', sa.Column('timer_s', sa.Float()))
    op.add_column('activities', sa.Column('end_at', sa.DateTime(timezone=True)))
    op.add_column('activities', sa.Column('fit_file_id', postgresql.UUID(as_uuid=True)))
    op.add_column('activities', sa.Column('workout_rpe', sa.Numeric(3, 1, asdecimal=False)))
    op.add_column('activities', sa.Column('workout_feel', sa.SmallInteger()))
    op.add_column('activities', sa.Column('fit_status', sa.String(20), nullable=False, server_default='not_fetched'))
    op.create_check_constraint('ck_activities_fit_status', 'activities', "fit_status IN ('not_fetched','fetched','decoded','unavailable','decode_error')")
    op.create_check_constraint('ck_activities_workout_rpe', 'activities', 'workout_rpe IS NULL OR (workout_rpe >= 0 AND workout_rpe <= 10)')
    op.create_table('fit_files',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('raw_object_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('activity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('zip_sha256', sa.String(64), nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.String(100), nullable=True),
        sa.Column('fit_sha256', sa.String(64), nullable=True),
        sa.Column('profile_version', sa.String(20), nullable=True),
        sa.Column('sdk_version', sa.String(20), nullable=True),
        sa.Column('decoded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decode_error', sa.String(100), nullable=True),
        sa.Column('message_inventory', postgresql.JSONB(), nullable=False),
        sa.Column('device', postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint('raw_object_id'),
        sa.UniqueConstraint('activity_id'),
    )
    op.create_foreign_key('fk_fit_files_raw_object_id', 'fit_files', 'raw_objects', ['raw_object_id'], ['id'])
    op.create_foreign_key('fk_fit_files_activity_id', 'fit_files', 'activities', ['activity_id'], ['id'])
    op.create_table('activity_laps',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('activity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('lap_index', sa.Integer(), nullable=False),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('timer_s', sa.Float(), nullable=True),
        sa.Column('elapsed_s', sa.Float(), nullable=True),
        sa.Column('distance_m', sa.Float(), nullable=True),
        sa.Column('avg_speed_mps', sa.Float(), nullable=True),
        sa.Column('avg_hr_bpm', sa.Float(), nullable=True),
        sa.Column('max_hr_bpm', sa.Float(), nullable=True),
        sa.Column('lap_trigger', sa.String(30), nullable=True),
        sa.Column('wkt_step_index', sa.Integer(), nullable=True),
        sa.UniqueConstraint('activity_id', 'lap_index'),
    )
    op.create_foreign_key('fk_activity_laps_activity_id', 'activity_laps', 'activities', ['activity_id'], ['id'])
    op.create_table('activity_workout_steps',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('activity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('message_index', sa.Integer(), nullable=False),
        sa.Column('step_name', sa.String(100), nullable=True),
        sa.Column('intensity', sa.String(20), nullable=True),
        sa.Column('duration_type', sa.String(30), nullable=False),
        sa.Column('duration_value', sa.Float(), nullable=True),
        sa.Column('target_type', sa.String(30), nullable=True),
        sa.Column('target_low', sa.Float(), nullable=True),
        sa.Column('target_high', sa.Float(), nullable=True),
        sa.Column('repeat_from', sa.Integer(), nullable=True),
        sa.Column('repeat_count', sa.Integer(), nullable=True),
        sa.UniqueConstraint('activity_id', 'message_index'),
        sa.CheckConstraint("intensity IN ('active','rest','warmup','cooldown','recovery','interval','other')", name='ck_activity_workout_steps_intensity'),
    )
    op.create_foreign_key('fk_activity_workout_steps_activity_id', 'activity_workout_steps', 'activities', ['activity_id'], ['id'])
    op.create_table('activity_streams',
        sa.Column('activity_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('t_s', postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column('hr_bpm', postgresql.ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column('speed_mps', postgresql.ARRAY(sa.REAL()), nullable=False),
        sa.Column('distance_m', postgresql.ARRAY(sa.REAL()), nullable=False),
        sa.Column('altitude_m', postgresql.ARRAY(sa.REAL()), nullable=False),
        sa.Column('cadence', postgresql.ARRAY(sa.REAL()), nullable=False),
        sa.Column('timer_on', postgresql.ARRAY(sa.Integer(), dimensions=2), nullable=False),
        sa.Column('sample_count', sa.Integer(), nullable=False),
        sa.Column('max_gap_s', sa.Integer(), nullable=False),
        sa.Column('quality_flags', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
    )
    op.create_foreign_key('fk_activity_streams_activity_id', 'activity_streams', 'activities', ['activity_id'], ['id'])
    op.create_foreign_key('fk_activities_fit_file_id', 'activities', 'fit_files', ['fit_file_id'], ['id'])


def downgrade():
    _guard(['fit_files', 'activity_laps', 'activity_workout_steps', 'activity_streams'], "SELECT EXISTS (SELECT 1 FROM activities WHERE timer_s IS NOT NULL OR end_at IS NOT NULL OR fit_file_id IS NOT NULL OR workout_rpe IS NOT NULL OR workout_feel IS NOT NULL OR fit_status <> 'not_fetched')")
    op.drop_constraint('fk_activities_fit_file_id', 'activities', type_='foreignkey')
    op.drop_table('activity_streams')
    op.drop_table('activity_workout_steps')
    op.drop_table('activity_laps')
    op.drop_table('fit_files')
    op.drop_constraint('ck_activities_workout_rpe', 'activities', type_='check')
    op.drop_constraint('ck_activities_fit_status', 'activities', type_='check')
    for name in ('fit_status','workout_feel','workout_rpe','fit_file_id','end_at','timer_s'):
        op.drop_column('activities', name)
