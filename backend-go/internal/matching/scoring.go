package matching

import (
	"math"
	"strconv"
)

func fragment(subject Subject) bool {
	if subject.Kind != "run" {
		return false
	}
	return (subject.TimerS != nil && *subject.TimerS < 300) ||
		(subject.DistanceM != nil && *subject.DistanceM < 400)
}

func logRatioCost(actual, planned *float64) float64 {
	if actual == nil || planned == nil || *actual <= 0 || *planned <= 0 {
		return 0
	}
	return math.Abs(math.Log(*actual / *planned))
}

func pairCost(plan Plan, subject Subject) float64 {
	cost := logRatioCost(subject.TimerS, plan.PlannedDurationS) + logRatioCost(subject.DistanceM, plan.PlannedDistanceM)
	if plan.HasWorkSteps != nil && subject.HasWorkoutSteps != nil && *plan.HasWorkSteps != *subject.HasWorkoutSteps {
		cost += 0.5
	}
	return cost
}

// chooseDay returns either distinct winning subject indexes for all plans, or
// the cost matrix for an ambiguous scored day. Unsupported groups are unscored.
func chooseDay(plans []Plan, subjects []Subject, kind string) ([]int, [][]float64) {
	if len(plans) == 1 && len(subjects) == 1 {
		return []int{0}, nil
	}
	if kind != "run" || len(plans) < 1 || len(plans) > 2 || len(subjects) < 2 || len(subjects) > 3 {
		return nil, nil
	}
	costs := make([][]float64, len(plans))
	for i, plan := range plans {
		costs[i] = make([]float64, len(subjects))
		for j, subject := range subjects {
			costs[i][j] = pairCost(plan, subject)
		}
	}

	// Enumerate the bounded one- and two-plan permutations in index order.
	// Equal scores retain that order and reduce the winning margin to zero.
	best, second := math.Inf(1), math.Inf(1)
	var winner []int
	consider := func(score float64, assignment ...int) {
		if score < best {
			best, second, winner = score, best, assignment
		} else if score < second {
			second = score
		}
	}
	for j, cost := range costs[0] {
		if len(plans) == 1 {
			consider(cost, j)
			continue
		}
		for k, otherCost := range costs[1] {
			if k != j {
				consider(cost+otherCost, j, k)
			}
		}
	}
	if second-best >= math.Log(1.5) {
		return winner, nil
	}
	return nil, costs
}

func roundedCost(cost float64) float64 {
	// Format the exact float at three decimal places. Multiplying by 1000
	// before rounding can move a value onto the wrong side of a decimal tie.
	text := strconv.FormatFloat(cost, 'f', 3, 64)
	rounded, _ := strconv.ParseFloat(text, 64)
	return rounded
}
