from datetime import date, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services.events import goal_pace_s_per_km, ranked_upcoming, renumber, target_status

TODAY = date(2026, 11, 19)


def event(n, *, days=0, rank=None, status="planned"):
    return SimpleNamespace(id=UUID(int=n), status=status, event_date=TODAY + timedelta(days=days), rank=rank)


class FakeSession:
    def __init__(self, rows, pending=()):
        self.rows = list(rows)
        self.pending = list(pending)
        self.flushed = False

    def scalars(self, _stmt):
        return iter(self.rows)

    def flush(self):
        self.rows.extend(self.pending)
        self.pending.clear()
        self.flushed = True


def test_ranked_upcoming_sorts_by_rank_then_date_with_nulls_last():
    first = event(1, days=20, rank=1)
    second = event(2, rank=1, days=20)
    third = event(3, rank=2)
    fourth = event(4, days=1)
    fifth = event(5, days=2)
    assert ranked_upcoming([fifth, second, fourth, third, first], TODAY) == list(
        enumerate([first, second, third, fourth, fifth], start=1)
    )


def test_ranked_upcoming_excludes_past_cancelled_and_completed():
    registered = event(1, status="registered")
    assert ranked_upcoming(
        [registered, event(2, days=-1), event(3, status="cancelled"), event(4, status="completed")], TODAY
    ) == [(1, registered)]


def test_ranked_upcoming_ignores_stale_stored_ranks():
    first, second = event(1, rank=5), event(2, rank=9)
    assert ranked_upcoming([second, first], TODAY) == [(1, first), (2, second)]


def test_renumber_assigns_contiguous_ranks_and_clears_others():
    first, second = event(1, rank=3), event(2)
    past, cancelled = event(3, days=-1, rank=1), event(4, status="cancelled", rank=2)
    session = FakeSession([second, past, first, cancelled])
    assert renumber(session, TODAY) == [(1, first), (2, second)]
    assert [row.rank for row in (first, second, past, cancelled)] == [1, 2, None, None]
    assert session.flushed


def test_renumber_includes_pending_rows():
    first, second = event(1, rank=1), event(2)
    session = FakeSession([first], pending=[second])
    assert renumber(session, TODAY) == [(1, first), (2, second)]
    assert first.rank == 1 and second.rank == 2


@pytest.mark.parametrize(
    ("target", "top", "expected"),
    [(1, 1, "current"), (1, 2, "changed"), (1, None, "changed"), (None, 2, "unset"), (None, None, "none")],
)
def test_target_status_cases(target, top, expected):
    assert target_status(UUID(int=target) if target else None, UUID(int=top) if top else None) == expected


@pytest.mark.parametrize(
    ("distance", "duration", "expected"),
    [(10000, 2700, 270), (21098, 5400, 256), (None, 2700, None), (10000, None, None), (0, 2700, None)],
)
def test_goal_pace_rounds_to_whole_seconds(distance, duration, expected):
    assert goal_pace_s_per_km(distance, duration) == expected
