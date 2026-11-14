import re
import uuid
from dataclasses import fields
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import get_args

import pytest

from app.planning_models import BlockBenchmarkResult
from app.services.block_benchmark import (
    BenchmarkOutcome,
    BenchmarkSpec,
    BenchmarkStatus,
    MatchFact,
    _decide,
    benchmark_spec,
    status_data,
)
from app.services.run_rpe import effective_run_rpe


def test_effective_run_rpe_prefers_manual_to_garmin_fit() -> None:
    manual_at = datetime(2026, 1, 2, tzinfo=UTC)
    garmin_at = datetime(2026, 1, 3, tzinfo=UTC)
    rows = [
        SimpleNamespace(id='manual', rpe=7.0, source='manual', collected_at=manual_at),
        SimpleNamespace(id='garmin', rpe=6.0, source='garmin_fit', collected_at=garmin_at),
    ]

    assert effective_run_rpe(rows, None) == (7.0, 'manual', manual_at)


def test_effective_run_rpe_uses_garmin_fit_when_manual_is_absent() -> None:
    collected_at = datetime(2026, 1, 3, tzinfo=UTC)
    rows = [SimpleNamespace(id='garmin', rpe=6.0, source='garmin_fit', collected_at=collected_at)]

    assert effective_run_rpe(rows, None) == (6.0, 'garmin_fit', collected_at)


def test_effective_run_rpe_uses_latest_manual_row() -> None:
    earlier = datetime(2026, 1, 2, tzinfo=UTC)
    later = datetime(2026, 1, 3, tzinfo=UTC)
    rows = [
        SimpleNamespace(id='later', rpe=8.0, source='manual', collected_at=later),
        SimpleNamespace(id='earlier', rpe=7.0, source='manual', collected_at=earlier),
    ]

    assert effective_run_rpe(rows, None) == (8.0, 'manual', later)


def test_effective_run_rpe_uses_workout_rpe_without_session_rows() -> None:
    assert effective_run_rpe([], 5.0) == (5.0, 'garmin_fit', None)


def test_effective_run_rpe_returns_none_without_any_source() -> None:
    assert effective_run_rpe([], None) == (None, None, None)


def test_effective_run_rpe_session_row_precedes_workout_rpe() -> None:
    collected_at = datetime(2026, 1, 3, tzinfo=UTC)
    rows = [SimpleNamespace(id='garmin', rpe=6.0, source='garmin_fit', collected_at=collected_at)]

    assert effective_run_rpe(rows, 9.0) == (6.0, 'garmin_fit', collected_at)


REVIEW = date(2026, 11, 20)
SPEC = BenchmarkSpec('time_trial', None, '5 km solo', 5000, date(2026, 11, 18))


def m(aid: uuid.UUID) -> MatchFact:
    return MatchFact(aid, date(2026, 11, 18), 5000, 1470, 8.0, datetime(2026, 11, 18, 13, 30, tzinfo=UTC))


def test_no_benchmark_is_not_set() -> None:
    result = _decide(None, REVIEW, REVIEW, None, None, None)
    assert result.status == 'not_set'
    assert all(getattr(result, field.name) is None for field in fields(BenchmarkStatus) if field.name != 'status')


def test_auto_match_is_completed() -> None:
    match = m(uuid.uuid4())
    result = _decide(SPEC, REVIEW, REVIEW, None, match, None)
    assert result.status == 'completed'
    assert result.match_method == 'auto'
    assert result.result_s == 1470
    assert result.rpe == 8.0
    assert result.evidence_at == match.end_at
    assert status_data(result)['activity_id'] == match.activity_id


def test_manual_match_precedes_auto_match() -> None:
    manual, auto = m(uuid.uuid4()), m(uuid.uuid4())
    result = _decide(SPEC, REVIEW, REVIEW, manual, auto, None)
    assert result.status == 'completed'
    assert result.match_method == 'manual'
    assert result.activity_id == manual.activity_id


@pytest.mark.parametrize(('offset', 'expected'), [(2, 'pending'), (3, 'missed')])
@pytest.mark.parametrize('event', [False, True])
def test_no_match_respects_grace_and_preserves_context(offset: int, expected: str, event: bool) -> None:
    event_id = uuid.uuid4() if event else None
    spec = BenchmarkSpec('event', event_id, '10K race', 10000, SPEC.planned_date) if event else SPEC
    result = _decide(spec, REVIEW, REVIEW + timedelta(days=offset), None, None, SPEC.planned_date)
    assert result.status == expected
    assert result.scheduled_date == SPEC.planned_date
    assert result.event_id == event_id


def test_benchmark_spec_reads_json() -> None:
    assert benchmark_spec(SimpleNamespace(benchmark=None)) is None
    event_id = uuid.uuid4()
    data = {'kind': 'event', 'event_id': str(event_id), 'protocol': '10K race', 'distance_m': 10000,
            'planned_date': '2026-11-18', 'progress_if': 'x', 'consolidate_if': 'y'}
    assert benchmark_spec(SimpleNamespace(benchmark=data)) == BenchmarkSpec('event', event_id, '10K race', 10000, SPEC.planned_date)


def test_benchmark_outcome_matches_table_check() -> None:
    outcomes = get_args(BenchmarkOutcome)
    assert outcomes == ('progress', 'consolidate', 'recalibrate_only', 'inconclusive')
    constraint = next(c for c in BlockBenchmarkResult.__table__.constraints if c.name == 'ck_block_benchmarks_outcome')
    assert re.findall(r"'([a-z_]+)'", str(constraint.sqltext)) == list(outcomes)
