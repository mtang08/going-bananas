from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Index, Numeric, UniqueConstraint

import app.calendar_models  # noqa: F401
import app.checkin_models  # noqa: F401
import app.coach_v2_models  # noqa: F401
import app.exception_models  # noqa: F401
import app.fit_models  # noqa: F401
import app.history_models  # noqa: F401
import app.metric_models  # noqa: F401
import app.planning_models  # noqa: F401
import app.strong_models  # noqa: F401
import app.travel_models  # noqa: F401
from app.db import Base
from app.migrations_head import EXPECTED_HEAD


def test_single_chained_schema_head() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [EXPECTED_HEAD]
    revisions = [revision.revision for revision in script.walk_revisions()]
    assert revisions[:19] == [
        "0028_coach_chat_reviews",
        "0027_rehab_sessions",
        "0026_workout_response",
        "0025_coach_output_v2",
        "0024_google_calendar",
        "0023_treadmill_interval_paces",
        "0022_race_goals",
        "0021_self_reported_completion",
        "0020_drop_planning_authority",
        "0019_lap_intensity_end",
        "0018_exception_findings",
        "0017_single_open_proposal",
        "0016_proposal_revisions",
        "0015_coach_v2",
        "0014_anchors_metrics_prompts",
        "0013_blocks_goals",
        "0012_calendar",
        "0011_checkins_v2",
        "0010_ingest_fit",
    ]


def test_required_tables_are_in_metadata() -> None:
    assert set(
        """fit_files activity_laps activity_workout_steps activity_streams
        checkins_v2 checkin_v2_revisions symptom_reports session_rpe
        calendar_versions calendar_session_revisions session_completions
        checkins checkin_revisions plan_versions planned_sessions completion_links weekly_snapshots
        coach_plan_revisions coach_recommendations coach_outcomes coach_outcome_events
        legacy_import_runs legacy_import_map
        blocks block_versions block_decisions goals events strength_routine_slots
        coach_chat_reviews coach_chat_receipts coach_chat_file_imports
        intensity_anchors metric_configs metric_results prompts coach_snapshots
        coach_proposals coach_proposal_revisions coach_proposal_changes coach_decision_keys
        exception_patches exception_findings block_benchmarks gcal_events trips trip_legs""".split()
    ) <= set(Base.metadata.tables)
    assert Base.metadata.tables["activities"].c.fit_status.server_default.arg == "not_fetched"
    assert "planning_authority" not in Base.metadata.tables["app_state"].c
    assert Base.metadata.tables["app_state"].c.calendar_head_version.server_default.arg == "0"
    assert Base.metadata.tables["session_completions"].c.input_version.server_default.arg == "1"
    assert Base.metadata.tables["checkins_v2"].c.pain_reported.nullable
    assert isinstance(Base.metadata.tables["session_rpe"].c.rpe.type, Numeric)
    assert Base.metadata.tables["block_versions"].c.benchmark.nullable is True


def test_integrity_rules_are_declared() -> None:
    expected = {
        "checkins_v2": {"ck_checkins_v2_context_tags", "ck_checkins_v2_fatigue"},
        "session_rpe": {"ck_session_rpe_subject", "ck_session_rpe_rpe"},
        "session_completions": {"ck_session_completions_subject", "ck_session_completions_status_subject"},
        "intensity_anchors": {"ck_intensity_anchors_unit_kind", "ck_intensity_anchors_value_high"},
        "exception_patches": {
            "ck_exception_patches_category",
            "ck_exception_patches_severity",
            "ck_exception_patches_ladder_level",
            "ck_exception_patches_status",
            "ck_exception_patches_resolved_by",
        },
        "exception_findings": {
            "ck_exception_findings_category",
            "ck_exception_findings_severity",
            "ck_exception_findings_status",
        },
        "block_benchmarks": {"ck_block_benchmarks_match_method", "ck_block_benchmarks_outcome"},
        "gcal_events": {"ck_gcal_events_time_shape", "ck_gcal_events_category", "ck_gcal_events_response"},
        "trips": {"ck_trips_source_shape", "ck_trips_review_status", "ck_trips_dates"},
    }
    for name, constraint_names in expected.items():
        actual = {c.name for c in Base.metadata.tables[name].constraints if isinstance(c, CheckConstraint)}
        assert constraint_names <= actual
    for table_name, index_name in [
        ("prompts", "uq_prompts_kind_activity_session"),
        ("metric_results", "uq_metric_results_identity"),
        ("metric_results", "uq_metric_results_current"),
        ("exception_findings", "uq_exception_findings_active"),
    ]:
        assert any(
            isinstance(index, Index) and index.name == index_name for index in Base.metadata.tables[table_name].indexes
        )

    unique = [
        c
        for c in Base.metadata.tables["block_benchmarks"].constraints
        if isinstance(c, UniqueConstraint) and c.name == "uq_block_benchmarks_block_version"
    ]
    assert len(unique) == 1 and [col.name for col in unique[0].columns] == ["block_uid", "block_version"]


def test_coach_operation_checks_allow_exception_operations() -> None:
    for table, name in [
        ("coach_snapshots", "ck_coach_snapshots_operation"),
        ("coach_proposals", "ck_coach_proposals_operation"),
        ("coach_proposals", "ck_coach_proposals_escalation"),
    ]:
        check = next(
            c for c in Base.metadata.tables[table].constraints if isinstance(c, CheckConstraint) and c.name == name
        )
        assert "'exception_review'" in str(check.sqltext)
        assert "'post_event_review'" in str(check.sqltext)
    index = next(
        i for i in Base.metadata.tables["exception_findings"].indexes if i.name == "uq_exception_findings_active"
    )
    assert index.unique is True
    assert str(index.dialect_options["postgresql"]["where"]) == "status IN ('open','addressed')"
