// Package evidence reads current coaching decision inputs under the caller's transaction.
package evidence

import (
	"bytes"
	"context"
	"encoding/json"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

type row = map[string]any

// PostgreSQL's JSON rendering of a double precision column loses the distinction
// between 1 and 1.0. Read scalars with their database types and decode JSONB with
// UseNumber so its integer values, including historical large IDs, stay exact.
func readRows(ctx context.Context, tx pgx.Tx, query string, args ...any) ([]row, error) {
	rows, err := tx.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (row, error) {
		columns := r.FieldDescriptions()
		values := make([]any, len(columns))
		targets := make([]any, len(columns))
		for i, column := range columns {
			switch column.DataTypeOID {
			case pgtype.JSONBOID, pgtype.JSONOID:
				targets[i] = new(json.RawMessage)
			default:
				targets[i] = &values[i]
			}
		}
		if err := r.Scan(targets...); err != nil {
			return nil, err
		}
		output := make(row, len(columns))
		for i, col := range columns {
			value := values[i]
			if raw, ok := targets[i].(*json.RawMessage); ok && len(*raw) > 0 {
				d := json.NewDecoder(bytes.NewReader(*raw))
				d.UseNumber()
				if err := d.Decode(&value); err != nil {
					return nil, err
				}
			}
			switch v := value.(type) {
			case [16]byte:
				value = uuid.UUID(v).String()
			case time.Time:
				if col.DataTypeOID == pgtype.DateOID {
					value = v.Format(time.DateOnly)
				} else {
					value = wireTime(v)
				}
			}
			output[col.Name] = value
		}
		return output, nil
	})
}

func wireTime(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond() == 0 {
		return t.Format("2006-01-02T15:04:05+00:00")
	}
	return t.Format("2006-01-02T15:04:05.000000+00:00")
}

type projection struct {
	key, query string
	optional   bool
}

const selectedSourceIDs = `select source_record_id from activity_sources union select source_record_id from recovery_observations union select source_record_id from strong_workouts`

var projections = []projection{
	{"activities", `select id,canonical_revision,resolution_state,fit_status,fit_file_id,field_provenance,start_at,local_date,sport,avg_hr_bpm,distance_m,moving_s,timer_s,workout_rpe::float8 from activities order by id`, false},
	{"checkins", `select id,version,observed_at,activity_id,gait_change,pain_reported,prompt_id,illness,fatigue::float8,kind,context_tags from checkins_v2 order by id`, false},
	{"recovery", `select id,metric,source_date,value,source_revision from recovery_observations order by id`, false},
	{"goals", `select id,version,status,text from goals order by id`, false},
	{"coverage", `select id,dataset,start_date,end_date,status,fully_enumerated from coverage_intervals order by id`, false},
	{"anchors", `select anchor_key,kind,status,value_low,value_high,unit,protocol,confidence,valid_from,review_after,supersedes_key from intensity_anchors order by id`, false},
	{"annotations", `select activity_id,version,workout_label,excluded from activity_annotations order by id`, true},
	{"symptoms", `select s.checkin_id,s.site,s.side,s.severity::float8,s.timing from symptom_reports s join checkins_v2 c on c.id=s.checkin_id order by s.id`, true},
	{"fit_files", `select activity_id,raw_object_id,zip_sha256,fit_sha256 from fit_files order by id`, false},
	{"activity_sources", `select activity_id,source_record_id,selected_fields from activity_sources order by id`, false},
	{"source_records", `select id,source_identity,payload_hash,raw_object_id,parser_version from source_records where id in (` + selectedSourceIDs + `) order by id`, false},
	{"raw_objects", `select id,sha256 from raw_objects where id in (
		select raw_object_id from source_records where id in (` + selectedSourceIDs + `) union select raw_object_id from fit_files union select raw_object_id from strong_workouts
	) order by id`, false},
	{"session_rpe", `select id,activity_id,strong_workout_id,manual_session_id,rpe::float8,source,collected_at,collection_delay_s from session_rpe order by id`, false},
	{"manual_sessions", `select id,version,date,kind,duration_s,effort,linked_activity_id from manual_sessions order by id`, false},
	{"strong_workouts", `select id,payload_hash,source_record_id,raw_object_id,resolution_state,local_date from strong_workouts order by id`, false},
	{"routine_slots", `select id,version,active,label,default_weekday,lower_body_cost,typical_duration_s,main_lower_body_lifts from strength_routine_slots order by id`, false},
	{"events", `select id,version,event_date,status,purpose,rank,goal_time_s from events order by id`, true},
	{"trips", `select id,version,status,source,start_date,end_date,destination_tz,destination_label,running_access,gym_access,day_availability from trips order by id`, true},
}
