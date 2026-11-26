package snapshotreads

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
)

type StrengthInputs struct {
	Confirmed []map[string]any
	Omissions []map[string]any
}

// InputReaders supplies the owning domains' projections within the caller's transaction.
// Week receives the Monday to load and the snapshot's as-of date independently.
type InputReaders struct {
	Week       func(ctx context.Context, tx pgx.Tx, weekStart, asOf string, now time.Time) (map[string]any, error)
	ReturnView func(ctx context.Context, tx pgx.Tx, asOf string) (map[string]any, error)
	Strength   func(ctx context.Context, tx pgx.Tx, operation, asOf string, now time.Time) (StrengthInputs, error)
}

type Inputs struct {
	AsOf string `json:"as_of"`
	Now  string `json:"now"`
	ProfileMetadata
	Planning
	Block
	ActivityInputs
	ExceptionContext
	TravelContext
	Checkins                  []map[string]any `json:"checkins"`
	Prompts                   []map[string]any `json:"prompts"`
	WeeklyDigest              []map[string]any `json:"weekly_digest"`
	RunningInterruption       map[string]any   `json:"running_interruption"`
	ConfirmedStrengthSessions []map[string]any `json:"confirmed_strength_sessions"`
	AcceptedStrengthOmissions []map[string]any `json:"accepted_strength_omissions"`
}

// LoadInputs reads display data after the caller has prepared metrics/detector state.
// Use the same repeatable-read transaction or locked transaction as the evidence reader.
func LoadInputs(ctx context.Context, tx pgx.Tx, operation, asOf string, now time.Time, deps InputReaders) (Inputs, error) {
	var out Inputs
	if deps.Week == nil || deps.Strength == nil {
		return Inputs{}, errors.New("weekly and strength snapshot readers are required")
	}
	day, err := time.Parse(time.DateOnly, asOf)
	if err != nil {
		return Inputs{}, err
	}
	profile, err := LoadProfile(ctx, tx, asOf)
	if err != nil {
		return Inputs{}, err
	}
	out.AsOf, out.Now, out.ProfileMetadata = asOf, feedbackInstant(now), profile.ProfileMetadata
	zone, err := time.LoadLocation(profile.Timezone)
	if err != nil {
		return Inputs{}, err
	}
	if out.Planning, err = LoadPlanning(ctx, tx, asOf); err != nil {
		return Inputs{}, err
	}
	if out.ActivityInputs, err = LoadActivity(ctx, tx, asOf, zone); err != nil {
		return Inputs{}, err
	}
	if out.Checkins, err = Checkins(ctx, tx, now, zone); err != nil {
		return Inputs{}, err
	}
	if out.Prompts, err = Prompts(ctx, tx, now); err != nil {
		return Inputs{}, err
	}
	if out.Block, err = LoadBlock(ctx, tx, asOf); err != nil {
		return Inputs{}, err
	}
	if out.ExceptionContext, err = LoadExceptions(ctx, tx, asOf, now); err != nil {
		return Inputs{}, err
	}
	if out.TravelContext, err = LoadTravel(ctx, tx, asOf, zone); err != nil {
		return Inputs{}, err
	}
	monday := day.AddDate(0, 0, -((int(day.Weekday()) + 6) % 7))
	for _, week := range []time.Time{monday.AddDate(0, 0, -7), monday} {
		data, err := deps.Week(ctx, tx, week.Format(time.DateOnly), asOf, now)
		if err != nil {
			return Inputs{}, err
		}
		if data == nil {
			return Inputs{}, errors.New("weekly reader returned no digest")
		}
		out.WeeklyDigest = append(out.WeeklyDigest, data)
	}
	if profile.hasInterruption {
		if deps.ReturnView == nil {
			return Inputs{}, errors.New("return-view reader required for recorded running interruption")
		}
		view, err := deps.ReturnView(ctx, tx, asOf)
		if err != nil {
			return Inputs{}, err
		}
		if err = addReturnContext(view, day, out.ActivityInputs); err != nil {
			return Inputs{}, err
		}
		out.RunningInterruption = view
	}
	strength, err := deps.Strength(ctx, tx, operation, asOf, now)
	if err != nil {
		return Inputs{}, err
	}
	if strength.Confirmed == nil || strength.Omissions == nil {
		return Inputs{}, errors.New("strength reader must return confirmed sessions and accepted omissions")
	}
	out.ConfirmedStrengthSessions, out.AcceptedStrengthOmissions = strength.Confirmed, strength.Omissions
	return out, nil
}

const returnGuidance = "The latest recorded run is context, not proof of a comparable easy dose or complete training history. " +
	"Affected past runs are review only; propose edits only from today onward and preserve protected records. " +
	"Omit unreachable runs, preserve confirmed commitments and use the usual running rhythm. " +
	"The first run is only an eligible candidate for review, not clearance; review before progressing when readiness or coverage is uncertain."

func addReturnContext(view map[string]any, day time.Time, activity ActivityInputs) error {
	episode, _ := view["interruption"].(map[string]any)
	start, _ := episode["starts_on"].(string)
	if _, err := time.Parse(time.DateOnly, start); err != nil {
		return errors.New("return-view reader omitted a valid interruption start")
	}
	var latest map[string]any
	for _, r := range activity.Runs {
		local := r["local_date"].(string)
		if local >= start {
			continue
		}
		// LoadActivity orders by UTC start and ID. Preserve Python's first
		// candidate on a tie, including during a daylight-saving transition.
		if latest == nil || local > latest["local_date"].(string) || local == latest["local_date"] && r["start_at"] != latest["start_at"] {
			latest = r
		}
	}
	view["latest_recorded_run"] = nil
	if latest != nil {
		run := map[string]any{}
		for _, k := range []string{"activity_id", "local_date", "sport", "timer_s", "distance_m", "rpe", "rpe_source"} {
			run[k] = latest[k]
		}
		view["latest_recorded_run"] = run
	}
	view["activity_history_coverage"] = "unknown"
	// Coverage intervals are inclusive and LoadActivity returns them in start-date order.
	first := day.AddDate(0, 0, -120).Format(time.DateOnly)
	for _, row := range activity.Coverage {
		if row["dataset"] != "activities" || row["status"] != "complete" || row["fully_enumerated"] != true {
			continue
		}
		if row["start_date"].(string) > first {
			break
		}
		end := row["end_date"].(string)
		if end >= day.Format(time.DateOnly) {
			view["activity_history_coverage"] = "complete"
			break
		}
		if end >= first {
			t, err := time.Parse(time.DateOnly, end)
			if err != nil {
				return err
			}
			first = t.AddDate(0, 0, 1).Format(time.DateOnly)
		}
	}
	view["guidance"] = returnGuidance
	return nil
}
