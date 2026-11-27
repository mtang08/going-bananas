package snapshotreads

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

type ActivityInputs struct {
	Runs          []map[string]any `json:"runs"`
	MetricResults []map[string]any `json:"metric_results"`
	Coverage      []map[string]any `json:"coverage"`
}

func LoadActivity(ctx context.Context, tx pgx.Tx, asOf string, zone *time.Location) (ActivityInputs, error) {
	runs, err := activityRows(ctx, tx, eligibleRunsSQL, "start_at", asOf, zone.String())
	if err != nil {
		return ActivityInputs{}, err
	}
	ids := make([]string, 0, len(runs))
	for _, r := range runs {
		ids = append(ids, r["activity_id"].(string))
	}
	metrics, err := activityRows(ctx, tx, snapshotMetricsSQL, "calculated_at", asOf, ids)
	if err != nil {
		return ActivityInputs{}, err
	}
	coverage, err := activityRows(ctx, tx, `SELECT dataset,start_date::text,end_date::text,status,
		fully_enumerated,completed_at,reason FROM coverage_intervals
		WHERE end_date >= $1::date - 120 AND start_date <= $1::date
		ORDER BY dataset,start_date`, "completed_at", asOf)
	if err != nil {
		return ActivityInputs{}, err
	}
	return ActivityInputs{runs, metrics, coverage}, nil
}

func activityRows(ctx context.Context, tx pgx.Tx, sql, instant string, args ...any) ([]map[string]any, error) {
	rows, err := tx.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (map[string]any, error) {
		v, err := snapshotRow(row)
		if t, ok := v[instant].(time.Time); ok {
			v[instant] = feedbackInstant(t)
		}
		return v, err
	})
}

const eligibleRunsSQL = `
SELECT a.id::text AS activity_id,((a.start_at AT TIME ZONE $2)::date)::text AS local_date,
	a.sport,a.timer_s,a.distance_m,COALESCE(r.rpe,a.workout_rpe)::float8 AS rpe,
	COALESCE(r.source,CASE WHEN a.workout_rpe IS NOT NULL THEN 'garmin_fit' END) AS rpe_source,a.start_at
FROM activities a
LEFT JOIN LATERAL (SELECT excluded FROM activity_annotations WHERE activity_id=a.id
	ORDER BY version DESC LIMIT 1) ann ON true
LEFT JOIN LATERAL (SELECT rpe,source FROM session_rpe WHERE activity_id=a.id AND source IN ('manual','garmin_fit')
	ORDER BY (source='manual') DESC,collected_at DESC,id DESC LIMIT 1) r ON true
WHERE a.sport IN ('running','trail_running','treadmill_running') AND a.resolution_state='resolved'
	AND ann.excluded IS NOT TRUE
	AND a.start_at >= (($1::date-121)::timestamp AT TIME ZONE $2)
	AND a.start_at < (($1::date+2)::timestamp AT TIME ZONE $2)
	AND (a.start_at AT TIME ZONE $2)::date BETWEEN $1::date-120 AND $1::date
ORDER BY a.start_at,a.id`

const snapshotMetricsSQL = `
WITH subjects(key) AS (
	SELECT unnest($2::text[])
	UNION ALL SELECT 'night:'||($1::date-offset_days)::text FROM generate_series(0,119) AS offset_days
	UNION ALL SELECT 'w'||width||':'||$1::date::text||suffix FROM unnest(ARRAY[7,14,28,56,84]) AS width
	CROSS JOIN unnest(ARRAY['',':run',':strength']) AS suffix
), versions(metric_id,method_version) AS (VALUES
	('run_volume_frequency','v1'),('symptom_response_timeline','v1'),('long_run_exposure','v1'),
	('session_rpe_load','v1'),('intensity_time_distribution','v1'),('work_interval_execution','v2'),
	('recovery_multisignal_summary','v1'),('planned_actual_session','v2'),('hard_session_spacing','v1'),
	('aerobic_efficiency','v1')
)
SELECT r.id::text AS result_id,r.metric_id,r.method_version,r.subject_type,r.subject_key,
	r.window_label,r.status,r.quality_status,r.value,r.unit,r.reason_codes,r.quality_flags,r.anchor_keys,r.calculated_at
FROM metric_results r JOIN versions USING(metric_id,method_version)
WHERE r.is_current AND r.subject_key IN (SELECT key FROM subjects)
ORDER BY r.metric_id,r.subject_key,r.id`
