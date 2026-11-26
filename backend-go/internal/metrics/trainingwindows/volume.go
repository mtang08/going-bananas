package trainingwindows

import (
	"context"
	"fmt"
	"math"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
)

type object = map[string]any

var volumeConfig = object{"window_days": []int{7, 14, 28, 56, 84}, "sports": []string{"running", "trail_running", "treadmill_running"}, "duration_field": "timer_s", "local_day_rule": "start_at_in_profile_tz"}

func runsBetween(ctx context.Context, tx pgx.Tx, start, end time.Time) ([]*metrics.Run, error) {
	rows, err := tx.Query(ctx, `SELECT id FROM activities WHERE start_at>=$1 AND start_at<$2 AND resolution_state='resolved' AND sport IN ('running','trail_running','treadmill_running') ORDER BY start_at,id`, start, end)
	if err != nil {
		return nil, err
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
	if err != nil {
		return nil, err
	}
	runs := make([]*metrics.Run, 0, len(ids))
	for _, id := range ids {
		r, err := metrics.LoadRun(ctx, tx, id, start.Location().String())
		if err != nil {
			return nil, err
		}
		if r != nil && r.Eligible {
			runs = append(runs, r)
		}
	}
	return runs, nil
}

func covered(ctx context.Context, tx pgx.Tx, start, end time.Time) (bool, error) {
	var complete bool
	err := tx.QueryRow(ctx, `SELECT coalesce(range_agg(daterange(start_date,end_date,'[]')) @> daterange($1::text::date,$2::text::date,'[)'),false)
 FROM coverage_intervals WHERE dataset='activities' AND status='complete' AND fully_enumerated AND start_date<$2::text::date AND end_date>=$1::text::date`, start.Format(time.DateOnly), end.Format(time.DateOnly)).Scan(&complete)
	return complete, err
}

func measure(sum float64, count, total int, complete bool) any {
	if count > 0 {
		v, _ := strconv.ParseFloat(strconv.FormatFloat(sum, 'f', 1, 64), 64)
		return v
	}
	if total == 0 && complete {
		return 0.0
	}
	return nil
}

func totals(runs []*metrics.Run, start, end time.Time, complete bool) (object, []string) {
	from, to := start.Format(time.DateOnly), end.Format(time.DateOnly)
	ids := []string{}
	var timer, distance float64
	var nt, nd int
	for _, r := range runs {
		if r.Day < from || r.Day >= to {
			continue
		}
		ids = append(ids, r.ID.String())
		if r.Timer != nil && *r.Timer >= 0 && !math.IsInf(*r.Timer, 0) {
			timer += *r.Timer
			nt++
		}
		if r.Distance != nil && *r.Distance >= 0 && !math.IsInf(*r.Distance, 0) {
			distance += *r.Distance
			nd++
		}
	}
	return object{"start_date": from, "end_date": end.AddDate(0, 0, -1).Format(time.DateOnly), "run_count": len(ids), "timer_duration_s": measure(timer, nt, len(ids), complete), "distance_m": measure(distance, nd, len(ids), complete), "runs_missing_timer": len(ids) - nt, "runs_missing_distance": len(ids) - nd}, ids
}

// RefreshVolume stores all registered current and previous-period running totals for a local as-of date.
func RefreshVolume(ctx context.Context, tx pgx.Tx, asOf time.Time, now time.Time) error {
	asOf = time.Date(asOf.Year(), asOf.Month(), asOf.Day(), 0, 0, 0, 0, asOf.Location())
	end := asOf.AddDate(0, 0, 1)
	runs, err := runsBetween(ctx, tx, end.AddDate(0, 0, -168), end)
	if err != nil {
		return err
	}
	for _, days := range widths["run_volume_frequency"] {
		start := end.AddDate(0, 0, -days)
		prior := start.AddDate(0, 0, -days)
		current, err := covered(ctx, tx, start, end)
		if err != nil {
			return err
		}
		previous, err := covered(ctx, tx, prior, start)
		if err != nil {
			return err
		}
		value, ids := totals(runs, start, end, current)
		prev, _ := totals(runs, prior, start, previous)
		prev["coverage_complete"] = previous
		value["previous"] = prev
		sources := []object{}
		for _, r := range runs {
			if r.Day >= prior.Format(time.DateOnly) {
				sources = append(sources, object{"activity_id": r.ID, "source_revision": r.SourceRevision, "source_refs": r.Refs})
			}
		}
		refs := object{"sources": sources, "coverage_complete": current, "previous_coverage_complete": previous}
		h, err := metrics.Digest(refs)
		if err != nil {
			return err
		}
		refs["input_hash"] = h
		refs["activity_ids"] = ids
		reasons, flags := []string{}, []string{}
		if value["runs_missing_timer"] != 0 {
			reasons = append(reasons, "TIMER_MISSING")
		}
		if value["runs_missing_distance"] != 0 {
			reasons = append(reasons, "DISTANCE_MISSING")
		}
		if !current {
			flags = append(flags, "SYNC_COVERAGE_INCOMPLETE")
		}
		status, quality := "available", "good"
		if len(reasons)+len(flags) > 0 {
			status, quality = "partial", "limited"
		}
		if !current && len(ids) == 0 {
			status, quality = "missing", ""
		}
		key := fmt.Sprintf("w%d:%s", days, asOf.Format(time.DateOnly))
		_, err = metrics.StoreResult(ctx, tx, metrics.Result{MetricID: "run_volume_frequency", MethodVersion: "v1", SubjectType: "window", SubjectKey: key, WindowLabel: key, WindowStart: &start, WindowEnd: &end, Config: volumeConfig, SourceRefs: refs, Value: value, Status: status, QualityStatus: quality, QualityFlags: flags, ReasonCodes: reasons, Timezone: asOf.Location().String()}, now)
		if err != nil {
			return err
		}
	}
	return nil
}
