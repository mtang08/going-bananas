package refresh

import (
	"context"
	"maps"
	"slices"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/matching/rematch"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/trainingwindows"
	"github.com/mtang08/going-bananas/backend-go/internal/prompts"
)

// Source reconciles provider and check-in observations on the caller's locked writer transaction.
// Calendar edits use PlanMetrics and CompletionMetrics, which handle manual overrides.
func Source(ctx context.Context, tx pgx.Tx, scopes []string, now time.Time, runs RunMetrics) error {
	if len(scopes) == 0 {
		return nil
	}
	b, err := newBatch(ctx, tx, now, runs)
	if err != nil {
		return err
	}
	s, err := b.expand(scopes)
	if err != nil {
		return err
	}
	today := now.In(b.zone).Format(time.DateOnly)
	revisionOnly := len(scopes) == 1 && scopes[0] == "revision"
	recoveryOnly := len(s.recovery) > 0 && len(s.dates)+len(b.explicit)+len(s.plans)+len(s.strength)+len(s.manual) == 0 && !b.broad && s.since == ""
	cold := false
	if revisionOnly || recoveryOnly {
		complete, err := trainingwindows.Complete(ctx, tx, today)
		if err != nil {
			return err
		}
		cold = !complete
	}
	if !revisionOnly || cold {
		var matched []uuid.UUID
		if !recoveryOnly || cold {
			days := maps.Clone(s.dates)
			days[today] = true
			matched, err = rematch.Dates(ctx, tx, slices.Sorted(maps.Keys(days)), now)
			if err != nil {
				return err
			}
		}
		if err = b.scopeMetrics(s, matched, cold); err != nil {
			return err
		}
	}
	_, err = prompts.Generate(ctx, tx, now)
	return err
}
