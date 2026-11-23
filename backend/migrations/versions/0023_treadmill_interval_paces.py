"""Store athlete-confirmed treadmill lap paces independently of watch data."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0023_treadmill_interval_paces"
down_revision = "0022_race_goals"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("activities", sa.Column("treadmill_interval_paces", JSONB(), nullable=True))


def downgrade():
    op.drop_column("activities", "treadmill_interval_paces")
