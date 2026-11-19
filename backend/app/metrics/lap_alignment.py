"""Align indexed laps with the expanded steps of a watch workout."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

__all__ = ["AlignLap", "Alignment", "align_laps"]


@dataclass(frozen=True)
class AlignLap:
    position: int
    wkt_step_index: int | None


@dataclass(frozen=True)
class Alignment:
    assigned: tuple[tuple[int, ...], ...]
    omitted: tuple[int, ...]
    tail: tuple[int, ...]
    flags: tuple[str, ...]
    error: str | None


@dataclass
class _State:
    cost: int
    lo: int
    hi: int
    previous_lap: int


def _relax(states: dict[int, _State], consumed: int, candidate: _State) -> None:
    current = states.get(consumed)
    if current is None or candidate.cost < current.cost:
        states[consumed] = candidate
    elif candidate.cost == current.cost:
        current.lo = min(current.lo, candidate.lo)
        current.hi = max(current.hi, candidate.hi)
        # Keep earlier assignments by preferring an omission when tracing backward.
        if candidate.previous_lap == consumed:
            current.previous_lap = consumed
        elif current.previous_lap != consumed:
            current.previous_lap = min(current.previous_lap, candidate.previous_lap)


def align_laps(
    expanded_refs: Sequence[int],
    work_positions: frozenset[int],
    laps: Sequence[AlignLap],
    completes: Callable[[int, tuple[int, ...]], bool],
    costs: Mapping[str, int],
) -> Alignment:
    ordered = sorted(laps, key=lambda lap: lap.position)
    indexed_positions = [i for i, lap in enumerate(ordered) if lap.wkt_step_index is not None]
    if not indexed_positions:
        return Alignment((), (), (), (), "NO_INDEXED_LAPS")

    indexed = [ordered[i] for i in indexed_positions]
    first, last = indexed_positions[0], indexed_positions[-1]
    flags: set[str] = set()
    if first > 0:
        flags.add("LEADING_LAPS_IGNORED")
    if last + 1 < len(ordered):
        flags.add("TRAILING_LAPS_IGNORED")
    if last - first + 1 > len(indexed):
        flags.add("UNINDEXED_LAP_IGNORED")

    known_refs = set(expanded_refs)
    if any(lap.wkt_step_index not in known_refs for lap in indexed):
        return Alignment((), (), (), tuple(sorted(flags)), "LAP_STEP_UNKNOWN")

    n, m = len(indexed), len(expanded_refs)
    positions = tuple(lap.position for lap in indexed)
    states: list[dict[int, _State]] = [{} for _ in range(m + 1)]
    states[0][0] = _State(0, 0, 0, 0)

    for j, ref in enumerate(expanded_refs):
        is_work = j in work_positions
        omit_cost = costs["omit_work"] if is_work else costs["omit_nonwork"]
        for i in sorted(states[j]):
            state = states[j][i]
            next_states = states[j + 1]
            for k in range(i + 1, n + 1):
                if indexed[k - 1].wkt_step_index != ref:
                    break
                completed = int(is_work and completes(j, positions[i:k]))
                _relax(
                    next_states,
                    k,
                    _State(
                        state.cost + (k - i - 1) * costs["split"],
                        state.lo + completed,
                        state.hi + completed,
                        i,
                    ),
                )
            _relax(next_states, i, _State(state.cost + omit_cost, state.lo, state.hi, i))

    ends = [(j, layer[n]) for j, layer in enumerate(states) if n in layer]
    if not ends:
        return Alignment((), (), (), tuple(sorted(flags)), "LAP_STEP_ORDER_MISMATCH")

    min_cost = min(state.cost for _, state in ends)
    best = [(j, state) for j, state in ends if state.cost == min_cost]
    if min(state.lo for _, state in best) != max(state.hi for _, state in best):
        return Alignment((), (), (), tuple(sorted(flags)), "LAP_ALIGNMENT_AMBIGUOUS")

    end = best[0][0]
    assigned: list[tuple[int, ...]] = [()] * m
    omitted: list[int] = []
    i = n
    for j in range(end - 1, -1, -1):
        previous_lap = states[j + 1][i].previous_lap
        if previous_lap == i:
            omitted.append(j)
        else:
            assigned[j] = positions[previous_lap:i]
        i = previous_lap

    if any(len(group) > 1 for group in assigned):
        flags.add("LAP_SPLIT_MERGED")
    if any(j not in work_positions for j in omitted):
        flags.add("NONWORK_STEP_OMITTED")

    return Alignment(tuple(assigned), tuple(reversed(omitted)), tuple(range(end, m)), tuple(sorted(flags)), None)
