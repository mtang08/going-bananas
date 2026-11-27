package drafts

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/athleteprofile"
	"github.com/mtang08/going-bananas/backend-go/internal/calendar"
	"github.com/mtang08/going-bananas/backend-go/internal/calendarstructure"
)

func reducesDose(a, b sessionFields) bool {
	if a.LocalDate != b.LocalDate || a.Kind != b.Kind || a.Recipe != b.Recipe || a.Placeholder != b.Placeholder || a.Custom != b.Custom || a.Intent != b.Intent {
		return false
	}
	if b.Duration != nil && a.Duration == nil || b.Distance != nil && a.Distance == nil || raisesDose(a, b) {
		return false
	}
	return !sameJSON(a.raw["planned_distance_m"], b.raw["planned_distance_m"]) || !sameJSON(a.raw["planned_duration_s"], b.raw["planned_duration_s"]) || !sameJSON(a.Structure, b.Structure)
}

// CalendarPrescription checks the athlete's persisted running restrictions and
// interruption for a manual edit or rollback. Only a manual edit can reduce
// the dose of an existing prescription that is already outside a restriction.
func CalendarPrescription(ctx context.Context, tx pgx.Tx, today string, allowReduction bool) (calendar.CheckPrescription, error) {
	var facts struct {
		Restriction  *restriction  `json:"running_restriction"`
		Interruption *interruption `json:"running_interruption"`
	}
	err := tx.QueryRow(ctx, "SELECT facts FROM profile_versions ORDER BY version DESC LIMIT 1").Scan(&facts)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, err
	}
	var r RuleContext
	r.Restriction = facts.Restriction
	r.Interruption = facts.Interruption
	r.Today = today
	return prescriptionCheck(r, allowReduction), nil
}
func prescriptionCheck(rules RuleContext, allowReduction bool) calendar.CheckPrescription {
	return func(before, after json.RawMessage, legacy bool) error {
		var old, next sessionFields
		if err := json.Unmarshal(after, &next); err != nil {
			return err
		}
		hasHead := string(before) != "null"
		if hasHead {
			if err := json.Unmarshal(before, &old); err != nil {
				return err
			}
		}
		if has(next.Structure) {
			if _, ok := calendarstructure.Expand(next.Structure); !ok {
				return &Error{"invalid_structure", "Invalid session structure", 422}
			}
		}
		reducesExistingConflict := allowReduction && hasHead && reducesDose(next, old) && restrictionConflict(rules.Restriction, old, sessionFields{}, false) != ""
		if msg := restrictionConflict(rules.Restriction, next, old, hasHead); msg != "" && !reducesExistingConflict {
			return &Error{"running_restriction", msg, 422}
		}
		if x := rules.Interruption; x != nil && next.Kind == "run" && next.LocalDate >= rules.Today && next.LocalDate >= x.Start && (x.Return == "" || next.LocalDate < x.Return) && (!hasHead || old.Kind != "run" || old.LocalDate != next.LocalDate || raisesDose(next, old)) {
			return &Error{"running_interruption", "Running is unavailable on " + next.LocalDate + ". Remove the run or move it outside the confirmed interruption.", 422}
		}
		return nil
	}
}

// CalendarConflict returns the same prescription conflict shown during review.
func CalendarConflict(limit *athleteprofile.RunningRestriction, row json.RawMessage) (string, error) {
	if limit == nil {
		return "", nil
	}
	r := restriction{Start: limit.StartsOn, Pause: limit.PauseRunning, NoQuality: limit.NoQuality, MaxDistance: limit.MaxDistanceM, MaxDuration: limit.MaxDurationS}
	if limit.EndsOn != nil {
		r.End = *limit.EndsOn
	}
	if limit.ReviewOn != nil {
		r.Review = *limit.ReviewOn
	}
	var session sessionFields
	if err := json.Unmarshal(row, &session); err != nil {
		return "", err
	}
	return restrictionConflict(&r, session, sessionFields{}, false), nil
}
