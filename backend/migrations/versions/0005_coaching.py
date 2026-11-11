"""Persist local coaching decisions and explicit user outcomes.

Revision ID: 0005_coaching
Revises: 0004_strong
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0005_coaching'
down_revision = '0004_strong'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('coach_recommendations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('kind', sa.String(12), nullable=False),
        sa.Column('as_of', sa.Date(), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('engine', sa.String(40), nullable=False),
        sa.Column('knowledge_version', sa.String(80), nullable=False),
        sa.Column('data_revision', sa.Integer(), nullable=False),
        sa.Column('profile_version', sa.Integer(), nullable=False),
        sa.Column('plan_version', sa.Integer(), nullable=False),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.Column('inputs', postgresql.JSONB(), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint('kind', 'as_of', 'input_hash'))
    op.create_index('ix_coach_recommendations_as_of', 'coach_recommendations', ['as_of'])
    op.create_table('coach_outcomes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('recommendation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('coach_recommendations.id'), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('effect', sa.String(24)),
        sa.Column('note', sa.Text()),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('recommendation_id'))


def downgrade() -> None:
    op.drop_table('coach_outcomes')
    op.drop_index('ix_coach_recommendations_as_of', table_name='coach_recommendations')
    op.drop_table('coach_recommendations')
