from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


def _guard(names, extra=None):
    bind = op.get_bind()
    for name in names:
        if bind.execute(sa.text(f'SELECT EXISTS (SELECT 1 FROM {name})')).scalar():
            raise RuntimeError('restore_required_nonempty_mvp_schema')
    if extra is not None and bind.execute(sa.text(extra)).scalar():
        raise RuntimeError('restore_required_nonempty_mvp_schema')

revision = '0012_calendar'
down_revision = '0011_checkins_v2'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('app_state', sa.Column('calendar_head_version', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('app_state', sa.Column('planning_authority', sa.String(12), nullable=False, server_default='legacy'))
    op.create_check_constraint('ck_app_state_planning_authority', 'app_state', "planning_authority IN ('legacy','calendar')")
    op.create_table('calendar_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('parent_number', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('actor', sa.String(10), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('proposal_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('restored_from_number', sa.Integer(), nullable=True),
        sa.Column('block_version_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('number'),
        sa.CheckConstraint("kind IN ('bootstrap','manual_edit','proposal_accept','rollback','legacy_import')", name='ck_calendar_versions_kind'),
        sa.CheckConstraint("actor IN ('system','user','coach')", name='ck_calendar_versions_actor'),
    )
    op.create_table('calendar_session_revisions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('session_uid', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('calendar_version_number', sa.Integer(), nullable=False),
        sa.Column('deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('local_date', sa.Date(), nullable=False),
        sa.Column('slot', sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('kind', sa.String(12), nullable=False),
        sa.Column('recipe_id', sa.String(10), nullable=True),
        sa.Column('custom', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('locked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('legacy_unstructured', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('legacy_payload', postgresql.JSONB(), nullable=True),
        sa.Column('placeholder', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('intent', sa.String(200), nullable=False),
        sa.Column('certainty', sa.String(12), nullable=False),
        sa.Column('planned_duration_s', sa.Integer(), nullable=True),
        sa.Column('planned_distance_m', sa.Integer(), nullable=True),
        sa.Column('structure', postgresql.JSONB(), nullable=True),
        sa.Column('strength_slot_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.CheckConstraint("kind IN ('run','strength','cross','rest','mobility')", name='ck_calendar_session_revisions_kind'),
        sa.UniqueConstraint('session_uid', 'revision'),
        sa.CheckConstraint('slot >= 0', name='ck_calendar_session_revisions_slot'),
        sa.CheckConstraint('planned_duration_s IS NULL OR planned_duration_s > 0', name='ck_calendar_session_revisions_planned_duration_s'),
        sa.CheckConstraint('planned_distance_m IS NULL OR planned_distance_m > 0', name='ck_calendar_session_revisions_planned_distance_m'),
        sa.CheckConstraint("certainty IN ('committed','provisional')", name='ck_calendar_session_revisions_certainty'),
    )
    op.create_index('ix_calendar_session_revisions_calendar_version_number', 'calendar_session_revisions', ['calendar_version_number'])
    op.create_index('ix_calendar_session_revisions_local_date', 'calendar_session_revisions', ['local_date'])
    op.create_foreign_key('fk_calendar_session_revisions_calendar_version_number', 'calendar_session_revisions', 'calendar_versions', ['calendar_version_number'], ['number'])
    op.create_table('session_completions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('session_uid', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('activity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('strong_workout_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('manual_session_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('match_method', sa.String(20), nullable=False),
        sa.Column('modification_reason', sa.String(40), nullable=True),
        sa.Column('reason_note', sa.Text(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('input_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("match_method IN ('explicit','auto_same_day','confirmed_move','user_marked','none')", name='ck_session_completions_match_method'),
        sa.UniqueConstraint('strong_workout_id'),
        sa.CheckConstraint("modification_reason IN ('symptom_onset','fatigue','illness','schedule','weather','equipment','other')", name='ck_session_completions_modification_reason'),
        sa.UniqueConstraint('activity_id'),
        sa.CheckConstraint("status IN ('skipped','unknown') OR num_nonnulls(activity_id,strong_workout_id,manual_session_id) = 1", name='ck_session_completions_status_subject'),
        sa.UniqueConstraint('session_uid'),
        sa.UniqueConstraint('manual_session_id'),
        sa.CheckConstraint("status IN ('completed_as_planned','completed_modified','partial','moved','skipped','extra','unknown')", name='ck_session_completions_status'),
        sa.CheckConstraint('num_nonnulls(activity_id,strong_workout_id,manual_session_id) <= 1', name='ck_session_completions_subject'),
    )
    op.create_foreign_key('fk_session_completions_activity_id', 'session_completions', 'activities', ['activity_id'], ['id'])
    op.create_foreign_key('fk_session_completions_strong_workout_id', 'session_completions', 'strong_workouts', ['strong_workout_id'], ['id'])
    op.create_foreign_key('fk_session_completions_manual_session_id', 'session_completions', 'manual_sessions', ['manual_session_id'], ['id'])
    op.create_table('legacy_import_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('key', sa.String(40), nullable=False),
        sa.Column('source_fingerprint', sa.String(64), nullable=False),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('report', postgresql.JSONB(), nullable=False),
        sa.Column('undo_payload', postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint('key'),
    )
    op.create_table('legacy_import_map',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('import_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_table', sa.String(60), nullable=False),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('target_kind', sa.String(40), nullable=False),
        sa.Column('target_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('payload_sha256', sa.String(64), nullable=False),
        sa.UniqueConstraint('source_table', 'source_id', 'target_kind'),
    )
    op.create_foreign_key('fk_legacy_import_map_import_id', 'legacy_import_map', 'legacy_import_runs', ['import_id'], ['id'])
    op.create_table('legacy_undo_requests',
        sa.Column('idempotency_key', sa.String(100), primary_key=True),
        sa.Column('import_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('result', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_foreign_key('fk_legacy_undo_requests_import_id', 'legacy_undo_requests', 'legacy_import_runs', ['import_id'], ['id'])


def downgrade():
    _guard(['calendar_versions', 'calendar_session_revisions', 'session_completions', 'legacy_import_runs', 'legacy_import_map', 'legacy_undo_requests'], "SELECT EXISTS (SELECT 1 FROM app_state WHERE calendar_head_version <> 0 OR planning_authority <> 'legacy')")
    op.drop_table('legacy_undo_requests')
    op.drop_table('legacy_import_map')
    op.drop_table('legacy_import_runs')
    op.drop_table('session_completions')
    op.drop_table('calendar_session_revisions')
    op.drop_table('calendar_versions')
    op.drop_constraint('ck_app_state_planning_authority', 'app_state', type_='check')
    op.drop_column('app_state', 'planning_authority')
    op.drop_column('app_state', 'calendar_head_version')
