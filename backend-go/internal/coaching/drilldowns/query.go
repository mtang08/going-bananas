// Package drilldowns supplies read-only projections for the coaching_query dashboard tool.
package drilldowns

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/coachdashboard"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/evidence"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/aerobic"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/assessment"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/intensity"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/intervals"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/recovery"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/trainingwindows"
)

type object = map[string]any

// Preview computes missing or outdated rows within the existing read transaction.
// A nil row denotes a subject that has no metric, just as in engine.read_results.
type Reader struct {
	Preview func(context.Context, pgx.Tx, string, string, time.Time) (map[string]any, error)
	Now     func() time.Time
}

func Query(ctx context.Context, tx pgx.Tx, args map[string]any) (any, error) {
	return (Reader{}).Query(ctx, tx, args)
}

func failure(code, msg string) error { return &coachdashboard.ToolFailure{Code: code, Message: msg} }
func badArgs() error {
	return failure("invalid_tool_arguments", "Check the coaching tool's arguments.")
}
func stringArg(args object, key string) string { s, _ := args[key].(string); return s }

func (r Reader) Query(ctx context.Context, tx pgx.Tx, args map[string]any) (any, error) {
	now := time.Now().UTC()
	if r.Now != nil {
		now = r.Now()
	}
	name := stringArg(args, "name")
	if name != "explain_metric" {
		if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock_shared(71382413)"); err != nil {
			return nil, err
		}
	}
	switch name {
	case "calendar_diff":
		from, err := strconv.Atoi(fmt.Sprint(args["from_version"]))
		if err != nil {
			return nil, badArgs()
		}
		to, err := strconv.Atoi(fmt.Sprint(args["to_version"]))
		if err != nil {
			return nil, badArgs()
		}
		return calendarDiff(ctx, tx, from, to)
	case "explain_metric", "activity_execution":
		key := "activity_id"
		if name == "explain_metric" {
			key = "result_id"
		}
		id, err := uuid.Parse(stringArg(args, key))
		if err != nil {
			return nil, badArgs()
		}
		if name == "explain_metric" {
			return explain(ctx, tx, id)
		}
		return r.activity(ctx, tx, id, now)
	case "long_run_history", "recovery_nights":
		start, err := time.Parse(time.DateOnly, stringArg(args, "start"))
		if err != nil {
			return nil, badArgs()
		}
		end, err := time.Parse(time.DateOnly, stringArg(args, "end"))
		if err != nil {
			return nil, badArgs()
		}
		if end.Before(start) || !end.Before(start.AddDate(0, 0, 92)) {
			return nil, failure("invalid_date_window", "Choose a date window of at most 92 days.")
		}
		if name == "recovery_nights" {
			return r.nights(ctx, tx, start, end, now)
		}
		return r.longRuns(ctx, tx, start, end, now)
	default:
		return nil, badArgs()
	}
}

func instant(t time.Time) string {
	layout := "2006-01-02T15:04:05"
	if t.Nanosecond() != 0 {
		layout += ".000000"
	}
	return t.UTC().Format(layout) + "+00:00"
}

// Convert only the timestamp columns of the row; nested values are stored JSON data.
func wireRows(ctx context.Context, tx pgx.Tx, query string, args ...any) ([]object, error) {
	rows, err := tx.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (object, error) {
		var raw []byte
		if err := row.Scan(&raw); err != nil {
			return nil, err
		}
		decoder := json.NewDecoder(bytes.NewReader(raw))
		decoder.UseNumber()
		var data object
		if err := decoder.Decode(&data); err != nil {
			return nil, err
		}
		for _, k := range []string{"start_at", "end_at", "window_start", "window_end", "calculated_at", "updated_at", "opens_at", "closes_at", "observed_at", "recorded_at"} {
			if v, ok := data[k].(string); ok {
				if t, err := time.Parse(time.RFC3339Nano, v); err == nil {
					data[k] = instant(t)
				}
			}
		}
		return data, nil
	})
}

func first(rows []object) object {
	if len(rows) > 0 {
		return rows[0]
	}
	return nil
}

func explain(ctx context.Context, tx pgx.Tx, id uuid.UUID) (object, error) {
	rows, err := wireRows(ctx, tx, `SELECT to_jsonb(r) || jsonb_build_object('config',c.config,'source_availability',
		jsonb_build_object('config_available',c.id IS NOT NULL,'provenance_complete',NOT ('MISSING_PROVENANCE'=ANY(r.reason_codes))))
		FROM metric_results r LEFT JOIN metric_configs c ON (r.metric_id,r.method_version,r.config_hash)=(c.metric_id,c.method_version,c.config_hash)
		WHERE r.id=$1`, id)
	if err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return nil, failure("metric_result_not_found", "Metric result not found")
	}
	return rows[0], nil
}

