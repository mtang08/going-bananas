package trainingwindows

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
)

var longConfig = object{"precedence": []string{"plan_link", "manual", "long_rule"}, "long_recipe": "REC002", "rule": "long_rule.v1", "rule_multiplier": 1.33, "rule_lookback_days": 28, "rule_min_prior_runs": 4, "comparator_lookback_days": 30, "break_lookback_days": 14, "weekly_window_days": 7, "weekly_includes_current": true}

type dependency struct {
	id         uuid.UUID
	hash       string
	value      object
	anchors    []string
	anchorHash *string
}

func resultsFor(ctx context.Context, tx pgx.Tx, metric string, runs []*metrics.Run) (map[string]dependency, error) {
	ids := make([]string, 0, len(runs))
	for _, r := range runs {
		ids = append(ids, r.ID.String())
	}
	rows, err := tx.Query(ctx, `SELECT subject_key,id,dependency_hash,value,anchor_keys,anchor_set_hash FROM metric_results WHERE metric_id=$1 AND method_version='v1' AND is_current AND subject_key=ANY($2)`, metric, ids)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := map[string]dependency{}
	for rows.Next() {
		var key string
		var d dependency
		var raw []byte
		if err := rows.Scan(&key, &d.id, &d.hash, &raw, &d.anchors, &d.anchorHash); err != nil {
			return nil, err
		}
		value, err := metrics.JSONValue(raw)
		if err != nil {
			return nil, err
		}
		d.value, _ = value.(map[string]any)
		result[key] = d
	}
	return result, rows.Err()
}

func RefreshLong(ctx context.Context, tx pgx.Tx, asOf, now time.Time) error {
	return calculateLong(ctx, tx, asOf, func(r metrics.Result) error { _, err := metrics.StoreResult(ctx, tx, r, now); return err })
}

func calculateLong(ctx context.Context, tx pgx.Tx, asOf time.Time, emit func(metrics.Result) error) error {
	end := dayStart(asOf).AddDate(0, 0, 1)
	runs, err := runsBetween(ctx, tx, end.AddDate(0, 0, -84), end)
	if err != nil {
		return err
	}
	results, err := resultsFor(ctx, tx, "long_run_exposure", runs)
	if err != nil {
		return err
	}
	for _, width := range widths["long_run_exposure"] {
		start := end.AddDate(0, 0, -width)
		coverage, err := covered(ctx, tx, start, end)
		if err != nil {
			return err
		}
		ids := []string{}
		sources := []object{}
		unknown := false
		count, longCount := 0, 0
		var latest object
		for _, r := range runs {
			if r.Day < start.Format(time.DateOnly) {
				continue
			}
			id := r.ID.String()
			ids = append(ids, id)
			ref := object{"activity_id": id, "source_revision": r.SourceRevision, "source_refs": r.Refs, "metric_result_id": nil, "metric_dependency_hash": nil}
			if d, ok := results[id]; ok {
				ref["metric_result_id"], ref["metric_dependency_hash"] = d.id, d.hash
				if d.value != nil {
					count++
					switch d.value["classification"] {
					case "unknown":
						unknown = true
					case "long":
						longCount++
						latest = d.value
					}
				}
			}
			sources = append(sources, ref)
		}
		refs := object{"sources": sources, "coverage_complete": coverage, "expected_run_count": len(ids), "computed_result_count": count}
		hash, err := metrics.Digest(refs)
		if err != nil {
			return err
		}
		refs["input_hash"] = hash
		refs["activity_ids"] = ids
		flags := []string{}
		if !coverage {
			flags = append(flags, "SYNC_COVERAGE_INCOMPLETE")
		}
		if count < len(ids) {
			flags = append(flags, "ACTIVITY_RESULT_MISSING")
		}
		if unknown {
			flags = append(flags, "CLASSIFICATION_UNKNOWN")
		}
		key := fmt.Sprintf("w%d:%s", width, asOf.Format(time.DateOnly))
		r := metrics.Result{MetricID: "long_run_exposure", MethodVersion: "v1", SubjectType: "window", SubjectKey: key, WindowLabel: key, WindowStart: &start, WindowEnd: &end, Config: longConfig, SourceRefs: refs, Timezone: asOf.Location().String(), Status: "available", QualityFlags: flags, Value: object{"long_run_count": longCount, "latest": latest}}
		if len(flags) > 0 {
			r.Status = "partial"
		}
		if count == 0 && !coverage {
			r.Status = "missing"
			r.Value = nil
		}
		if err := emit(r); err != nil {
			return err
		}
	}
	return nil
}
