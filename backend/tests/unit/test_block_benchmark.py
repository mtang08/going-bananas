from datetime import UTC, datetime
from types import SimpleNamespace

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
