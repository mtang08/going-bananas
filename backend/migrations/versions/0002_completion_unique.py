"""Require one actual completion per planned session.
Revision ID: 0002_completion_unique
Revises: 0001_initial
"""
from alembic import op

revision = '0002_completion_unique'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_unique_constraint('uq_completion_planned_session', 'completion_links', ['planned_session_id'])

def downgrade() -> None:
    op.drop_constraint('uq_completion_planned_session', 'completion_links', type_='unique')
