"""Add confirmed alternating strength schedule to versioned profiles.

Revision ID: 0008_strength_schedule
Revises: 0007_coaching_selection
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0008_strength_schedule'
down_revision = '0007_coaching_selection'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('profile_versions', sa.Column('strength_schedule_mode', sa.String(16), server_default='weekly', nullable=False))
    op.add_column('profile_versions', sa.Column('strength_week_a_start', sa.Date(), nullable=True))
    op.add_column('profile_versions', sa.Column('strength_week_a_days', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('profile_versions', sa.Column('strength_week_b_days', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('profile_versions', sa.Column('mobility_week_a_days', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('profile_versions', sa.Column('mobility_week_b_days', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('profile_versions', sa.Column('mobility_optional_days', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))


def downgrade() -> None:
    op.drop_column('profile_versions', 'mobility_optional_days')
    op.drop_column('profile_versions', 'mobility_week_b_days')
    op.drop_column('profile_versions', 'mobility_week_a_days')
    op.drop_column('profile_versions', 'strength_week_b_days')
    op.drop_column('profile_versions', 'strength_week_a_days')
    op.drop_column('profile_versions', 'strength_week_a_start')
    op.drop_column('profile_versions', 'strength_schedule_mode')
