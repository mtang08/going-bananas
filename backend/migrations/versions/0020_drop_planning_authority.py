"""Drop planning_authority and the unused daily_guidance / legacy_undo_requests tables."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0020_drop_planning_authority'
down_revision = '0019_lap_intensity_end'
branch_labels = None
depends_on = None

DROPPED_TABLES = ('legacy_undo_requests', 'daily_guidance')


def upgrade():
    bind = op.get_bind()
    # Hold both locks through DROP so the emptiness checks cannot race with inserts.
    bind.execute(sa.text(f"LOCK TABLE {', '.join(DROPPED_TABLES)} IN ACCESS EXCLUSIVE MODE"))
    for table in DROPPED_TABLES:
        if bind.execute(sa.text(f'SELECT EXISTS (SELECT 1 FROM {table})')).scalar():
            raise RuntimeError('nonempty_table_drop_refused')
    op.drop_table('legacy_undo_requests')
    op.drop_table('daily_guidance')
    op.drop_constraint('ck_app_state_planning_authority', 'app_state', type_='check')
    op.drop_column('app_state', 'planning_authority')


def downgrade():
    op.add_column('app_state', sa.Column('planning_authority', sa.String(12), nullable=False, server_default='legacy'))
    op.execute("UPDATE app_state SET planning_authority = 'calendar' WHERE calendar_head_version > 0")
    op.create_check_constraint('ck_app_state_planning_authority', 'app_state', "planning_authority IN ('legacy','calendar')")
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
    op.create_table('legacy_undo_requests',
        sa.Column('idempotency_key', sa.String(100), primary_key=True),
        sa.Column('import_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('result', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_foreign_key('fk_legacy_undo_requests_import_id', 'legacy_undo_requests', 'legacy_import_runs', ['import_id'], ['id'])