func (r Reader) metric(ctx context.Context, tx pgx.Tx, id, key string, now time.Time) (object, error) {
	version, hash, ok := evidence.RegisteredMetric(id)
	if !ok {
		return nil, errors.New("unregistered coaching metric")
	}
	rows, err := wireRows(ctx, tx, `SELECT to_jsonb(r) FROM metric_results r WHERE metric_id=$1 AND method_version=$2
		AND subject_key=$3 AND is_current AND config_hash=$4 ORDER BY calculated_at DESC,id DESC LIMIT 1`, id, version, key, hash)
	if err != nil || len(rows) > 0 {
		return first(rows), err
	}
	if r.Preview != nil {
		return r.Preview(ctx, tx, id, key, now)
	}
	if id == "recovery_multisignal_summary" {
		return recovery.NightPreview(ctx, tx, key)
	}
	subject, err := uuid.Parse(key)
	if err != nil {
		return nil, err
	}
	var result *metrics.Result
	switch id {
	case "long_run_exposure", "session_rpe_load", "symptom_response_timeline":
		var zone string
		if err := tx.QueryRow(ctx, "SELECT "+zoneSQL).Scan(&zone); err != nil {
			return nil, err
		}
		result, err = trainingwindows.CalculateActivity(ctx, tx, id, subject, zone)
	case "work_interval_execution":
		result, err = intervals.Calculate(ctx, tx, subject)
	case "aerobic_efficiency":
		result, err = aerobic.Calculate(ctx, tx, subject)
	case "intensity_time_distribution":
		result, err = intensity.Calculate(ctx, tx, subject)
	case "planned_actual_session":
		result, err = assessment.Calculate(ctx, tx, subject, now)
	default:
		return nil, errors.New("unknown coaching query metric")
	}
	if err != nil || result == nil {
		return nil, err
	}
	return previewRow(*result, now)
}

func previewRow(result metrics.Result, now time.Time) (object, error) {
	row, err := metrics.Preview(result, now)
	if err != nil {
		return nil, err
	}
	for _, key := range []string{"window_start", "window_end"} {
		if t, ok := row[key].(*time.Time); ok && t != nil {
			row[key] = instant(*t)
		}
	}
	row["calculated_at"] = instant(now)
	return row, nil
}

func (r Reader) nights(ctx context.Context, tx pgx.Tx, start, end, now time.Time) (object, error) {
	var nights []object
	for d := start; !d.After(end); d = d.AddDate(0, 0, 1) {
		day := d.Format(time.DateOnly)
		row, err := r.metric(ctx, tx, "recovery_multisignal_summary", "night:"+day, now)
		if err != nil {
			return nil, err
		}
		if row == nil {
			return nil, errors.New("missing recovery night preview")
		}
		n := object{}
		if value, ok := row["value"].(object); ok {
			for k, v := range value {
				n[k] = v
			}
		}
		n["local_date"] = day
		for _, k := range []string{"status", "quality_status", "reason_codes", "quality_flags"} {
			n[k] = row[k]
		}
		nights = append(nights, n)
	}
	return object{"start": start.Format(time.DateOnly), "end": end.Format(time.DateOnly), "nights": nights}, nil
}

const zoneSQL = "coalesce((SELECT nullif(timezone,'') FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York')"

func (r Reader) longRuns(ctx context.Context, tx pgx.Tx, start, end, now time.Time) ([]object, error) {
	rows, err := tx.Query(ctx, `SELECT id::text FROM activities WHERE (start_at AT TIME ZONE `+zoneSQL+`)::date BETWEEN $1::date AND $2::date ORDER BY start_at,id`, start.Format(time.DateOnly), end.Format(time.DateOnly))
	if err != nil {
		return nil, err
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, err
	}
	out := []object{}
	for _, id := range ids {
		row, err := r.metric(ctx, tx, "long_run_exposure", id, now)
		if err != nil {
			return nil, err
		}
		if val, ok := row["value"].(object); ok && val["classification"] == "long" {
			out = append(out, row)
		}
	}
	slices.SortFunc(out, func(a, b object) int {
		x, y := stringArg(a, "window_start"), stringArg(b, "window_start")
		if x == "" && y != "" {
			return 1
		}
		if y == "" && x != "" {
			return -1
		}
		if x < y {
			return -1
		}
		if x > y {
			return 1
		}
		aID, bID := stringArg(a, "subject_key"), stringArg(b, "subject_key")
		if aID < bID {
			return -1
		}
		if aID > bID {
			return 1
		}
		return 0
	})
	return out, nil
}
