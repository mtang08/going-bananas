package activityhttp

import (
	"context"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"net/http"
	"strings"
	"time"
)

const activitySQL = `SELECT a.id::text,a.sport,a.resolution_state,to_json(a.start_at)#>>'{}',(a.start_at AT TIME ZONE $1)::date::text,
 a.distance_m,a.elapsed_s,a.moving_s,a.avg_hr_bpm,an.workout_label,a.source_workout_label,coalesce(an.excluded,false),
 jsonb_build_object('id',a.id,'original_start',a.original_start,'source_local_date',a.local_date,'subtype',a.subtype,'provenance',a.field_provenance,
  'source',CASE WHEN a.garmin_id IS NULL OR a.garmin_id='' THEN 'import' ELSE 'garmin' END,
  'annotations',jsonb_build_object('version',coalesce(an.version,0),'workout_label',an.workout_label,'notes',an.notes,'excluded',coalesce(an.excluded,false)))
 FROM activities a LEFT JOIN LATERAL (SELECT * FROM activity_annotations WHERE activity_id=a.id ORDER BY version DESC LIMIT 1) an ON true`

func readActivities(ctx context.Context, tx pgx.Tx, clause string, args ...any) ([]activity, error) {
	rows, err := tx.Query(ctx, activitySQL+clause, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (activity, error) {
		var a activity
		var start string
		err := row.Scan(&a.id, &a.sport, &a.state, &start, &a.day, &a.distance, &a.elapsed, &a.moving, &a.hr, &a.manual, &a.source, &a.excluded, &a.data)
		if err == nil {
			a.start, err = time.Parse(time.RFC3339Nano, start)
		}
		return a, err
	})
}
func fill(ctx context.Context, tx pgx.Tx, rows []activity, zone string) ([]object, error) {
	out := make([]object, 0, len(rows))
	if len(rows) == 0 {
		return out, nil
	}
	var first, last time.Time
	for _, a := range rows {
		if !eligible(a) {
			continue
		}
		if first.IsZero() || first.After(a.start) {
			first = a.start
		}
		if last.Before(a.start) {
			last = a.start
		}
	}
	var hist []activity
	var err error
	days := []int{5, 6}
	if !first.IsZero() {
		hist, err = readActivities(ctx, tx, " WHERE a.start_at BETWEEN $2 AND $3 AND a.sport IN ('running','trail_running','treadmill_running')", zone, first.Add(-84*24*time.Hour), last)
		if err != nil {
			return nil, err
		}
		var prefs any
		if err = tx.QueryRow(ctx, "SELECT (SELECT preferences->'long_run_weekdays' FROM profile_versions ORDER BY version DESC LIMIT 1)").Scan(&prefs); err != nil {
			return nil, err
		}
		if v, ok := prefs.([]any); ok && len(v) > 0 {
			var custom []int
			for _, d := range v {
				x, ok := d.(float64)
				if !ok || x != float64(int(x)) || x < 0 || x > 6 {
					custom = nil
					break
				}
				custom = append(custom, int(x))
			}
			if custom != nil {
				days = custom
			}
		}
	}
	for _, a := range rows {
		v := a.data
		v["sport"] = a.sport
		v["start_at"] = wireTime(a.start)
		v["local_date"] = a.day
		v["resolution_state"] = a.state
		v["distance_m"] = a.distance
		v["elapsed_s"] = a.elapsed
		v["moving_s"] = a.moving
		v["avg_hr_bpm"] = a.hr
		for k, n := range map[string]*float64{"moving_pace_s_per_km": a.moving, "elapsed_pace_s_per_km": a.elapsed} {
			v[k] = nil
			if positive(n) && positive(a.distance) {
				v[k] = *n / (*a.distance / 1000)
			}
		}
		v["classification"] = nil
		label := "unknown"
		if a.source != nil && *a.source != "" {
			label = *a.source
		}
		if a.manual != nil && *a.manual != "" {
			label = *a.manual
		}
		if eligible(a) {
			c := classify(a, hist, days)
			v["classification"] = c
			label = c["effective_label"].(string)
		}
		v["workout_label"] = label
		out = append(out, v)
	}
	return out, nil
}
func dateStamp(t time.Time) string {
	s := "2006-01-02T15:04:05-07:00"
	if t.Nanosecond() != 0 {
		s = "2006-01-02T15:04:05.000000-07:00"
	}
	return t.Format(s)
}
func (h Handler) activities(ctx context.Context, tx pgx.Tx, r *http.Request, now time.Time, loc *time.Location) (any, error) {
	first, last, err := days(r, "start_date", "end_date", now, loc, 28, 366)
	if err != nil {
		return nil, err
	}
	q := r.URL.Query()
	size, err := limit(q, 50, 1, 200)
	if err != nil {
		return nil, err
	}
	sport, _ := parameter(q, "sport")
	var stamp *time.Time
	var id *uuid.UUID
	if cursor, _ := parameter(q, "cursor"); cursor != "" {
		left, right, ok := strings.Cut(cursor, "|")
		t, e := time.Parse(time.RFC3339Nano, left)
		u, e2 := uuid.Parse(right)
		if !ok || e != nil || e2 != nil {
			return nil, &problem{422, "invalid_cursor", "Invalid activity cursor", nil}
		}
		stamp = &t
		id = &u
	}
	rows, err := readActivities(ctx, tx, ` WHERE a.start_at>=$2 AND a.start_at<$3 AND ($4::text='' OR sport=$4)
  AND ($5::timestamptz IS NULL OR (a.start_at,a.id)<($5,$6::uuid)) ORDER BY a.start_at DESC,a.id DESC LIMIT $7`, loc.String(), first, last.AddDate(0, 0, 1), sport, stamp, id, size+1)
	if err != nil {
		return nil, err
	}
	var next *string
	if len(rows) > size {
		rows = rows[:size]
		last := rows[size-1]
		v := dateStamp(last.start) + "|" + last.id
		next = &v
	}
	items, err := fill(ctx, tx, rows, loc.String())
	if err != nil {
		return nil, err
	}
	var coverage []object
	err = tx.QueryRow(ctx, `SELECT coalesce(jsonb_agg(jsonb_build_object('dataset',dataset,'start_date',start_date,'end_date',end_date,'status',status,
  'fully_enumerated',fully_enumerated,'completed_at',completed_at,'reason',reason) ORDER BY dataset,start_date),'[]')
 FROM coverage_intervals WHERE start_date<=$2 AND end_date>=$1`, first.Format(time.DateOnly), last.Format(time.DateOnly)).Scan(&coverage)
	return object{"items": items, "next_cursor": next, "timezone": loc.String(), "coverage": coverage}, err
}
func activityID(r *http.Request) (uuid.UUID, error) {
	id, err := uuid.Parse(r.PathValue("activity_id"))
	if err != nil {
		return uuid.Nil, invalid("path.activity_id", "Input should be a valid UUID")
	}
	return id, nil
}
func (h Handler) detail(ctx context.Context, tx pgx.Tx, r *http.Request, _ time.Time, loc *time.Location) (any, error) {
	id, err := activityID(r)
	if err != nil {
		return nil, err
	}
	rows, err := readActivities(ctx, tx, " WHERE a.id=$2", loc.String(), id)
	if err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return nil, &problem{404, "not_found", "Activity not found", nil}
	}
	items, err := fill(ctx, tx, rows, loc.String())
	if err != nil {
		return nil, err
	}
	var sources []object
	err = tx.QueryRow(ctx, `SELECT coalesce(jsonb_agg(jsonb_build_object('source_record_id',source_record_id,'selected_fields',selected_fields)),'[]') FROM activity_sources WHERE activity_id=$1`, id).Scan(&sources)
	items[0]["sources"] = sources
	return items[0], err
}

func wireTime(t time.Time) string {
	v := dateStamp(t)
	return strings.TrimSuffix(v, "+00:00") + map[bool]string{true: "Z"}[strings.HasSuffix(v, "+00:00")]
}
