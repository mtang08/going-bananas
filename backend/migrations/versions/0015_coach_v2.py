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

revision = '0015_coach_v2'
down_revision = '0014_anchors_metrics_prompts'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('coach_snapshots',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('operation', sa.String(32), nullable=False),
        sa.Column('as_of', sa.Date(), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('calendar_version_number', sa.Integer(), nullable=False),
        sa.Column('block_version_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('data_revision', sa.Integer(), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('source_fingerprint', sa.String(64), nullable=False),
        sa.Column('source_versions', postgresql.JSONB(), nullable=False),
        sa.Column('kb_digest', sa.String(64), nullable=False),
        sa.Column('payload_sha256', sa.String(64), nullable=False),
        sa.Column('kb_package_version', sa.String(30), nullable=False),
        sa.Column('kb_routes', postgresql.JSONB(), nullable=False),
        sa.Column('approx_tokens', sa.Integer(), nullable=False),
        sa.CheckConstraint("operation IN ('proceed_or_modify_today','review_rolling_plan','review_training_block','select_quality_session','recalibrate_intensity','handle_goal_or_race_change')", name='ck_coach_snapshots_operation'),
    )
    op.create_foreign_key('fk_coach_snapshots_block_version_id', 'coach_snapshots', 'block_versions', ['block_version_id'], ['id'])
    op.create_table('coach_proposals',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('operation', sa.String(32), nullable=False),
        sa.Column('snapshot_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('base_calendar_version', sa.Integer(), nullable=False),
        sa.Column('base_block_version_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('confidence', postgresql.JSONB(), nullable=False),
        sa.Column('evidence_ids', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('policy_ids', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('recipe_ids', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('follow_up', sa.Text(), nullable=True),
        sa.Column('escalation', sa.String(32), nullable=True),
        sa.Column('block_change', postgresql.JSONB(), nullable=True),
        sa.Column('anchor_changes', postgresql.JSONB(), nullable=True),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('decision_idempotency_key', sa.String(100), nullable=True),
        sa.Column('decision_hash', sa.String(64), nullable=True),
        sa.Column('decision_result', postgresql.JSONB(), nullable=True),
        sa.Column('validation_errors', postgresql.JSONB(), nullable=True),
        sa.Column('skill_version', sa.String(20), nullable=False),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.CheckConstraint("operation IN ('proceed_or_modify_today','review_rolling_plan','review_training_block','select_quality_session','recalibrate_intensity','handle_goal_or_race_change')", name='ck_coach_proposals_operation'),
        sa.UniqueConstraint('decision_idempotency_key'),
        sa.UniqueConstraint('input_hash'),
        sa.CheckConstraint("status IN ('pending','accepted','partially_accepted','rejected','stale','invalid')", name='ck_coach_proposals_status'),
        sa.CheckConstraint("escalation IN ('proceed_or_modify_today','review_rolling_plan','review_training_block','select_quality_session','recalibrate_intensity','handle_goal_or_race_change')", name='ck_coach_proposals_escalation'),
    )
    op.create_foreign_key('fk_coach_proposals_snapshot_id', 'coach_proposals', 'coach_snapshots', ['snapshot_id'], ['id'])
    op.create_foreign_key('fk_coach_proposals_base_block_version_id', 'coach_proposals', 'block_versions', ['base_block_version_id'], ['id'])
    op.create_table('coach_proposal_changes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('proposal_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('change_id', sa.String(12), nullable=False),
        sa.Column('op', sa.String(10), nullable=False),
        sa.Column('session_uid', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('before', postgresql.JSONB(), nullable=True),
        sa.Column('after', postgresql.JSONB(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('decision', sa.String(10), nullable=False),
        sa.CheckConstraint("decision IN ('pending','accepted','rejected')", name='ck_coach_proposal_changes_decision'),
        sa.UniqueConstraint('proposal_id', 'change_id'),
        sa.CheckConstraint("op IN ('add','modify','move','delete')", name='ck_coach_proposal_changes_op'),
    )
    op.create_foreign_key('fk_coach_proposal_changes_proposal_id', 'coach_proposal_changes', 'coach_proposals', ['proposal_id'], ['id'])
    op.create_table('coach_decision_keys',
        sa.Column('idempotency_key', sa.String(100), primary_key=True),
        sa.Column('proposal_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('decision_hash', sa.String(64), nullable=False),
        sa.Column('result', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_foreign_key('fk_coach_decision_keys_proposal_id', 'coach_decision_keys', 'coach_proposals', ['proposal_id'], ['id'])
    op.create_table('daily_guidance',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('local_date', sa.Date(), nullable=False),
        sa.Column('checkin_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('engine', sa.String(20), nullable=False),
        sa.Column('decision', sa.String(24), nullable=False),
        sa.Column('session_uid', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('missing_inputs', postgresql.ARRAY(sa.String(40)), nullable=False, server_default='{}'),
        sa.Column('coach_review_suggested', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('trigger_codes', postgresql.ARRAY(sa.String(40)), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.UniqueConstraint('local_date', 'input_hash'),
        sa.CheckConstraint("decision IN ('proceed','modify','reschedule','rest','seek_clinical_input')", name='ck_daily_guidance_decision'),
    )
    op.create_foreign_key('fk_daily_guidance_checkin_id', 'daily_guidance', 'checkins_v2', ['checkin_id'], ['id'])
    op.create_foreign_key('fk_calendar_versions_proposal_id', 'calendar_versions', 'coach_proposals', ['proposal_id'], ['id'])
    op.create_foreign_key('fk_block_versions_proposal_id', 'block_versions', 'coach_proposals', ['proposal_id'], ['id'])
    op.create_foreign_key('fk_block_decisions_proposal_id', 'block_decisions', 'coach_proposals', ['proposal_id'], ['id'])
    op.create_foreign_key('fk_intensity_anchors_proposal_id', 'intensity_anchors', 'coach_proposals', ['proposal_id'], ['id'])


def downgrade():
    _guard(['coach_snapshots', 'coach_proposals', 'coach_proposal_changes', 'coach_decision_keys', 'daily_guidance'])
    op.drop_constraint('fk_calendar_versions_proposal_id', 'calendar_versions', type_='foreignkey')
    op.drop_constraint('fk_block_versions_proposal_id', 'block_versions', type_='foreignkey')
    op.drop_constraint('fk_block_decisions_proposal_id', 'block_decisions', type_='foreignkey')
    op.drop_constraint('fk_intensity_anchors_proposal_id', 'intensity_anchors', type_='foreignkey')
    op.drop_table('daily_guidance')
    op.drop_table('coach_decision_keys')
    op.drop_table('coach_proposal_changes')
    op.drop_table('coach_proposals')
    op.drop_table('coach_snapshots')
