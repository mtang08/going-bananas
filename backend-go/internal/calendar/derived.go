package calendar

import (
	"bytes"
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/matching/rematch"
	"github.com/mtang08/going-bananas/backend-go/internal/prompts"
	"slices"
	"time"
)

// CompletionTargets describes the scope after rematching, before metric computation.
type CompletionTargets struct {
	Change     CompletionChange
	ManualOnly bool
	Dates      []string
	Matched    []uuid.UUID
}
type RefreshMetrics func(context.Context, pgx.Tx, CompletionTargets) error

// DerivedRefresh runs the ordered rematch, metric and prompt stages in a single transaction.
func DerivedRefresh(now time.Time, metrics RefreshMetrics) RefreshCompletion {
	return func(ctx context.Context, tx pgx.Tx, change CompletionChange) error {
		if metrics == nil {
			return errors.New("completion metric refresh is required")
		}
		targets, err := reconcile(ctx, tx, change, now)
		if err != nil {
			return err
		}
		if err = metrics(ctx, tx, targets); err != nil {
			return err
		}
		_, err = prompts.Generate(ctx, tx, now)
		return err
	}
}

func selfReported(row *db.SessionCompletion) bool {
	return row == nil || (row.MatchMethod == "user_marked" && row.Status == "completed_as_planned" && !hasRecording(row))
}
func reconcile(ctx context.Context, tx pgx.Tx, change CompletionChange, now time.Time) (CompletionTargets, error) {
	targets := CompletionTargets{Change: change}
	var reconciled string
	if selfReported(change.Before) && selfReported(change.After) && change.Displaced == nil {
		targets.ManualOnly = true
		if change.PlanDay.Valid {
			reconciled = change.PlanDay.Time.Format(time.DateOnly)
			matched, err := rematch.Dates(ctx, tx, []string{reconciled}, now)
			if err != nil {
				return targets, err
			}
			targets.Matched = matched
		}
		if len(targets.Matched) == 0 {
			return targets, nil
		}
		targets.ManualOnly = false
	}
	var scope PlanScope
	for _, c := range []*CompletionChange{&change, change.Displaced} {
		if c == nil {
			continue
		}
		scope.PlanUIDs = append(scope.PlanUIDs, c.SessionUID)
		if c.PreviousRecordingDay.Valid {
			scope.Dates = append(scope.Dates, c.PreviousRecordingDay.Time.Format(time.DateOnly))
		}
		if c.RecordingDay.Valid {
			scope.Dates = append(scope.Dates, c.RecordingDay.Time.Format(time.DateOnly))
		}
	}
	var err error
	targets.Dates, err = scopeDays(ctx, tx, scope)
	if err != nil {
		return targets, err
	}
	matched, err := rematchScope(ctx, tx, targets.Dates, reconciled, now)
	if err != nil {
		return targets, err
	}
	targets.Matched = append(targets.Matched, matched...)
	slices.SortFunc(targets.Matched, func(a, b uuid.UUID) int { return bytes.Compare(a[:], b[:]) })
	targets.Matched = slices.Compact(targets.Matched)
	return targets, nil
}
