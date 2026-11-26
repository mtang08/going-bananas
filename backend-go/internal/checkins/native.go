package checkins

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/exceptions"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
)

// NewStore connects both write paths to the native detector and ordered source refresh.
func NewStore(pool *pgxpool.Pool, now func() time.Time, runs refresh.RunMetrics) Store {
	if now == nil {
		now = time.Now
	}
	return Store{Pool: pool, Now: now, Detect: exceptions.Detect, Refresh: func(ctx context.Context, tx pgx.Tx, scopes []string) error {
		return refresh.Source(ctx, tx, scopes, now().UTC(), runs)
	}}
}
