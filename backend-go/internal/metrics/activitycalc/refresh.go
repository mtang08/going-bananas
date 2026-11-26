// Package activitycalc refreshes the FIT-dependent metrics for one activity.
package activitycalc

import (
	"context"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/aerobic"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/intensity"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/intervals"
	"time"
)

func Refresh(ctx context.Context, tx pgx.Tx, id uuid.UUID, now time.Time) error {
	for _, f := range []func(context.Context, pgx.Tx, uuid.UUID, time.Time) (uuid.UUID, error){intensity.Refresh, intervals.Refresh, aerobic.Refresh} {
		if _, err := f(ctx, tx, id, now); err != nil {
			return err
		}
	}
	return nil
}
