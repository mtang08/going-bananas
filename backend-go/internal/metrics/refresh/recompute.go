package refresh

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/aerobic"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/intensity"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/intervals"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/trainingwindows"
)

func (b *batch) includes(metric string) bool { return b.filter == nil || b.filter[metric] }

func (b *batch) runSelected(ctx context.Context, tx pgx.Tx, id uuid.UUID, zone string, now time.Time) error {
	for _, name := range []string{"symptom_response_timeline", "long_run_exposure", "session_rpe_load", intervals.ID, intensity.ID, aerobic.ID} {
		if !b.includes(name) {
			continue
		}
		var r *metrics.Result
		var err error
		switch name {
		case intervals.ID:
			r, err = intervals.Calculate(ctx, tx, id)
		case intensity.ID:
			r, err = intensity.Calculate(ctx, tx, id)
		case aerobic.ID:
			r, err = aerobic.Calculate(ctx, tx, id)
		default:
			r, err = trainingwindows.CalculateActivity(ctx, tx, name, id, zone)
		}
		if err != nil {
			return err
		}
		if r == nil {
			_, err = tx.Exec(ctx, `UPDATE metric_results SET is_current=false WHERE metric_id=$1 AND method_version=$2 AND subject_key=$3 AND is_current`, name, version(name), id.String())
		} else {
			_, err = metrics.StoreResult(ctx, tx, *r, now)
		}
		if err != nil {
			return err
		}
	}
	return nil
}

type RecomputeSummary struct {
	Metric   string `json:"metric"`
	Since    string `json:"since"`
	Until    string `json:"until"`
	Subjects int    `json:"subjects"`
	Current  int    `json:"results_current"`
	History  int    `json:"history_rows"`
}

func Recompute(ctx context.Context, tx pgx.Tx, metric, since, until string, now time.Time) (RecomputeSummary, error) {
	result := RecomputeSummary{Metric: metric}
	catalog := configs()
	if _, ok := catalog[metric]; !ok && metric != "all" {
		return result, errors.New("invalid_metric")
	}
	if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
		return result, err
	}
	b, err := newBatch(ctx, tx, now, nil)
	if err != nil {
		return result, err
	}
	if metric != "all" {
		b.filter = map[string]bool{metric: true}
		if metric == "hard_session_spacing" {
			b.filter["long_run_exposure"] = true
		}
		if b.filter["long_run_exposure"] {
			b.filter["symptom_response_timeline"] = true
		}
		if metric == "planned_actual_session" {
			b.filter[intervals.ID] = true
		}
		b.calculate = b.runSelected
	}
	today := now.In(b.zone)
	if since == "" {
		since = today.AddDate(0, 0, -83).Format(time.DateOnly)
	}
	if until == "" {
		until = today.Format(time.DateOnly)
	}
	result.Since, result.Until = since, until
	first, e1 := time.ParseInLocation(time.DateOnly, since, b.zone)
	last, e2 := time.ParseInLocation(time.DateOnly, until, b.zone)
	if e1 != nil || e2 != nil || first.After(last) || last.After(today) {
		return result, errors.New("invalid_date_window")
	}
	for day := first; !day.After(last); day = day.AddDate(0, 0, 1) {
		clear(b.runs)
		clear(b.plans)
		if err := b.windows(day); err != nil {
			return result, err
		}
	}
	versions := map[string]string{}
	for m := range catalog {
		versions[m] = version(m)
	}
	err = tx.QueryRow(ctx, `SELECT count(DISTINCT(metric_id,subject_key)),count(*) FILTER(WHERE is_current AND method_version=($2::jsonb->>metric_id)),count(*) FROM metric_results WHERE $1='all' OR metric_id=$1`, metric, versions).Scan(&result.Subjects, &result.Current, &result.History)
	return result, err
}
