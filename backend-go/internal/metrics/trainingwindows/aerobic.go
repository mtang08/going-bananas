package trainingwindows

import (
	"context"
	"errors"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/aerobic"
	"slices"
	"strconv"
	"strings"
	"time"
)

type aeroEntry struct {
	run                   *metrics.Run
	resultID, dep, status *string
	reasons, flags        []string
	val                   object
}

func rounded(v float64, d int) float64 {
	n, _ := strconv.ParseFloat(strconv.FormatFloat(v, 'f', d, 64), 64)
	return n
}
func mid(vals []float64) float64 {
	slices.Sort(vals)
	i := len(vals) / 2
	if len(vals)%2 == 1 {
		return vals[i]
	}
	return (vals[i-1] + vals[i]) / 2
}
func midOrNil(v []float64, d int) any {
	if len(v) == 0 {
		return nil
	}
	return rounded(mid(v), d)
}
func aerobicWindow(ctx context.Context, tx pgx.Tx, first, end time.Time, days int, now time.Time) error {
	runs, err := runsBetween(ctx, tx, first, end)
	if err != nil {
		return err
	}
	entries := make([]aeroEntry, 0, len(runs))
	sources := make([]object, 0, len(runs))
	ids := make([]string, 0, len(runs))
	for _, r := range runs {
		e := aeroEntry{run: r}
		err := tx.QueryRow(ctx, `SELECT id::text,dependency_hash,status,reason_codes,quality_flags,value FROM metric_results WHERE metric_id=$1 AND method_version=$2 AND subject_key=$3 AND is_current`, aerobic.ID, aerobic.Version, r.ID.String()).Scan(&e.resultID, &e.dep, &e.status, &e.reasons, &e.flags, &e.val)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		entries = append(entries, e)
		ids = append(ids, r.ID.String())
		sources = append(sources, object{"activity_id": r.ID.String(), "source_revision": r.SourceRevision, "metric_result_id": e.resultID, "metric_dependency_hash": e.dep})
	}
	complete, err := covered(ctx, tx, first, end)
	if err != nil {
		return err
	}
	refs := object{"sources": sources, "coverage_complete": complete}
	hash, err := metrics.Digest(refs)
	if err != nil {
		return err
	}
	refs["input_hash"] = hash
	refs["activity_ids"] = ids
	middle := first.AddDate(0, 0, days/2).Format(time.DateOnly)
	points := []object{}
	skip := map[string]int{}
	var vals, early, late, decs []float64
	slices.SortFunc(entries, func(a, b aeroEntry) int {
		if a.run.Day < b.run.Day {
			return -1
		}
		if a.run.Day > b.run.Day {
			return 1
		}
		return strings.Compare(a.run.ID.String(), b.run.ID.String())
	})
	for _, e := range entries {
		reason := "NO_RESULT"
		if e.status != nil && (*e.status == "available" || *e.status == "partial") && e.val != nil {
			if slices.Contains(e.flags, "TREADMILL") {
				skip["TREADMILL"]++
				continue
			}
			ef := e.val["ef_m_per_beat"].(float64)
			dec := e.val["decoupling"].(map[string]any)["pct"]
			vals = append(vals, ef)
			if e.run.Day < middle {
				early = append(early, ef)
			} else {
				late = append(late, ef)
			}
			if d, ok := dec.(float64); ok {
				decs = append(decs, d)
			}
			points = append(points, object{"activity_id": e.run.ID.String(), "local_date": e.run.Day, "session_class": e.val["session_class"], "ef_m_per_beat": ef, "mean_speed_mps": e.val["mean_speed_mps"], "mean_hr_bpm": e.val["mean_hr_bpm"], "decoupling_pct": dec, "quality_flags": e.flags})
			continue
		}
		if len(e.reasons) > 0 {
			reason = e.reasons[0]
		}
		skip[reason]++
	}
	var change any
	enough := len(early) >= 3 && len(late) >= 3
	if enough {
		change = rounded(100*(mid(late)-mid(early))/mid(early), 2)
	}
	value := object{"window_days": days, "runs_total": len(entries), "runs_counted": len(points), "runs_without_result": skip["NO_RESULT"], "not_counted": skip, "ef_median_m_per_beat": midOrNil(vals, 3), "ef_early_median_m_per_beat": midOrNil(early, 3), "ef_late_median_m_per_beat": midOrNil(late, 3), "ef_change_pct": change, "decoupling_runs_counted": len(decs), "decoupling_median_pct": midOrNil(decs, 2), "points": points}
	status := "available"
	reasons := []string{}
	flags := []string{}
	if len(points) == 0 {
		status = "not_assessable"
		reasons = append(reasons, "NO_ELIGIBLE_RUNS")
	} else {
		if skip["NO_RESULT"] > 0 {
			reasons = append(reasons, "ACTIVITY_RESULT_MISSING")
		}
		if len(reasons) > 0 || !complete {
			status = "partial"
		}
		if !enough {
			flags = append(flags, "TREND_TOO_FEW_RUNS")
		}
	}
	if !complete {
		reasons = append(reasons, "SYNC_COVERAGE_INCOMPLETE")
	}
	key := "w" + strconv.Itoa(days) + ":" + end.AddDate(0, 0, -1).Format(time.DateOnly)
	_, err = metrics.StoreResult(ctx, tx, metrics.Result{MetricID: aerobic.ID, MethodVersion: aerobic.Version, SubjectType: "window", SubjectKey: key, WindowLabel: key, WindowStart: &first, WindowEnd: &end, Status: status, Value: value, ReasonCodes: reasons, QualityFlags: flags, Unit: "m_per_beat", Timezone: first.Location().String(), Config: aerobic.Config, SourceRefs: refs}, now)
	return err
}
func RefreshAerobic(ctx context.Context, tx pgx.Tx, asOf, now time.Time) error {
	end := time.Date(asOf.Year(), asOf.Month(), asOf.Day()+1, 0, 0, 0, 0, asOf.Location())
	for _, d := range []int{28, 84} {
		if err := aerobicWindow(ctx, tx, end.AddDate(0, 0, -d), end, d, now); err != nil {
			return err
		}
	}
	return nil
}
