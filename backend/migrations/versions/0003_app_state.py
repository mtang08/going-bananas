"""Initialize the singleton revision row before concurrent imports.
Revision ID: 0003_app_state
Revises: 0002_completion_unique
"""
from alembic import op

revision = '0003_app_state'
down_revision = '0002_completion_unique'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute('INSERT INTO app_state (id, data_revision) VALUES (1, 0) ON CONFLICT (id) DO NOTHING')

def downgrade() -> None:
    pass
