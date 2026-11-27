package snapshots

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/exceptions"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
)

// Detector refreshes exception state in the snapshot's transaction.
type Detector func(context.Context, pgx.Tx, time.Time) error

type Builder struct {
	runs   refresh.RunMetrics
	detect Detector
}

func NewBuilder(runs refresh.RunMetrics, detect Detector) *Builder {
	return &Builder{runs: runs, detect: detect}
}

func (b *Builder) Build(ctx context.Context, tx pgx.Tx, operation, asOf string, now time.Time, kbRoot string) (map[string]any, error) {
	return BuildWithPreparation(ctx, tx, operation, asOf, now, kbRoot, b.prepare)
}

func (b *Builder) prepare(ctx context.Context, tx pgx.Tx, operation, asOf string, now time.Time) error {
	day, err := time.Parse(time.DateOnly, asOf)
	if err != nil {
		return err
	}
	needsDetection := operation == exception || operation == postEvent || operation == rolling || operation == blockReview
	if needsDetection && b.detect == nil {
		return errors.New("exception detector required for this snapshot operation")
	}
	if err := refresh.EnsureWindows(ctx, tx, day, now, b.runs); err != nil {
		return err
	}
	days := map[string]int{daily: 3, rolling: 14, quality: 14, blockReview: 28, exception: 3, postEvent: 14}[operation]
	if days != 0 {
		if err := refresh.EnsureNights(ctx, tx, day.AddDate(0, 0, 1-days), day, now); err != nil {
			return err
		}
	}
	if needsDetection {
		return b.detect(ctx, tx, now)
	}
	return nil
}

// Build uses the native per-run and window calculators and exception detector.
func Build(ctx context.Context, tx pgx.Tx, operation, asOf string, now time.Time, kbRoot string) (map[string]any, error) {
	return NewBuilder(nil, func(ctx context.Context, tx pgx.Tx, now time.Time) error {
		_, err := exceptions.Detect(ctx, tx, now)
		return err
	}).Build(ctx, tx, operation, asOf, now, kbRoot)
}
