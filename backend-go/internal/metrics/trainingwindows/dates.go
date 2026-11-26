// Package trainingwindows selects persisted local-date windows affected by a change.
package trainingwindows

import (
	"context"
	"fmt"
	"regexp"
	"slices"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
)

var windowKey = regexp.MustCompile(`^w([0-9]+):([0-9]{4}-[0-9]{2}-[0-9]{2})(?::(?:run|strength))?$`)

type Targets struct {
	Broad                bool
	Since                string
	Dates, CoverageDates []string
	HasActivities        bool
}
type Selection struct {
	Training, SpacingOnly []string
}
type stored struct{ metric, key string }

var widths = map[string][]int{
	"run_volume_frequency": {7, 14, 28, 56, 84}, "long_run_exposure": {7, 14, 28, 56, 84}, "session_rpe_load": {7, 14, 28, 56, 84},
	"intensity_time_distribution": {7, 14, 28, 56, 84}, "symptom_response_timeline": {28}, "recovery_multisignal_summary": {7},
	"hard_session_spacing": {14}, "aerobic_efficiency": {28, 84},
}

func keys(set map[string]bool) []string {
	days := make([]string, 0, len(set))
	for k := range set {
		days = append(days, k)
	}
	slices.Sort(days)
	return days
}

func within(days []string, first, last time.Time) bool {
	low, high := first.Format(time.DateOnly), last.Format(time.DateOnly)
	return slices.ContainsFunc(days, func(day string) bool { return low <= day && day <= high })
}

func selectDates(records []stored, target Targets, today string) (Selection, error) {
	all := map[string]bool{today: true}
	spacing := map[string]bool{}
	for _, r := range records {
		parts := windowKey.FindStringSubmatch(r.key)
		if parts == nil {
			continue
		}
		end, err := time.Parse(time.DateOnly, parts[2])
		if err != nil {
			return Selection{}, err
		}
		width, err := strconv.Atoi(parts[1])
		if err != nil {
			return Selection{}, err
		}
		if r.metric == "run_volume_frequency" {
			width *= 2
		}
		first := end.AddDate(0, 0, 1-width)
		switch {
		case target.Broad, target.Since != "" && parts[2] >= target.Since, within(target.Dates, first, end),
			r.metric == "long_run_exposure" && within(target.CoverageDates, first.AddDate(0, 0, -30), end),
			r.metric == "hard_session_spacing" && within(target.Dates, end.AddDate(0, 0, -14), end.AddDate(0, 0, 14)):
			all[parts[2]] = true
		case r.metric == "hard_session_spacing" && len(target.CoverageDates) > 0 && target.HasActivities:
			spacing[parts[2]] = true
		}
	}
	for day := range all {
		delete(spacing, day)
	}
	return Selection{Training: keys(all), SpacingOnly: keys(spacing)}, nil
}

func current(ctx context.Context, tx pgx.Tx) ([]stored, error) {
	registered := make([]string, 0, len(widths))
	for id := range widths {
		registered = append(registered, id)
	}
	rows, err := tx.Query(ctx, `SELECT metric_id,subject_key FROM metric_results WHERE subject_type='window' AND is_current AND method_version='v1' AND metric_id=ANY($1)`, registered)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (stored, error) {
		var s stored
		err := r.Scan(&s.metric, &s.key)
		return s, err
	})
}

// Select returns full training dates and the additional spacing-only dates affected by coverage.
func Select(ctx context.Context, tx pgx.Tx, target Targets, today string) (Selection, error) {
	for _, day := range append(append(slices.Clone(target.Dates), target.CoverageDates...), today) {
		if _, err := time.Parse(time.DateOnly, day); err != nil {
			return Selection{}, err
		}
	}
	if target.Since != "" {
		if _, err := time.Parse(time.DateOnly, target.Since); err != nil {
			return Selection{}, err
		}
	}
	records, err := current(ctx, tx)
	if err != nil {
		return Selection{}, err
	}
	return selectDates(records, target, today)
}

// Complete reports whether every registered output for a training day is current.
func Complete(ctx context.Context, tx pgx.Tx, day string) (bool, error) {
	if _, err := time.Parse(time.DateOnly, day); err != nil {
		return false, err
	}
	records, err := current(ctx, tx)
	if err != nil {
		return false, err
	}
	known := map[stored]bool{}
	for _, r := range records {
		known[r] = true
	}
	for metric, windows := range widths {
		for _, width := range windows {
			key := fmt.Sprintf("w%d:%s", width, day)
			if metric == "session_rpe_load" {
				if !known[stored{metric, key + ":run"}] || !known[stored{metric, key + ":strength"}] {
					return false, nil
				}
			} else if !known[stored{metric, key}] {
				return false, nil
			}
		}
	}
	return true, nil
}
