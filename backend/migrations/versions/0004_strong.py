"""Add source-faithful Strong workout storage.

Revision ID: 0004_strong
Revises: 0003_app_state
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0004_strong"
down_revision = "0003_app_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strong_workouts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source_account_id", UUID(as_uuid=True), sa.ForeignKey("source_accounts.id"), nullable=False),
        sa.Column("source_identity", sa.String(64), nullable=False),
        sa.Column("source_record_id", UUID(as_uuid=True), sa.ForeignKey("source_records.id"), nullable=False),
        sa.Column("raw_object_id", UUID(as_uuid=True), sa.ForeignKey("raw_objects.id"), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("local_start", sa.String(19), nullable=False),
        sa.Column("workout_name", sa.Text(), nullable=False),
        sa.Column("duration_s", sa.Float()),
        sa.Column("sets", JSONB(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("resolution_state", sa.String(30), nullable=False, server_default="resolved"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source_account_id", "source_identity"),
    )
    op.create_index("ix_strong_workouts_local_date", "strong_workouts", ["local_date"])


def downgrade() -> None:
    op.drop_index("ix_strong_workouts_local_date", table_name="strong_workouts")
    op.drop_table("strong_workouts")
