"""Track which cached recommendation was explicitly selected most recently.

Revision ID: 0007_coaching_selection
Revises: 0006_coaching_outcomes
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_coaching_selection"
down_revision = "0006_coaching_outcomes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "coach_recommendations",
        sa.Column("selected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("coach_recommendations", "selected_at")
