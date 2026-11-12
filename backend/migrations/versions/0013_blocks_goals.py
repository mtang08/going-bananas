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

revision = '0013_blocks_goals'
down_revision = '0012_calendar'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('blocks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('block_uid', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('block_uid'),
    )
    op.create_table('block_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('block_uid', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('objective', sa.Text(), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('maintained_qualities', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('non_goals', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('eligible_recipe_ids', postgresql.ARRAY(sa.String(10)), nullable=False, server_default='{}'),
        sa.Column('progression_dimension', sa.String(40), nullable=False),
        sa.Column('constraints', postgresql.JSONB(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('review_date', sa.Date(), nullable=False),
        sa.Column('completion_indicators', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('early_review_triggers', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('objective_status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('proposal_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint('block_uid', 'version'),
        sa.CheckConstraint("progression_dimension IN ('duration','frequency','long_run','quality_volume','intensity','none')", name='ck_block_versions_progression_dimension'),
        sa.CheckConstraint("objective_status IN ('unresolved','partially_achieved','achieved','not_achieved')", name='ck_block_versions_objective_status'),
        sa.CheckConstraint("status IN ('draft','active','consolidating','completed','replaced','ended')", name='ck_block_versions_status'),
    )
    op.create_foreign_key('fk_block_versions_block_uid', 'block_versions', 'blocks', ['block_uid'], ['block_uid'])
    op.create_table('block_decisions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('block_uid', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('decision', sa.String(12), nullable=False),
        sa.Column('from_version', sa.Integer(), nullable=True),
        sa.Column('to_version', sa.Integer(), nullable=True),
        sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('evidence_ids', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('policy_ids', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('confidence', sa.String(10), nullable=False),
        sa.Column('proposal_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("decision IN ('start','continue','extend','consolidate','transition','replace','end')", name='ck_block_decisions_decision'),
    )
    op.create_foreign_key('fk_block_decisions_block_uid', 'block_decisions', 'blocks', ['block_uid'], ['block_uid'])
    op.create_table('goals',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('horizon', sa.String(12), nullable=False),
        sa.Column('priority', sa.SmallInteger(), nullable=False),
        sa.Column('status', sa.String(10), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.CheckConstraint("horizon IN ('3_6_months','season','long_term')", name='ck_goals_horizon'),
        sa.CheckConstraint("status IN ('active','paused','done','dropped')", name='ck_goals_status'),
    )
    op.create_table('events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('distance_m', sa.Integer(), nullable=True),
        sa.Column('priority', sa.String(20), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('result_s', sa.Integer(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.CheckConstraint("priority IN ('target','supported_exposure','benchmark','optional')", name='ck_events_priority'),
        sa.CheckConstraint("status IN ('planned','registered','completed','cancelled')", name='ck_events_status'),
    )
    op.create_table('strength_routine_slots',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('label', sa.String(40), nullable=False),
        sa.Column('default_weekday', sa.SmallInteger(), nullable=False),
        sa.Column('lower_body_cost', sa.String(10), nullable=False),
        sa.Column('typical_duration_s', sa.Integer(), nullable=True),
        sa.Column('main_lower_body_lifts', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.CheckConstraint("lower_body_cost IN ('low','moderate','high')", name='ck_strength_routine_slots_lower_body_cost'),
        sa.CheckConstraint('default_weekday BETWEEN 0 AND 6', name='ck_strength_routine_slots_default_weekday'),
    )
    op.create_foreign_key('fk_calendar_versions_block_version_id', 'calendar_versions', 'block_versions', ['block_version_id'], ['id'])
    op.create_foreign_key('fk_calendar_session_revisions_strength_slot_id', 'calendar_session_revisions', 'strength_routine_slots', ['strength_slot_id'], ['id'])


def downgrade():
    _guard(['blocks', 'block_versions', 'block_decisions', 'goals', 'events', 'strength_routine_slots'])
    op.drop_constraint('fk_calendar_versions_block_version_id', 'calendar_versions', type_='foreignkey')
    op.drop_constraint('fk_calendar_session_revisions_strength_slot_id', 'calendar_session_revisions', type_='foreignkey')
    op.drop_table('strength_routine_slots')
    op.drop_table('events')
    op.drop_table('goals')
    op.drop_table('block_decisions')
    op.drop_table('block_versions')
    op.drop_table('blocks')
