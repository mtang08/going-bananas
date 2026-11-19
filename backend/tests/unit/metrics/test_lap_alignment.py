from collections.abc import Callable, Mapping, Sequence

import pytest

from app.metrics.lap_alignment import AlignLap, Alignment, align_laps

REFS = [0, 1, 2, 1, 2, 1, 2, 1, 2, 4]
WORK = frozenset({1, 3, 5, 7})
COSTS = {"split": 1, "omit_nonwork": 2, "omit_work": 10}


def _complete(step: int, laps: tuple[int, ...]) -> bool:
    return True


def _align(
    lap_refs: Sequence[int | None],
    *,
    refs: Sequence[int] = REFS,
    work: frozenset[int] = WORK,
    completes: Callable[[int, tuple[int, ...]], bool] = _complete,
    costs: Mapping[str, int] = COSTS,
) -> Alignment:
    return align_laps(refs, work, [AlignLap(i, ref) for i, ref in enumerate(lap_refs)], completes, costs)


def test_exact_prefix_is_one_to_one():
    assert _align(REFS) == Alignment(tuple((i,) for i in range(10)), (), (), (), None)


def test_split_warmup_merged():
    result = _align([0, 0, 1, 2, 1, 2, 1, 2, 1, 2, 4])

    assert result.error is None
    assert result.assigned[0] == (0, 1)
    assert result.flags == ("LAP_SPLIT_MERGED",)


def test_skip_last_recovery():
    result = _align([0, 1, 2, 1, 2, 1, 2, 1, 4])

    assert result.error is None
    assert result.omitted == (8,)
    assert result.flags == ("NONWORK_STEP_OMITTED",)


def test_reported_real_case():
    refs = [0, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 4]
    work = frozenset({1, 3, 5, 7, 9})
    result = _align([0, 0, 1, 2, 1, 2, 1, 2, 1, 2, 1, 4], refs=refs, work=work)

    assert result.error is None
    assert result.flags == ("LAP_SPLIT_MERGED", "NONWORK_STEP_OMITTED")
    assert all(len(result.assigned[j]) == 1 for j in work)
    assert result.omitted == (10,)


def test_interior_work_skipped():
    result = _align([0, 1, 2, 2, 1, 2, 1, 2, 4])

    assert result.error is None
    assert len(result.omitted) == 1
    assert result.omitted[0] in WORK
    assert result.flags == ()


def test_prefix_truncation():
    result = _align([0, 1, 2, 1])

    assert result.error is None
    assert result.tail == (4, 5, 6, 7, 8, 9)
    assert result.omitted == ()


def test_out_of_order():
    assert _align([0, 1, 2, 1, 0]) == Alignment((), (), (), (), "LAP_STEP_ORDER_MISMATCH")


@pytest.mark.parametrize("ref", [3, 99])
def test_unknown_reference(ref: int):
    assert _align([0, ref]) == Alignment((), (), (), (), "LAP_STEP_UNKNOWN")


@pytest.mark.parametrize("lap_refs", [[], [None, None]])
def test_no_indexed_laps(lap_refs: list[int | None]):
    assert _align(lap_refs) == Alignment((), (), (), (), "NO_INDEXED_LAPS")


def test_unindexed_laps_flagged():
    result = _align([None, 0, 1, None, 2, 1, 2, 1, 2, 1, 2, 4, None])

    assert result.error is None
    assert result.flags == ("LEADING_LAPS_IGNORED", "TRAILING_LAPS_IGNORED", "UNINDEXED_LAP_IGNORED")
    assert all(3 not in group for group in result.assigned)


def test_sorts_laps_keeps_original_positions_and_checks_work_only():
    laps = [AlignLap(70, 1), AlignLap(15, 0), AlignLap(30, None), AlignLap(50, 1)]

    def completes(step: int, positions: tuple[int, ...]) -> bool:
        assert step == 1
        assert positions in ((50,), (50, 70))
        return positions == (50, 70)

    result = align_laps([0, 1], frozenset({1}), laps, completes, COSTS)

    assert result == Alignment(((15,), (50, 70)), (), (), ("LAP_SPLIT_MERGED", "UNINDEXED_LAP_IGNORED"), None)


def test_adjacent_work_laps_before_cooldown():
    result = _align([0, 1, 1, 4], completes=lambda step, laps: len(laps) == 2)

    assert result.error is None
    assert result.assigned[1] == (1,)
    assert result.assigned[3] == (2,)
    assert result.omitted == (2, 4, 5, 6, 7, 8)


def test_adjacent_work_laps_truncated_merge():
    result = _align([0, 1, 1])

    assert result.error is None
    assert result.assigned[1] == (1, 2)
    assert result.flags == ("LAP_SPLIT_MERGED",)
    assert result.tail == tuple(range(2, 10))


def test_ambiguity_only_when_outcome_differs():
    costs = {**COSTS, "split": 2}
    ambiguous = _align([0, 1, 1], costs=costs, completes=lambda step, laps: len(laps) == 2)
    assert ambiguous == Alignment((), (), (), (), "LAP_ALIGNMENT_AMBIGUOUS")

    same_count = _align([0, 1, 1], costs=costs, completes=lambda step, laps: False)
    assert same_count.error is None
    assert same_count.assigned[1] == (1, 2)
    assert same_count.tail == tuple(range(2, 10))


def test_deterministic():
    laps = [0, 1, 1, 1, 4]
    refs = [0, 1, 1, 4]
    work = frozenset({1, 2})
    result = _align(laps, refs=refs, work=work)

    assert result.error is None
    assert result.assigned == ((0,), (1,), (2, 3), (4,))
    assert result == _align(laps, refs=refs, work=work)
