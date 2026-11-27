package garmincli

import (
	"context"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/replay"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
)

// SourceRefresh constructs the in-transaction callback shared by the exporter and worker.
func SourceRefresh(now func() time.Time, runs refresh.RunMetrics) replay.Refresh {
	if runs == nil {
		return nil
	}
	if now == nil {
		now = time.Now
	}
	return func(ctx context.Context, tx pgx.Tx, scope replay.RefreshScope) error {
		at := now().UTC()
		keys, completeCoverage, err := scopeKeys(ctx, tx, scope)
		if err != nil {
			return err
		}
		if len(keys) == 0 && completeCoverage {
			keys = []string{"revision"}
		}
		return refresh.Source(ctx, tx, keys, at, runs)
	}
}

func scopeKeys(ctx context.Context, tx pgx.Tx, scope replay.RefreshScope) ([]string, bool, error) {
	var keys []string
	for id := range scope.Activities {
		keys = append(keys, "activity:"+id.String())
	}
	for _, day := range scope.AffectedDates {
		keys = append(keys, "date:"+day)
	}
	for _, day := range scope.RecoveryDates {
		keys = append(keys, "recovery_dates:"+day)
	}
	var complete bool
	if len(scope.CoverageIDs) > 0 {
		// In this writer transaction, each changed interval was previously absent or partial.
		// Only dates newly added to the union of complete activity coverage affect metrics.
		var days []string
		err := tx.QueryRow(ctx, `WITH complete AS (
 SELECT id,start_date,end_date FROM coverage_intervals
 WHERE dataset='activities' AND status='complete' AND fully_enumerated
), changed AS (SELECT * FROM complete WHERE id=ANY($1::uuid[])),
 days AS (SELECT DISTINCT c.start_date + n AS day FROM changed c
 CROSS JOIN LATERAL generate_series(0,c.end_date-c.start_date) n)
 SELECT EXISTS(SELECT FROM changed), ARRAY(SELECT day::text FROM days
 WHERE NOT EXISTS(SELECT FROM complete c WHERE NOT(c.id=ANY($1::uuid[]))
 AND day BETWEEN c.start_date AND c.end_date) ORDER BY day)`, scope.CoverageIDs).Scan(&complete, &days)
		if err != nil {
			return nil, false, err
		}
		for _, day := range days {
			keys = append(keys, "coverage_date:"+day)
		}
	}
	slices.Sort(keys)
	return slices.Compact(keys), complete, nil
}
