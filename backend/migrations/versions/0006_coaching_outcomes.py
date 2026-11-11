"""Append-only recommendation outcome events.

Revision ID: 0006_coaching_outcomes
Revises: 0005_coaching
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0006_coaching_outcomes'
down_revision = '0005_coaching'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('coach_outcome_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('recommendation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('coach_recommendations.id'), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('effect', sa.String(24)),
        sa.Column('note', sa.Text()),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_coach_outcome_events_recommendation_id', 'coach_outcome_events', ['recommendation_id'])
    op.execute(sa.text("""
        INSERT INTO coach_outcome_events (id, recommendation_id, status, effect, note, recorded_at)
        SELECT id, recommendation_id, status, effect, note, recorded_at
        FROM coach_outcomes
    """))


def downgrade() -> None:
    op.drop_index('ix_coach_outcome_events_recommendation_id', table_name='coach_outcome_events')
    op.drop_table('coach_outcome_events')
