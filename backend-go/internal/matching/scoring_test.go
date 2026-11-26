package matching

import (
	"math"
	"slices"
	"testing"
)

func TestRoundedCostMatchesPython(t *testing.T) {
	for _, tc := range []struct{ cost, want float64 }{
		{1.2345, 1.234}, {2.6755, 2.675}, {0.0005, 0.001},
		{0.0625, 0.062}, {0.1875, 0.188},
	} {
		if got := roundedCost(tc.cost); got != tc.want {
			t.Errorf("roundedCost(%v) = %v, want %v", tc.cost, got, tc.want)
		}
	}
}

func TestScoringAcrossAssignments(t *testing.T) {
	num := func(v float64) *float64 { return &v }
	plans := []Plan{{PlannedDistanceM: num(1000)}, {PlannedDistanceM: num(3000)}}
	subjects := []Subject{{DistanceM: num(3000)}, {DistanceM: num(1000)}, {DistanceM: num(9000)}}
	winners, costs := chooseDay(plans, subjects, "run")
	if !slices.Equal(winners, []int{1, 0}) || costs != nil {
		t.Fatalf("winners %v costs %v", winners, costs)
	}
	// Both plans prefer the same recording. Two equally good permutations
	// must remain ambiguous, with costs aligned to original subject order.
	winners, costs = chooseDay([]Plan{plans[0], plans[0]}, subjects, "run")
	if winners != nil || len(costs) != 2 || len(costs[0]) != 3 || costs[0][1] != 0 {
		t.Fatalf("winners %v costs %v", winners, costs)
	}
}

func TestWinningMarginBoundary(t *testing.T) {
	one := 1.0
	plan := []Plan{{PlannedDurationS: &one}}
	for _, tc := range []struct {
		ratio float64
		wins  bool
	}{
		{1.5, true}, {math.Nextafter(1.5, 1), false},
	} {
		winners, _ := chooseDay(plan, []Subject{{TimerS: &one}, {TimerS: &tc.ratio}}, "run")
		if (len(winners) > 0) != tc.wins {
			t.Errorf("ratio %.17g winners %v", tc.ratio, winners)
		}
	}
}

func TestFragmentBoundaries(t *testing.T) {
	for _, tc := range []struct {
		kind            string
		timer, distance float64
		want            bool
	}{
		{"run", 300, 400, false}, {"run", 299, 400, true}, {"run", 300, 399, true}, {"strength", 12, 0, false},
	} {
		if got := fragment(Subject{Kind: tc.kind, TimerS: &tc.timer, DistanceM: &tc.distance}); got != tc.want {
			t.Errorf("%s timer=%g distance=%g: fragment=%t", tc.kind, tc.timer, tc.distance, got)
		}
	}
}

// A nonzero best score can leave the difference just below the threshold.
// Scores are compared before rounding them for the candidate response.
func TestMarginAfterSubtractingBestCost(t *testing.T) {
	planned, first, second := 1000.0, 1250.0, 1875.0
	winners, costs := chooseDay([]Plan{{PlannedDurationS: &planned}}, []Subject{{TimerS: &first}, {TimerS: &second}}, "run")
	if winners != nil || len(costs) != 1 {
		t.Fatalf("expected ambiguous scores, got winners %v, costs %v", winners, costs)
	}
}
