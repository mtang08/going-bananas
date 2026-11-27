package activityhttp

import (
	"context"
	"net/http"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
)

func (h Handler) longRuns(ctx context.Context, tx pgx.Tx, r *http.Request, now time.Time, loc *time.Location) (any, error) {
	first, last, err := metricDates(r, true, loc)
	if err != nil {
		return nil, err
	}
	if first.After(last) {
		return nil, &problem{422, "invalid_date_window", "Invalid date window", nil}
	}
	rows, err := tx.Query(ctx, `SELECT id::text FROM activities WHERE start_at >= $1 AND start_at < $2 ORDER BY start_at,id`, first, last.AddDate(0, 0, 1))
	if err != nil {
		return nil, err
	}
	keys, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, err
	}
	result := []object{}
	for _, key := range keys {
		row, err := refresh.ReadResult(ctx, tx, "long_run_exposure", key, now)
		if err != nil {
			return nil, err
		}
		value, _ := row["value"].(map[string]any)
		if value["classification"] == "long" {
			timestamps(row, "window_start", "window_end", "calculated_at")
			result = append(result, row)
		}
	}
	slices.SortFunc(result, func(a, b object) int {
		aTime, aOk := a["window_start"].(string)
		bTime, bOk := b["window_start"].(string)
		if aOk != bOk {
			if aOk {
				return -1
			}
			return 1
		}
		at, _ := time.Parse(time.RFC3339Nano, aTime)
		bt, _ := time.Parse(time.RFC3339Nano, bTime)
		if c := at.Compare(bt); c != 0 {
			return c
		}
		return strings.Compare(a["subject_key"].(string), b["subject_key"].(string))
	})
	return result, nil
}
