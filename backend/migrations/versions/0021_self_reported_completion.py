"""Allow athlete-confirmed completion without a recording."""

from alembic import op

revision = "0021_self_reported_completion"
down_revision = "0020_drop_planning_authority"
branch_labels = None
depends_on = None

NAME = "ck_session_completions_status_subject"
PREVIOUS = "status IN ('skipped','unknown') OR num_nonnulls(activity_id,strong_workout_id,manual_session_id) = 1"


def upgrade():
    op.drop_constraint(NAME, "session_completions", type_="check")
    op.create_check_constraint(
        NAME, "session_completions", PREVIOUS + " OR (status = 'completed_as_planned' AND match_method = 'user_marked')"
    )


def downgrade():
    # PostgreSQL refuses the downgrade if it would invalidate a saved self-report.
    op.drop_constraint(NAME, "session_completions", type_="check")
    op.create_check_constraint(NAME, "session_completions", PREVIOUS)
