"""Race goals: event purpose, goal time and rank; block target event and build outline."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022_race_goals"
down_revision = "0021_self_reported_completion"
branch_labels = None
depends_on = None

OLD_PRIORITY = "priority IN ('target','supported_exposure','benchmark','optional')"
EXPIRE_NOTE = "Event removed by migration 0022_race_goals"


def upgrade():
    bind = op.get_bind()
    # Events are deleted (Q5). Rows that referenced them stay, with the reference cleared.
    op.execute("UPDATE block_benchmarks SET event_id = NULL")
    op.execute("UPDATE intensity_anchors SET source_event_id = NULL")
    op.execute(
        sa.text(
            "UPDATE exception_findings SET status = 'expired', closed_at = now(), "
            "close_note = :note, version = version + 1 "
            "WHERE rule_code = 'POST_EVENT_REVIEW_DUE' AND status IN ('open','addressed')"
        ).bindparams(note=EXPIRE_NOTE)
    )
    deleted = bind.execute(sa.text("DELETE FROM events")).rowcount
    print(f"0022_race_goals: deleted {deleted} events")

    op.drop_constraint("ck_events_priority", "events", type_="check")
    op.drop_column("events", "priority")
    op.add_column("events", sa.Column("purpose", sa.String(12), nullable=False))
    op.create_check_constraint("ck_events_purpose", "events", "purpose IN ('pr','benchmark','training')")
    op.add_column("events", sa.Column("goal_time_s", sa.Integer(), nullable=True))
    op.create_check_constraint("ck_events_goal_time", "events", "goal_time_s IS NULL OR goal_time_s > 0")
    op.add_column("events", sa.Column("rank", sa.SmallInteger(), nullable=True))
    op.create_check_constraint("ck_events_rank", "events", "rank IS NULL OR rank >= 1")
    op.create_unique_constraint("uq_events_rank", "events", ["rank"], deferrable=True, initially="DEFERRED")

    op.add_column(
        "block_versions",
        sa.Column("target_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id"), nullable=True),
    )
    op.add_column(
        "block_versions",
        sa.Column("build_outline", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade():
    # Deleted events are not restored; the backup holds them.
    bind = op.get_bind()
    for probe in (
        "SELECT EXISTS (SELECT 1 FROM events)",
        "SELECT EXISTS (SELECT 1 FROM block_versions WHERE target_event_id IS NOT NULL)",
        "SELECT EXISTS (SELECT 1 FROM block_versions WHERE build_outline <> '[]'::jsonb)",
    ):
        if bind.execute(sa.text(probe)).scalar():
            raise RuntimeError("restore_required_nonempty_race_goals")
    op.drop_column("block_versions", "build_outline")
    op.drop_column("block_versions", "target_event_id")
    op.drop_constraint("uq_events_rank", "events", type_="unique")
    op.drop_constraint("ck_events_rank", "events", type_="check")
    op.drop_column("events", "rank")
    op.drop_constraint("ck_events_goal_time", "events", type_="check")
    op.drop_column("events", "goal_time_s")
    op.drop_constraint("ck_events_purpose", "events", type_="check")
    op.drop_column("events", "purpose")
    op.add_column("events", sa.Column("priority", sa.String(20), nullable=False))
    op.create_check_constraint("ck_events_priority", "events", OLD_PRIORITY)
