from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from app.metrics import engine
from app.metrics.contract import (
    QualityStatus,
    completion_association_hash,
    config_hash,
    coverage_label,
    integrate_timer_on,
    plausible_hr,
    plausible_speed,
    rolling_window,
)
from app.metrics.engine import parse_scope, recompute, register


def test_timer_union_keeps_unknown_edges_and_gaps() -> None:
    pieces = integrate_timer_on([0, 1, 2, 3, 20, 21], [(0, 2), (3, 21)], 10)
    assert sum(seconds for _, seconds, _ in pieces) == 20
    assert sum(seconds for _, seconds, known in pieces if known) == 3
    assert sum(seconds for _, seconds, known in pieces if not known) == 17
    assert (3, 17, False) in pieces
    assert integrate_timer_on([], [(0, 10)], 10) == [(None, 10, False)]
    assert integrate_timer_on([2, 4], [(0, 6)], 10) == [
        (None, 2, False), (0, 2, True), (None, 2, False)]
    assert sum(x[1] for x in integrate_timer_on([0, 2, 4, 6], [(0, 4), (2, 6)], 10)) == 6
    assert integrate_timer_on([0, 1, 2], [(0.25, 1.75)], 10) == [(0, .75, True), (1, .75, True)]
    assert integrate_timer_on([0, 1, 2], [(0, 0), (0, 2), (2, 2)], 10) == [
        (0, 1, True), (1, 1, True)]
    assert integrate_timer_on([0, 1], [(0, 0), (1, 1)], 10) == []


@pytest.mark.parametrize('samples,timer,gap,error', [
    ([2, 1], [(0, 2)], 10, 'invalid_stream_order'),
    ([1, 1], [(0, 2)], 10, 'invalid_stream_order'),
    ([0, 1], [(1, 0)], 10, 'invalid_timer'),
    ([0, 1], [(0, float('inf'))], 10, 'invalid_timer'),
    ([0, 1], [(0, 1, 2)], 10, 'invalid_timer'),
    ([0, 1], [(0, 1)], 0, 'invalid_timer'),
])
def test_timer_rejects_bad_input(samples, timer, gap, error) -> None:
    with pytest.raises(ValueError, match=error):
        integrate_timer_on(samples, timer, gap)


def test_coverage_and_hashes() -> None:
    assert coverage_label(9, 10) == QualityStatus.good
    assert coverage_label(7, 10) == QualityStatus.limited
    assert coverage_label(6.99, 10) == QualityStatus.insufficient
    assert coverage_label(0, 0) is None
    with pytest.raises(ValueError):
        coverage_label(float('nan'), 10)
    assert rolling_window(date(2026, 11, 12), 7) == (date(2026, 11, 6), date(2026, 11, 12))
    assert config_hash({'b': 1, 'a': 2}) == config_hash({'a': 2, 'b': 1})
    with pytest.raises(ValueError):
        config_hash({'x': float('inf')})
    assert plausible_hr(30) and plausible_hr(230) and not plausible_hr(29)
    assert plausible_speed(0) and plausible_speed(10) and not plausible_speed(11)
    base = {'session_uid': UUID(int=1), 'activity_id': UUID(int=2),
            'match_method': 'explicit', 'modification_reason': 'fatigue',
            'reason_note': 'felt heavy', 'input_version': 2}
    assert completion_association_hash(base) == completion_association_hash(
        {**base, 'status': 'partial', 'version': 7, 'updated_at': datetime.now(UTC)})
    assert completion_association_hash(base) != completion_association_hash({**base, 'input_version': 3})


def test_scope_and_empty_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, 'REGISTRY', {})
    assert parse_scope('activity:00000000-0000-0000-0000-000000000001')[0] == 'activity'
    assert parse_scope('strength:strong:00000000-0000-0000-0000-000000000001')[0] == 'strength:strong'
    assert parse_scope('recovery_dates:2026-11-11,2026-11-12')[1] == (date(2026, 11, 11), date(2026, 11, 12))
    for scope in ('activity:nope', 'anchors:2026-99-99', 'recovery_dates:', 'bogus'):
        with pytest.raises(ValueError, match='invalid_scope'):
            parse_scope(scope)
    assert not engine.REGISTRY
    assert recompute(None, 'calendar') == []


def test_registry_rejects_duplicate_unknown_and_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, 'REGISTRY', {})
    @register('a', 'v1', ('b',))
    def a(_session, _scope):
        return []

    with pytest.raises(ValueError, match='duplicate_metric_registration'):
        register('a', 'v1', ())(a)
    with pytest.raises(ValueError, match='unknown_metric_dependency'):
        recompute(None, 'calendar')
    @register('b', 'v1', ('a',))
    def b(_session, _scope):
        return []
    with pytest.raises(ValueError, match='metric_dependency_cycle'):
        recompute(None, 'calendar')
