// Package intervals aligns FIT workout laps with the planned work repetitions.
package intervals

import (
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/recording"
	"math"
	"slices"
)

type lap struct {
	index                                int
	ref                                  *int
	start                                float64
	end, elapsed, timer, distance, speed *float64
	intensity                            *string
	pace                                 *float64
}
type alignment struct {
	assigned      [][]int
	omitted, tail []int
	flags         []string
	err           string
}
type state struct{ cost, lo, hi, previous int }

func improve(layer map[int]state, i int, next state) {
	old, ok := layer[i]
	if !ok || next.cost < old.cost {
		layer[i] = next
		return
	}
	if next.cost != old.cost {
		return
	}
	old.lo = min(old.lo, next.lo)
	old.hi = max(old.hi, next.hi)
	if next.previous == i {
		old.previous = i
	} else if old.previous != i {
		old.previous = min(old.previous, next.previous)
	}
	layer[i] = old
}
func align(steps []recording.FitStep, work map[int]repPlan, laps []lap) alignment {
	var pos []int
	for i, l := range laps {
		if l.ref != nil {
			pos = append(pos, i)
		}
	}
	var a alignment
	if len(pos) == 0 {
		a.err = "NO_INDEXED_LAPS"
		return a
	}
	if pos[0] > 0 {
		a.flags = append(a.flags, "LEADING_LAPS_IGNORED")
	}
	if pos[len(pos)-1] < len(laps)-1 {
		a.flags = append(a.flags, "TRAILING_LAPS_IGNORED")
	}
	if pos[len(pos)-1]-pos[0]+1 > len(pos) {
		a.flags = append(a.flags, "UNINDEXED_LAP_IGNORED")
	}
	for _, p := range pos {
		if !slices.ContainsFunc(steps, func(s recording.FitStep) bool { return s.Index == *laps[p].ref }) {
			a.err = "LAP_STEP_UNKNOWN"
			return a
		}
	}
	states := make([]map[int]state, len(steps)+1)
	states[0] = map[int]state{0: {}}
	for j, step := range steps {
		next := map[int]state{}
		states[j+1] = next
		p, hard := work[j]
		omit := 2
		if hard {
			omit = 10
		}
		for i, v := range states[j] {
			for k := i + 1; k <= len(pos); k++ {
				if *laps[pos[k-1]].ref != step.Index {
					break
				}
				done := 0
				if hard {
					var sum float64
					ok := true
					for _, l := range pos[i:k] {
						amount := laps[l].timer
						if p.DurationType == "distance" {
							amount = laps[l].distance
						}
						if !numeric(amount) {
							ok = false
							break
						}
						sum += *amount
					}
					if ok && p.complete(sum) {
						done = 1
					}
				}
				improve(next, k, state{v.cost + k - i - 1, v.lo + done, v.hi + done, i})
			}
			improve(next, i, state{v.cost + omit, v.lo, v.hi, i})
		}
	}
	best, end, lo, hi := math.MaxInt, -1, 0, 0
	for j, l := range states {
		if v, ok := l[len(pos)]; ok {
			if v.cost < best {
				best, end, lo, hi = v.cost, j, v.lo, v.hi
			} else if v.cost == best {
				lo = min(lo, v.lo)
				hi = max(hi, v.hi)
			}
		}
	}
	if end < 0 {
		a.err = "LAP_STEP_ORDER_MISMATCH"
		return a
	}
	if lo != hi {
		a.err = "LAP_ALIGNMENT_AMBIGUOUS"
		return a
	}
	a.assigned = make([][]int, len(steps))
	i := len(pos)
	for j := end - 1; j >= 0; j-- {
		prev := states[j+1][i].previous
		if prev == i {
			a.omitted = append(a.omitted, j)
			if _, ok := work[j]; !ok {
				a.flags = append(a.flags, "NONWORK_STEP_OMITTED")
			}
		} else {
			a.assigned[j] = pos[prev:i]
			if i-prev > 1 {
				a.flags = append(a.flags, "LAP_SPLIT_MERGED")
			}
		}
		i = prev
	}
	for j := end; j < len(steps); j++ {
		a.tail = append(a.tail, j)
	}
	return a
}
