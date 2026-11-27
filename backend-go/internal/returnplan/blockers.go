package returnplan

import (
	"context"
	"encoding/json"
	"slices"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/athleteprofile"
	"github.com/mtang08/going-bananas/backend-go/internal/calendarstructure"
)

type trip struct {
	Start       string
	End, Access *string
	Days        []struct{ Date, Availability string }
}

func confirmedTrips(ctx context.Context, tx pgx.Tx, start, end string) ([]trip, error) {
	rows, err := tx.Query(ctx, `SELECT start_date::text,end_date::text,running_access,day_availability
		FROM trips WHERE status='confirmed' AND start_date <= $2::date AND (end_date IS NULL OR end_date >= $1::date)`, start, end)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowToStructByPos[trip])
}

const reducedTravel = "Review the reduced or unavailable travel day on {day} before keeping that run."
const unknownTravel = "Confirm running access and availability during the trip on {day} before keeping that run."

func travelBlock(trips []trip, day string) string {
	reason := ""
	for _, t := range trips {
		if day < t.Start || (t.End != nil && day > *t.End) {
			continue
		}
		if t.Access != nil && (*t.Access == "limited" || *t.Access == "none") {
			return reducedTravel
		}
		status := ""
		for _, entry := range t.Days {
			if entry.Date == day {
				status = entry.Availability
				break
			}
		}
		if status == "unavailable" || status == "reduced" {
			return reducedTravel
		}
		if status != "normal" {
			reason = unknownTravel
		}
	}
	return reason
}

func exceedsCap(declared, cap *int, steps []calendarstructure.Step, unit string) bool {
	if cap == nil {
		return false
	}
	if declared != nil && *declared > *cap {
		return true
	}
	var total float64
	complete := len(steps) > 0
	for _, s := range steps {
		if s.DurationType == unit {
			total += s.DurationValue
			continue
		}
		if t := s.Target; t != nil && t.Modality == "speed" {
			if unit == "distance" {
				total += s.DurationValue * *t.High
				continue
			}
			if *t.Low > 0 {
				total += s.DurationValue / *t.Low
				continue
			}
			if *t.High > 0 {
				total += s.DurationValue / *t.High
			}
		}
		complete = false
	}
	return total > float64(*cap) || (declared == nil && !complete)
}

func harderThanEasy(r run, steps []calendarstructure.Step) bool {
	if r.Placeholder || r.Custom || r.Recipe == nil || !slices.Contains([]string{"REC001", "REC002", "REC007"}, *r.Recipe) {
		return true
	}
	work := 0
	for _, s := range steps {
		if s.Type == "work" {
			work++
		}
		if s.Type == "recovery" || work > 1 {
			return true
		}
	}
	var brief struct {
		Effort struct {
			Low  *int `json:"rpe_low"`
			High *int `json:"rpe_high"`
		}
	}
	if json.Unmarshal(r.Brief, &brief) != nil || brief.Effort.Low == nil || brief.Effort.High == nil {
		return false
	}
	ceiling := 4
	if *r.Recipe == "REC002" {
		ceiling = 5
	}
	return *brief.Effort.High > ceiling
}

func blocker(r run, limit *athleteprofile.RunningRestriction, trips []trip) string {
	steps, _ := calendarstructure.Expand(r.Structure)
	if limit != nil && r.Day >= limit.StartsOn && (limit.EndsOn == nil || r.Day <= *limit.EndsOn) {
		if limit.PauseRunning || (limit.NoQuality && harderThanEasy(r, steps)) || exceedsCap(r.Distance, limit.MaxDistanceM, steps, "distance") || exceedsCap(r.Duration, limit.MaxDurationS, steps, "time") {
			return "Review the run on {day} against the recorded running limits."
		}
	}
	if reason := travelBlock(trips, r.Day); reason != "" {
		return reason
	}
	if r.Recipe == nil || *r.Recipe != "REC001" || harderThanEasy(r, steps) {
		return "Review the session and choose an easy return option for {day}."
	}
	if (r.Duration == nil || *r.Duration <= 0) && (r.Distance == nil || *r.Distance <= 0) && (len(r.Structure) == 0 || string(r.Structure) == "null" || string(r.Structure) == "[]") {
		return "Confirm the planned duration, distance, or workout steps before keeping the run on {day}."
	}
	return ""
}
