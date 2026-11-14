"""Exception findings, tracked exception patches, and two new coach operations."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0018_exception_findings'
down_revision = '0017_single_open_proposal'
branch_labels = None
depends_on = None

OLD_OPS = ('proceed_or_modify_today', 'review_rolling_plan', 'review_training_block',
           'select_quality_session', 'recalibrate_intensity', 'handle_goal_or_race_change')
NEW_OPS = OLD_OPS + ('exception_review', 'post_event_review')
OPERATION_CHECKS = (('coach_snapshots', 'ck_coach_snapshots_operation', 'operation'),
                    ('coach_proposals', 'ck_coach_proposals_operation', 'operation'),
                    ('coach_proposals', 'ck_coach_proposals_escalation', 'escalation'))
EMPTY = sa.text("'[]'::jsonb")
CATEGORY = "('symptoms_illness','training_response','accumulated_fatigue','calendar_disruption','post_event')"
SEVERITY = "('observe','caution','hold','escalate')"


def _in(column, values):
    return f"{column} IN ({','.join(repr(v) for v in values)})"


def _set_operations(values):
    for table, name, column in OPERATION_CHECKS:
        op.drop_constraint(name, table, type_='check')
        op.create_check_constraint(name, table, _in(column, values))


def upgrade():
    _set_operations(NEW_OPS)
    op.create_table(
        'exception_patches',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('proposal_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('coach_proposals.id'), nullable=False),
        sa.Column('calendar_version_number', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(24), nullable=False),
        sa.Column('severity', sa.String(10), nullable=False),
        sa.Column('ladder_level', sa.String(20), nullable=False),
        sa.Column('window_start', sa.Date(), nullable=False),
        sa.Column('window_end', sa.Date(), nullable=False),
        sa.Column('reassess_on', sa.Date(), nullable=False),
        sa.Column('monitor', postgresql.JSONB(), nullable=False, server_default=EMPTY),
        sa.Column('return_criteria', postgresql.JSONB(), nullable=False, server_default=EMPTY),
        sa.Column('escalate_criteria', postgresql.JSONB(), nullable=False, server_default=EMPTY),
        sa.Column('unchanged', postgresql.JSONB(), nullable=False, server_default=EMPTY),
        sa.Column('status', sa.String(12), nullable=False, server_default='open'),
        sa.Column('resolved_at', sa.DateTime(timezone=True)),
        sa.Column('resolved_by', sa.String(8)),
        sa.Column('resolution_note', sa.String(500)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.UniqueConstraint('proposal_id'),
        sa.CheckConstraint(f'category IN {CATEGORY}', name='ck_exception_patches_category'),
        sa.CheckConstraint(f'severity IN {SEVERITY}', name='ck_exception_patches_severity'),
        sa.CheckConstraint("ladder_level IN ('current_session','next_session','next_days','committed_window','block')", name='ck_exception_patches_ladder_level'),
        sa.CheckConstraint("status IN ('open','resolved','escalated','superseded')", name='ck_exception_patches_status'),
        sa.CheckConstraint("resolved_by IN ('coach','athlete')", name='ck_exception_patches_resolved_by'),
    )
    op.create_table(
        'exception_findings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('rule_code', sa.String(40), nullable=False),
        sa.Column('rule_version', sa.String(20), nullable=False),
        sa.Column('category', sa.String(24), nullable=False),
        sa.Column('severity', sa.String(10), nullable=False),
        sa.Column('entity_key', sa.String(160), nullable=False),
        sa.Column('status', sa.String(12), nullable=False, server_default='open'),
        sa.Column('summary', sa.String(240), nullable=False),
        sa.Column('evidence', postgresql.JSONB(), nullable=False),
        sa.Column('evidence_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('patch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('exception_patches.id')),
        sa.Column('reviewed_by_proposal_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('coach_proposals.id')),
        sa.Column('closed_at', sa.DateTime(timezone=True)),
        sa.Column('close_note', sa.String(500)),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.CheckConstraint(f'category IN {CATEGORY}', name='ck_exception_findings_category'),
        sa.CheckConstraint(f'severity IN {SEVERITY}', name='ck_exception_findings_severity'),
        sa.CheckConstraint("status IN ('open','addressed','reviewed','resolved','dismissed','expired')", name='ck_exception_findings_status'),
    )
    op.create_index('uq_exception_findings_active', 'exception_findings', ['rule_code', 'entity_key'], unique=True,
                    postgresql_where=sa.text("status IN ('open','addressed')"))
    op.add_column('block_versions', sa.Column('benchmark', postgresql.JSONB(), nullable=True))
    op.create_table(
        'block_benchmarks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('block_uid', postgresql.UUID(as_uuid=True), sa.ForeignKey('blocks.block_uid'), nullable=False),
        sa.Column('block_version', sa.Integer(), nullable=False),
        sa.Column('match_method', sa.String(8), nullable=False),
        sa.Column('activity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('activities.id')),
        sa.Column('event_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('events.id')),
        sa.Column('protocol', sa.String(300), nullable=False),
        sa.Column('distance_m', sa.Integer()),
        sa.Column('local_date', sa.Date()),
        sa.Column('result_s', sa.Integer()),
        sa.Column('outcome', sa.String(20)),
        sa.Column('compared_with', sa.String(300)),
        sa.Column('proposal_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('coach_proposals.id')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('block_uid', 'block_version', name='uq_block_benchmarks_block_version'),
        sa.CheckConstraint("match_method IN ('auto','manual')", name='ck_block_benchmarks_match_method'),
        sa.CheckConstraint("outcome IN ('progress','consolidate','recalibrate_only','inconclusive')", name='ck_block_benchmarks_outcome'),
    )


def downgrade():
    bind = op.get_bind()
    new_ops = "('exception_review','post_event_review')"
    for probe in ('SELECT EXISTS (SELECT 1 FROM exception_findings)',
                  'SELECT EXISTS (SELECT 1 FROM exception_patches)',
                  f'SELECT EXISTS (SELECT 1 FROM coach_snapshots WHERE operation IN {new_ops})',
                  f'SELECT EXISTS (SELECT 1 FROM coach_proposals WHERE operation IN {new_ops} OR escalation IN {new_ops})',
                  'SELECT EXISTS (SELECT 1 FROM block_benchmarks)',
                  'SELECT EXISTS (SELECT 1 FROM block_versions WHERE benchmark IS NOT NULL)'):
        if bind.execute(sa.text(probe)).scalar():
            raise RuntimeError('restore_required_nonempty_mvp_schema')
    op.drop_index('uq_exception_findings_active', table_name='exception_findings')
    op.drop_table('exception_findings')
    op.drop_table('exception_patches')
    op.drop_table('block_benchmarks')
    op.drop_column('block_versions', 'benchmark')
    _set_operations(OLD_OPS)
