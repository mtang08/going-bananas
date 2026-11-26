package metrics

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
)

type object = map[string]any

func Digest(value any) (string, error) {
	b, err := canonicaljson.Metric(value)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("%x", sha256.Sum256(b)), nil
}
func JSONValue(raw []byte) (any, error) {
	if raw == nil {
		return nil, nil
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var value any
	err := dec.Decode(&value)
	return value, err
}

// PostgreSQL JSON loses the distinction between integer-valued float columns
// and integers. Restore schema-declared floats before computing Python's hash.
func floats(value any) any {
	switch v := value.(type) {
	case json.Number:
		f, _ := v.Float64()
		return f
	case []any:
		for i, child := range v {
			v[i] = floats(child)
		}
		return v
	default:
		return value
	}
}
func jsonRows(ctx context.Context, tx pgx.Tx, query string, id uuid.UUID, floatFields ...string) ([]object, error) {
	rows, err := tx.Query(ctx, query, id)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (object, error) {
		var b []byte
		if err := r.Scan(&b); err != nil {
			return nil, err
		}
		value, err := JSONValue(b)
		if err != nil {
			return nil, err
		}
		obj := value.(map[string]any)
		for _, key := range floatFields {
			obj[key] = floats(obj[key])
		}
		return obj, nil
	})
}

const utcStart = `to_char(start_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')`
const utcEnd = `to_char(end_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')`

func fitReferences(ctx context.Context, tx pgx.Tx, id uuid.UUID) (object, error) {
	// psycopg receives the PostgreSQL text representation of real[] values.
	// Preserve that spelling before converting to Python-style floats.
	streams, err := jsonRows(ctx, tx, `SELECT to_jsonb(s)-'activity_id' FROM activity_streams s WHERE activity_id=$1`, id, "speed_mps", "distance_m", "altitude_m", "cadence")
	if err != nil {
		return nil, err
	}
	var stream object
	var flags any = []string{}
	if len(streams) > 0 {
		stream = streams[0]
		flags = stream["quality_flags"]
	}
	laps, err := jsonRows(ctx, tx, `SELECT (to_jsonb(l)-'id'-'activity_id')||jsonb_build_object('start_at',`+utcStart+`,'end_at',`+utcEnd+`)
		FROM activity_laps l WHERE activity_id=$1 ORDER BY lap_index`, id, "timer_s", "elapsed_s", "distance_m", "avg_speed_mps", "avg_hr_bpm", "max_hr_bpm")
	if err != nil {
		return nil, err
	}
	steps, err := jsonRows(ctx, tx, `SELECT to_jsonb(w)-'id'-'activity_id' FROM activity_workout_steps w WHERE activity_id=$1 ORDER BY message_index`, id, "duration_value", "target_low", "target_high")
	if err != nil {
		return nil, err
	}
	hash, err := Digest(object{"stream": stream, "laps": laps, "steps": steps})
	if err != nil {
		return nil, err
	}
	fit, err := jsonRows(ctx, tx, `SELECT jsonb_build_object('id',id,'fit_sha256',fit_sha256,'zip_sha256',zip_sha256,'raw_object_id',raw_object_id,
		'sdk_version',sdk_version,'profile_version',profile_version) FROM fit_files WHERE activity_id=$1`, id)
	if err != nil {
		return nil, err
	}
	result := object{}
	if len(fit) > 0 {
		result = fit[0]
	}
	result["normalized_hash"] = hash
	result["quality_flags"] = flags
	return result, nil
}

// Run contains the validated facts and canonical identity used by activity metrics.
type Run struct {
	ID              uuid.UUID
	Sport           string
	Timer, Distance *float64
	Start           time.Time
	End             *time.Time
	Day, State      string
	Label           *string
	Eligible        bool
	Refs, FIT       object
	SourceRevision  string
}

func LoadRun(ctx context.Context, tx pgx.Tx, id uuid.UUID, zone string) (*Run, error) {
	a := Run{ID: id}
	var raw []byte
	var start time.Time
	var end *time.Time
	var label, annotationLabel *string
	var revision int
	var fitStatus, state, day string
	var elapsed *float64
	var excluded *bool
	var version *int
	err := tx.QueryRow(ctx, `SELECT a.start_at,a.end_at,a.sport,a.timer_s,a.elapsed_s,a.distance_m,a.source_workout_label,
		a.resolution_state,a.canonical_revision,a.fit_status,a.field_provenance,(a.start_at AT TIME ZONE $2)::date::text,
		an.excluded,an.workout_label,an.version FROM activities a LEFT JOIN LATERAL
		(SELECT * FROM activity_annotations WHERE activity_id=a.id ORDER BY version DESC LIMIT 1) an ON true WHERE a.id=$1`, id, zone).Scan(
		&start, &end, &a.Sport, &a.Timer, &elapsed, &a.Distance, &label, &state, &revision, &fitStatus, &raw, &day, &excluded, &annotationLabel, &version)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	provenance, err := JSONValue(raw)
	if err != nil {
		return nil, err
	}
	fit, err := fitReferences(ctx, tx, id)
	if err != nil {
		return nil, err
	}
	sources, err := jsonRows(ctx, tx, `SELECT json_build_object('source_record_id',s.id,'payload_hash',s.payload_hash,'source_modified_at',
		CASE WHEN s.source_modified_at IS NOT NULL THEN to_char(s.source_modified_at,'YYYY-MM-DD"T"HH24:MI:SS') ||
		CASE WHEN extract(microseconds FROM s.source_modified_at)::integer%1000000<>0 THEN to_char(s.source_modified_at,'.US') ELSE '' END ||
		to_char(s.source_modified_at,'TZH:TZM') END,
		'parser_version',s.parser_version,'raw_sha256',r.sha256,'selected_fields',l.selected_fields)
		FROM activity_sources l JOIN source_records s ON s.id=l.source_record_id LEFT JOIN raw_objects r ON r.id=s.raw_object_id
		WHERE l.activity_id=$1 ORDER BY s.id`, id)
	if err != nil {
		return nil, err
	}
	var annotation object
	if version != nil {
		annotation = object{"excluded": excluded, "workout_label": annotationLabel}
	}
	refs := object{"id": id, "canonical_revision": revision, "fit_status": fitStatus,
		"facts":      object{"start_at": start, "end_at": end, "sport": a.Sport, "timer_s": a.Timer, "elapsed_s": elapsed, "distance_m": a.Distance, "source_workout_label": label, "resolution_state": state},
		"annotation": annotation, "annotation_version": version, "source_records": sources, "field_provenance": provenance, "fit": fit}
	hash, err := Digest(refs)
	if err != nil {
		return nil, err
	}
	a.Start, a.End, a.Day, a.State, a.Label = start, end, day, state, label
	if annotationLabel != nil && *annotationLabel != "" {
		a.Label = annotationLabel
	}
	a.Refs, a.FIT, a.SourceRevision = refs, fit, hash
	a.Eligible = state == "resolved" && (a.Sport == "running" || a.Sport == "trail_running" || a.Sport == "treadmill_running") && (excluded == nil || !*excluded)
	return &a, nil
}
