package trainingwindows

import (
	"slices"
	"testing"
)

func TestCoverageAndOrdinaryChanges(t *testing.T) {
	rows := []stored{{"run_volume_frequency", "w7:2026-02-14"}, {"long_run_exposure", "w14:2026-03-15"}, {"hard_session_spacing", "w14:2026-01-20"}, {"hard_session_spacing", "w14:2025-12-01"}, {"session_rpe_load", "w7:2026-05-10:strength"}, {"recovery_multisignal_summary", "night:2026-05-11"}}
	selected, err := selectDates(rows, Targets{Dates: []string{"2026-02-01"}, CoverageDates: []string{"2026-02-01"}, HasActivities: true}, "2026-06-01")
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(selected.Training, []string{"2026-01-20", "2026-02-14", "2026-03-15", "2026-06-01"}) || !slices.Equal(selected.SpacingOnly, []string{"2025-12-01"}) {
		t.Fatal(selected)
	}
}
