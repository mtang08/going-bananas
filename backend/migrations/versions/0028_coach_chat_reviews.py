"""Persist dashboard conversations and idempotent message receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0028_coach_chat_reviews"
down_revision = "0027_rehab_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coach_chat_reviews",
        sa.Column("mode", sa.Text(), primary_key=True),
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("state", JSONB(), nullable=False),
        sa.Column("current", sa.Boolean(), nullable=False),
    )
    op.create_table("coach_chat_file_imports", sa.Column("mode", sa.Text(), primary_key=True))
    op.create_index(
        "coach_chat_current", "coach_chat_reviews", ["mode"], unique=True, postgresql_where=sa.text("current")
    )
    op.create_table(
        "coach_chat_receipts",
        sa.Column("mode", sa.Text(), primary_key=True),
        sa.Column("client_message_id", UUID(), primary_key=True),
        sa.Column("digest", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    # Dropping populated tables would lose private reviews or permit a replayed turn.
    op.execute("""
        LOCK TABLE coach_chat_reviews, coach_chat_receipts, coach_chat_file_imports IN ACCESS EXCLUSIVE MODE
    """)
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT FROM coach_chat_reviews) OR EXISTS (SELECT FROM coach_chat_receipts)
             OR EXISTS (SELECT FROM coach_chat_file_imports) THEN
            RAISE EXCEPTION 'Cannot downgrade while dashboard reviews or receipts exist';
          END IF;
        END $$
    """)
    op.drop_table("coach_chat_file_imports")
    op.drop_table("coach_chat_receipts")
    op.drop_table("coach_chat_reviews")
