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

revision = '0014_anchors_metrics_prompts'
down_revision = '0013_blocks_goals'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('intensity_anchors',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('anchor_key', sa.String(40), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('value_low', sa.Float(), nullable=False),
        sa.Column('value_high', sa.Float(), nullable=True),
        sa.Column('unit', sa.String(8), nullable=False),
        sa.Column('protocol', sa.String(24), nullable=False),
        sa.Column('confidence', sa.String(12), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('calibrated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_from', sa.Date(), nullable=False),
        sa.Column('review_after', sa.Date(), nullable=False),
        sa.Column('source_activity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('source_event_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('proposal_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('conditions', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('supersedes_key', sa.String(40), nullable=True),
        sa.CheckConstraint('value_high IS NULL OR value_low <= value_high', name='ck_intensity_anchors_value_high'),
        sa.CheckConstraint("kind IN ('hr_aerobic_upper','hr_threshold_lower','speed_aerobic_upper','speed_threshold_lower','performance_5k','performance_1mile','performance_3min','performance_20_30min')", name='ck_intensity_anchors_kind'),
        sa.CheckConstraint("unit IN ('bpm','mps','s','m')", name='ck_intensity_anchors_unit'),
        sa.CheckConstraint("protocol IN ('race_5k','time_trial_5k','time_trial_1mile','time_trial_3min','time_trial_20_30min','workout_derived','lab_test','manual')", name='ck_intensity_anchors_protocol'),
        sa.CheckConstraint("confidence IN ('high','moderate','low','insufficient')", name='ck_intensity_anchors_confidence'),
        sa.CheckConstraint("status IN ('provisional','active','expired','invalid')", name='ck_intensity_anchors_status'),
        sa.UniqueConstraint('anchor_key'),
        sa.CheckConstraint("(kind LIKE 'hr_%' AND unit='bpm') OR (kind LIKE 'speed_%' AND unit='mps') OR (kind IN ('performance_5k','performance_1mile') AND unit='s') OR (kind='performance_3min' AND unit='m') OR (kind='performance_20_30min' AND unit='mps')", name='ck_intensity_anchors_unit_kind'),
    )
    op.create_foreign_key('fk_intensity_anchors_source_activity_id', 'intensity_anchors', 'activities', ['source_activity_id'], ['id'])
    op.create_foreign_key('fk_intensity_anchors_source_event_id', 'intensity_anchors', 'events', ['source_event_id'], ['id'])
    op.create_table('metric_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('metric_id', sa.String(60), nullable=False),
        sa.Column('method_version', sa.String(40), nullable=False),
        sa.Column('config', postgresql.JSONB(), nullable=False),
        sa.Column('config_hash', sa.String(64), nullable=False),
        sa.UniqueConstraint('metric_id', 'method_version', 'config_hash'),
    )
    op.create_table('metric_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('metric_id', sa.String(60), nullable=False),
        sa.Column('method_version', sa.String(40), nullable=False),
        sa.Column('subject_type', sa.String(12), nullable=False),
        sa.Column('subject_key', sa.String(120), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('window_label', sa.String(40), nullable=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('quality_status', sa.String(14), nullable=True),
        sa.Column('value', postgresql.JSONB(), nullable=True),
        sa.Column('unit', sa.String(16), nullable=True),
        sa.Column('reason_codes', postgresql.ARRAY(sa.String(40)), nullable=False, server_default='{}'),
        sa.Column('quality_flags', postgresql.ARRAY(sa.String(40)), nullable=False, server_default='{}'),
        sa.Column('source_refs', postgresql.JSONB(), nullable=False),
        sa.Column('anchor_keys', postgresql.ARRAY(sa.String(40)), nullable=False, server_default='{}'),
        sa.Column('config_hash', sa.String(64), nullable=False),
        sa.Column('anchor_set_hash', sa.String(64), nullable=True),
        sa.Column('calculated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('dependency_hash', sa.String(64), nullable=False),
        sa.Column('timezone', sa.String(100), nullable=False),
        sa.Column('is_current', sa.Boolean(), nullable=False, server_default='true'),
        sa.CheckConstraint("status IN ('available','partial','missing','invalid','not_applicable','not_assessable')", name='ck_metric_results_status'),
        sa.CheckConstraint("quality_status IN ('good','limited','insufficient')", name='ck_metric_results_quality_status'),
        sa.CheckConstraint("subject_type IN ('activity','session','window','night','report')", name='ck_metric_results_subject_type'),
    )
    op.create_table('prompts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('activity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('session_uid', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('opens_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closes_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(10), nullable=False),
        sa.CheckConstraint("status IN ('open','answered','dismissed','expired')", name='ck_prompts_status'),
        sa.CheckConstraint("kind IN ('rpe','delayed_symptom','unmatched_session','missing_activity')", name='ck_prompts_kind'),
    )
    op.create_foreign_key('fk_prompts_activity_id', 'prompts', 'activities', ['activity_id'], ['id'])
    op.create_foreign_key('fk_checkins_v2_prompt_id', 'checkins_v2', 'prompts', ['prompt_id'], ['id'])
    op.create_index('uq_prompts_kind_activity_session', 'prompts', ['kind','activity_id','session_uid'], unique=True, postgresql_nulls_not_distinct=True)
    op.create_index('uq_metric_results_identity', 'metric_results', ['metric_id','method_version','subject_key','config_hash',sa.text("coalesce(anchor_set_hash, '')"),'dependency_hash'], unique=True)
    op.create_index('uq_metric_results_current', 'metric_results', ['metric_id','method_version','subject_key'], unique=True, postgresql_where=sa.text('is_current'))


def downgrade():
    _guard(['intensity_anchors', 'metric_configs', 'metric_results', 'prompts'])
    op.drop_constraint('fk_checkins_v2_prompt_id', 'checkins_v2', type_='foreignkey')
    op.drop_index('uq_prompts_kind_activity_session')
    op.drop_index('uq_metric_results_identity')
    op.drop_index('uq_metric_results_current')
    op.drop_table('prompts')
    op.drop_table('metric_results')
    op.drop_table('metric_configs')
    op.drop_table('intensity_anchors')
