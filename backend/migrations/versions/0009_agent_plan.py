"""Persist external coach revisions without modifying source observations."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0009_agent_plan'
down_revision = '0008_strength_schedule'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('coach_plan_revisions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('parent_revision_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('coach_plan_revisions.id')),
        sa.Column('plan_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('plan_versions.id')),
        sa.Column('workflow', sa.String(12), nullable=False),
        sa.Column('as_of', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('idempotency_key', sa.String(100), nullable=False),
        sa.Column('evidence_hash', sa.String(64), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('inputs', postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint('idempotency_key'),
        sa.UniqueConstraint('workflow', 'as_of', 'evidence_hash'))


def downgrade():
    op.drop_table('coach_plan_revisions')
