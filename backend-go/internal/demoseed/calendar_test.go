package demoseed

import (
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestDemoPlanWeekdayRotation(t *testing.T) {
	// The Python bootstrap_plan/routine_occurrences projections for each startup
	// weekday. The first, partial week starts with the first effective routine slot.
	cases := []struct{ runs, strength string }{
		{"QEELQEL", "0A,4B,7A,11B"}, {"QELQEEL", "3A,6A,10B,13A"},
		{"QELQELL", "2A,5A,9B,12A"}, {"QLQEELL", "1A,4A,8B,11A"},
		{"QLQELQL", "0A,3A,7B,10A"}, {"LQEELQL", "2A,6B,9A,13B"}, {"LQELQEL", "1A,5B,8A,12B"},
	}
	zone, err := time.LoadLocation("America/New_York")
	if err != nil {
		t.Fatal(err)
	}
	slots := map[string]uuid.UUID{"Full body A": uuid.New(), "Full body B": uuid.New()}
	for i, c := range cases {
		day := time.Date(2026, 3, 2+i, 0, 0, 0, 0, zone)
		var roles strings.Builder
		var strengths []string
		for _, s := range demoPlan(day, day, 1800, 2400, slots) {
			if s.kind == "strength" {
				offset := 0
				for !day.AddDate(0, 0, offset).Equal(s.day) {
					offset++
				}
				strengths = append(strengths, fmt.Sprintf("%d%s", offset, strings.TrimPrefix(s.intent, "Full body ")))
			} else if s.placeholder {
				roles.WriteByte('Q')
			} else if s.recipe == "REC002" {
				roles.WriteByte('L')
			} else {
				roles.WriteByte('E')
			}
		}
		if roles.String() != c.runs || strings.Join(strengths, ",") != c.strength {
			t.Errorf("%s: %s %v", day.Weekday(), roles.String(), strengths)
		}
	}
}
