"""Editable pending proposals with immutable revision snapshots."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0016_proposal_revisions'
down_revision = '0015_coach_v2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('coach_proposals', sa.Column('revision', sa.Integer(), nullable=False, server_default='1'))
    op.create_table('coach_proposal_revisions',
        sa.Column('proposal_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('coach_proposals.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('revision', sa.Integer(), primary_key=True),
        sa.Column('saved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('changed_change_ids', postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column('changed_fields', postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column('request_hash', sa.String(64)),
    )
    op.execute("""INSERT INTO coach_proposal_revisions
        (proposal_id, revision, saved_at, reason, payload, changed_change_ids, changed_fields)
        SELECT id, 1, submitted_at, 'Original proposal', payload, '{}', '{}'
        FROM coach_proposals""")


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM coach_proposal_revisions)')).scalar():
        raise RuntimeError('restore_required_nonempty_mvp_schema')
    op.drop_table('coach_proposal_revisions')
    op.drop_column('coach_proposals', 'revision')
