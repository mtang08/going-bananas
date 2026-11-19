"""Retain FIT lap intensity, end time and decoder version."""
import sqlalchemy as sa
from alembic import op

revision = '0019_lap_intensity_end'
down_revision = '0018_exception_findings'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('activity_laps', sa.Column('intensity', sa.String(20)))
    op.add_column('activity_laps', sa.Column('end_at', sa.DateTime(timezone=True)))
    op.create_check_constraint(
        'ck_activity_laps_intensity', 'activity_laps',
        "intensity IS NULL OR intensity IN ('active','rest','warmup','cooldown','recovery','interval','other')",
    )
    op.add_column('fit_files', sa.Column('decoder_version', sa.Integer()))


def downgrade():
    op.drop_column('fit_files', 'decoder_version')
    op.drop_constraint('ck_activity_laps_intensity', 'activity_laps', type_='check')
    op.drop_column('activity_laps', 'end_at')
    op.drop_column('activity_laps', 'intensity')
