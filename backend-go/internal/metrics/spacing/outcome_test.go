package spacing

import (
	"slices"
	"testing"
	"time"
)

func TestNearestExposureBeyondWindowAndUncertainDay(t *testing.T) {
	asOf := time.Date(2026, 3, 8, 0, 0, 0, 0, time.UTC)
	zone, err := time.LoadLocation("America/New_York")
	if err != nil {
		t.Fatal(err)
	}
	local := time.Date(2026, 3, 8, 0, 0, 0, 0, zone)
	prior := local.Add(-10 * 24 * time.Hour)
	later := local.Add(9 * 24 * time.Hour)
	entries := []exposure{
		{Key: "prior", Day: "2026-02-26", Classes: []string{"quality"}, StartLow: prior, StartHigh: prior, EndLow: prior, EndHigh: prior},
		{Key: "today", Day: "2026-03-08", Classes: []string{"quality"}, StartLow: local, StartHigh: local.AddDate(0, 0, 1), EndLow: local, EndHigh: local.AddDate(0, 0, 1)},
		{Key: "today", Day: "2026-03-08", Classes: []string{"long"}},
		{Key: "later", Day: "2026-03-17", Classes: []string{"lower_body_strength"}, StartLow: later, StartHigh: later, EndLow: later, EndHigh: later},
	}
	value := outcome(entries, asOf)
	seq := value["sequence"].([]object)
	if len(seq) != 1 || !slices.Equal(seq[0]["classes"].([]string), []string{"long", "quality"}) {
		t.Fatal(seq)
	}
	sessions := value["sessions"].([]object)
	g := sessions[0]["hours_since"].(object)["quality"].(object)
	if g["low"] != 240.0 || g["high"] != 263.0 || g["confidence"] != "low" {
		t.Fatal(g)
	}
	if len(value["gaps"].([]object)) != 4 {
		t.Fatal(value["gaps"])
	}
}
