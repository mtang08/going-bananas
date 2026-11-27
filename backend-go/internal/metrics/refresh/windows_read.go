package refresh

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/spacing"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/trainingwindows"
)

// ReadWindows returns matching current rows and previews any missing keys from source evidence.
func ReadWindows(ctx context.Context, tx pgx.Tx, metric string, keys []string, asOf, now time.Time) (map[string]map[string]any, error) {
	config, ok := configs()[metric]
	if !ok {
		return nil, fmt.Errorf("unregistered window metric %q", metric)
	}
	hash, err := metrics.Digest(config)
	if err != nil {
		return nil, err
	}
	rows, err := tx.Query(ctx, `SELECT to_jsonb(m) FROM metric_results m WHERE metric_id=$1 AND method_version=$2 AND config_hash=$3 AND subject_key=ANY($4) AND is_current`, metric, version(metric), hash, keys)
	if err != nil {
		return nil, err
	}
	current, err := pgx.CollectRows(rows, pgx.RowTo[map[string]any])
	if err != nil {
		return nil, err
	}
	out := map[string]map[string]any{}
	for _, item := range current {
		out[item["subject_key"].(string)] = item
	}
	if len(out) == len(keys) {
		return out, nil
	}
	var calculated map[string]metrics.Result
	if metric == "hard_session_spacing" {
		r, e := spacing.Calculate(ctx, tx, asOf)
		if e != nil {
			return nil, e
		}
		calculated = map[string]metrics.Result{r.SubjectKey: r}
	} else {
		calculated, err = trainingwindows.Calculate(ctx, tx, metric, asOf)
		if err != nil {
			return nil, err
		}
	}
	for _, key := range keys {
		if out[key] != nil {
			continue
		}
		r, ok := calculated[key]
		if !ok {
			continue
		}
		start, end := r.WindowStart.UTC(), r.WindowEnd.UTC()
		r.WindowStart, r.WindowEnd = &start, &end
		out[key], err = metrics.Preview(r, now)
		if err != nil {
			return nil, err
		}
	}
	return out, nil
}
