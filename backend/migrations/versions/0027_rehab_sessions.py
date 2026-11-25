"""Allow independent rehab sessions in the versioned calendar."""

from alembic import op

revision = "0027_rehab_sessions"
down_revision = "0026_workout_response"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_calendar_session_revisions_kind", "calendar_session_revisions", type_="check")
    op.create_check_constraint(
        "ck_calendar_session_revisions_kind",
        "calendar_session_revisions",
        "kind IN ('run','strength','cross','rest','mobility','rehab')",
    )


def downgrade() -> None:
    # Refuse to discard rehab history on downgrade.
    op.drop_constraint("ck_calendar_session_revisions_kind", "calendar_session_revisions", type_="check")
    op.create_check_constraint(
        "ck_calendar_session_revisions_kind",
        "calendar_session_revisions",
        "kind IN ('run','strength','cross','rest','mobility')",
    )
