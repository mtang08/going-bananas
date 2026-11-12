"""Keep one open coaching draft and retain dismissed proposals in history."""
import sqlalchemy as sa
from alembic import op

revision = '0017_single_open_proposal'
down_revision = '0016_proposal_revisions'
branch_labels = None
depends_on = None

OPEN = "status IN ('pending','stale','invalid')"
STATUSES = "status IN ('pending','accepted','partially_accepted','rejected','stale','invalid','discarded')"


def upgrade():
    op.add_column('coach_proposals', sa.Column('discarded_at', sa.DateTime(timezone=True)))
    op.drop_constraint('ck_coach_proposals_status', 'coach_proposals', type_='check')
    op.create_check_constraint('ck_coach_proposals_status', 'coach_proposals', STATUSES)
    # Preserve the most recently edited draft; keep older proposals and their revisions readable.
    op.execute("""WITH ranked AS (
        SELECT p.id, row_number() OVER (
            ORDER BY COALESCE((SELECT max(r.saved_at) FROM coach_proposal_revisions r
                WHERE r.proposal_id=p.id), p.submitted_at) DESC, p.submitted_at DESC, p.id DESC
        ) AS position
        FROM coach_proposals p WHERE p.status IN ('pending','stale','invalid')
    ) UPDATE coach_proposals p SET status='discarded', discarded_at=CURRENT_TIMESTAMP
      FROM ranked WHERE p.id=ranked.id AND ranked.position>1""")
    op.create_index('uq_coach_proposals_one_open', 'coach_proposals', [sa.text('(true)')],
        unique=True, postgresql_where=sa.text(OPEN))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM coach_proposals WHERE status='discarded')")).scalar():
        raise RuntimeError('restore_required_nonempty_mvp_schema')
    op.drop_index('uq_coach_proposals_one_open', table_name='coach_proposals')
    op.drop_constraint('ck_coach_proposals_status', 'coach_proposals', type_='check')
    op.create_check_constraint('ck_coach_proposals_status', 'coach_proposals',
        "status IN ('pending','accepted','partially_accepted','rejected','stale','invalid')")
    op.drop_column('coach_proposals', 'discarded_at')
