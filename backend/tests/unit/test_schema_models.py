from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Index, Numeric

import app.agent_models  # noqa: F401
import app.calendar_models  # noqa: F401
import app.checkin_models  # noqa: F401
import app.coach_v2_models  # noqa: F401
import app.coaching_models  # noqa: F401
import app.fit_models  # noqa: F401
import app.metric_models  # noqa: F401
import app.planning_models  # noqa: F401
import app.strong_models  # noqa: F401
from app.db import Base
from app.migrations_head import EXPECTED_HEAD


def test_single_chained_schema_head() -> None:
    config = Config('alembic.ini')
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [EXPECTED_HEAD]
    revisions = [revision.revision for revision in script.walk_revisions()]
    assert revisions[:8] == [
        '0017_single_open_proposal', '0016_proposal_revisions', '0015_coach_v2', '0014_anchors_metrics_prompts', '0013_blocks_goals',
        '0012_calendar', '0011_checkins_v2', '0010_ingest_fit',
    ]


def test_required_tables_are_in_metadata() -> None:
    assert set('''fit_files activity_laps activity_workout_steps activity_streams
        checkins_v2 checkin_v2_revisions symptom_reports session_rpe
        calendar_versions calendar_session_revisions session_completions
        legacy_import_runs legacy_import_map legacy_undo_requests
        blocks block_versions block_decisions goals events strength_routine_slots
        intensity_anchors metric_configs metric_results prompts coach_snapshots
        coach_proposals coach_proposal_revisions coach_proposal_changes coach_decision_keys daily_guidance'''.split()) <= set(Base.metadata.tables)
    assert Base.metadata.tables['activities'].c.fit_status.server_default.arg == 'not_fetched'
    assert Base.metadata.tables['app_state'].c.planning_authority.server_default.arg == 'legacy'
    assert Base.metadata.tables['app_state'].c.calendar_head_version.server_default.arg == '0'
    assert Base.metadata.tables['session_completions'].c.input_version.server_default.arg == '1'
    assert isinstance(Base.metadata.tables['session_rpe'].c.rpe.type, Numeric)


def test_integrity_rules_are_declared() -> None:
    expected = {
        'checkins_v2': {'ck_checkins_v2_context_tags', 'ck_checkins_v2_fatigue'},
        'session_rpe': {'ck_session_rpe_subject', 'ck_session_rpe_rpe'},
        'session_completions': {'ck_session_completions_subject', 'ck_session_completions_status_subject'},
        'intensity_anchors': {'ck_intensity_anchors_unit_kind', 'ck_intensity_anchors_value_high'},
    }
    for name, constraint_names in expected.items():
        actual = {c.name for c in Base.metadata.tables[name].constraints if isinstance(c, CheckConstraint)}
        assert constraint_names <= actual
    for table_name, index_name in [
        ('prompts', 'uq_prompts_kind_activity_session'),
        ('metric_results', 'uq_metric_results_identity'),
        ('metric_results', 'uq_metric_results_current'),
    ]:
        assert any(isinstance(index, Index) and index.name == index_name
                   for index in Base.metadata.tables[table_name].indexes)
