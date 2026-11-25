"""Preserve explicit answers to the workout pain question."""

import sqlalchemy as sa
from alembic import op

revision = "0026_workout_response"
down_revision = "0025_coach_output_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("checkins_v2", sa.Column("pain_reported", sa.Boolean(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM checkins_v2 WHERE pain_reported IS NOT NULL)")).scalar():
        raise RuntimeError("restore_required_workout_response")
    op.drop_column("checkins_v2", "pain_reported")
