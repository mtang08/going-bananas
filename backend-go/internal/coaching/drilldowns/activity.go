package drilldowns

import (
	"context"
	"encoding/json"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
)

func (r Reader) activity(ctx context.Context, tx pgx.Tx, id uuid.UUID, now time.Time) (object, error) {
	activities, err := wireRows(ctx, tx, `SELECT to_jsonb(v) FROM (SELECT id,start_at,end_at,(start_at AT TIME ZONE `+zoneSQL+`)::date AS local_date,
		sport,distance_m,timer_s,elapsed_s,fit_status,workout_rpe,treadmill_interval_paces FROM activities WHERE id=$1) v`, id)
	if err != nil {
		return nil, err
	}
	if len(activities) == 0 {
		return nil, failure("activity_not_found", "Activity not found")
	}
	a := activities[0]
	if !slices.Contains([]string{"running", "trail_running", "treadmill_running"}, stringArg(a, "sport")) {
		return nil, failure("not_run_activity", "Activity is not a run")
	}
	fitRPE := a["workout_rpe"]
	paces, _ := a["treadmill_interval_paces"].(object)
	delete(a, "workout_rpe")
	delete(a, "treadmill_interval_paces")
	metrics := map[string]object{}
	for _, key := range []string{"work_interval_execution", "intensity_time_distribution", "aerobic_efficiency", "session_rpe_load", "symptom_response_timeline"} {
		metrics[key], err = r.metric(ctx, tx, key, id.String(), now)
		if err != nil {
			return nil, err
		}
	}
	completed, err := wireRows(ctx, tx, `SELECT jsonb_build_object('id',id,'session_uid',session_uid,'activity_id',activity_id,'strong_workout_id',strong_workout_id,
		'manual_session_id',manual_session_id,'status',status,'match_method',match_method,'modification_reason',modification_reason,'reason_note',reason_note,
		'version',version,'input_version',input_version,'updated_at',updated_at) FROM session_completions WHERE activity_id=$1`, id)
	if err != nil {
		return nil, err
	}
	completion := first(completed)
	var planned, comparison object
	if completion != nil {
		completion["local_date"] = a["local_date"]
		uid := stringArg(completion, "session_uid")
		comparison, err = r.metric(ctx, tx, "planned_actual_session", uid, now)
		if err != nil {
			return nil, err
		}
		planned, err = activityPlan(ctx, tx, uid, now)
		if err != nil {
			return nil, err
		}
	}
	laps, err := wireRows(ctx, tx, `SELECT to_jsonb(l)-'id'-'activity_id' FROM activity_laps l WHERE activity_id=$1 ORDER BY lap_index`, id)
	if err != nil {
		return nil, err
	}
	if a["sport"] == "treadmill_running" {
		addPaces(laps, paces)
	}
	steps, err := wireRows(ctx, tx, `SELECT to_jsonb(s)-'id'-'activity_id' FROM activity_workout_steps s WHERE activity_id=$1 ORDER BY message_index`, id)
	if err != nil {
		return nil, err
	}
	var manual, garmin *float64
	err = tx.QueryRow(ctx, `SELECT max(rpe::float8) FILTER (WHERE source='manual'),max(rpe::float8) FILTER (WHERE source='garmin_fit') FROM session_rpe WHERE activity_id=$1`, id).Scan(&manual, &garmin)
	if err != nil {
		return nil, err
	}
	var effective, source any
	if garmin != nil {
		fitRPE = *garmin
	}
	if fitRPE != nil {
		effective = fitRPE
		source = "garmin_fit"
	}
	if manual != nil {
		effective = *manual
		source = "manual"
	}
	srpe, _ := metrics["session_rpe_load"]["value"].(object)
	symptoms, _ := metrics["symptom_response_timeline"]["value"].(object)
	reports, exists := symptoms["reports"]
	if !exists {
		reports = []any{}
	}
	feedback, err := delayedResponse(ctx, tx, id, now)
	if err != nil {
		return nil, err
	}
	return object{
		"activity": a, "planned": planned, "completion": completion, "laps": laps, "watch_steps": steps,
		"planned_actual": comparison, "intervals": metrics["work_interval_execution"], "intensity": metrics["intensity_time_distribution"], "aerobic": metrics["aerobic_efficiency"],
		"rpe":              object{"effective": effective, "source": source, "manual": manual, "garmin_fit": fitRPE, "srpe_load_au": srpe["load_au"]},
		"delayed_response": feedback, "symptoms": reports,
	}, nil
}

func activityPlan(ctx context.Context, tx pgx.Tx, uid string, now time.Time) (object, error) {
	rows, err := wireRows(ctx, tx, `WITH head AS (SELECT calendar_head_version AS n FROM app_state WHERE id=1 AND calendar_head_version>0),
		latest AS (SELECT r.* FROM calendar_session_revisions r,head WHERE session_uid=$1 AND calendar_version_number<=head.n
		ORDER BY calendar_version_number DESC,revision DESC LIMIT 1),
		current_row AS (SELECT `+rowView+` || jsonb_build_object('certainty',CASE WHEN local_date<=($2::timestamptz AT TIME ZONE `+zoneSQL+`)::date+6 THEN 'committed' ELSE 'provisional' END) AS val FROM latest r WHERE NOT deleted),
		historical AS (SELECT `+rowView+` AS val FROM calendar_session_revisions r,head WHERE r.session_uid=$1 AND calendar_version_number=1 AND deleted AND legacy_payload IS NOT NULL)
		SELECT val FROM current_row UNION ALL SELECT val FROM historical WHERE NOT EXISTS(SELECT FROM current_row) LIMIT 1`, uid, now)
	return first(rows), err
}

func addPaces(laps []object, paces object) {
	for _, lap := range laps {
		lap["confirmed_pace_s_per_mile"] = nil
		saved, _ := paces[fmt.Sprint(lap["lap_index"])].(object)
		if saved == nil {
			continue
		}
		parts := []string{stringArg(lap, "start_at"), stringArg(lap, "end_at")}
		for _, k := range []string{"elapsed_s", "timer_s"} {
			s := "None"
			if n, ok := lap[k].(json.Number); ok {
				f, err := n.Float64()
				if err != nil {
					continue
				}
				b, err := canonicaljson.Metric(f)
				if err == nil {
					s = string(b)
				}
			}
			parts = append(parts, s)
		}
		index := "None"
		if v := lap["wkt_step_index"]; v != nil {
			index = fmt.Sprint(v)
		}
		parts = append(parts, index)
		if saved["lap_identity"] == strings.Join(parts, "|") {
			lap["confirmed_pace_s_per_mile"] = saved["pace_s_per_mile"]
		}
	}
}

func delayedResponse(ctx context.Context, tx pgx.Tx, id uuid.UUID, now time.Time) (object, error) {
	prompts, err := wireRows(ctx, tx, `SELECT to_jsonb(v) FROM (SELECT id,kind,activity_id,session_uid,opens_at,closes_at,CASE WHEN status='open' AND opens_at>$2 THEN 'scheduled'
		WHEN status='open' AND closes_at<=$2 THEN 'expired' ELSE status END AS status FROM prompts WHERE activity_id=$1 AND kind='delayed_symptom') v`, id, now)
	if err != nil {
		return nil, err
	}
	checks, err := wireRows(ctx, tx, `SELECT to_jsonb(v) FROM (SELECT c.id AS checkin_id,c.observed_at,c.recorded_at,c.pain_reported,c.gait_change,
		CASE WHEN c.observed_at>=a.end_at THEN (extract(epoch FROM(c.observed_at-a.end_at))/3600)::float8 END AS hours_after_end,
		coalesce((SELECT jsonb_agg(jsonb_build_object('site',s.site,'side',s.side,'severity',s.severity,'timing',s.timing) ORDER BY s.id)
		FROM symptom_reports s WHERE s.checkin_id=c.id),'[]') AS symptoms FROM checkins_v2 c JOIN activities a ON a.id=c.activity_id
		WHERE c.activity_id=$1 AND c.kind='delayed_followup' AND c.observed_at<=$2 AND c.recorded_at<=$2 ORDER BY c.observed_at DESC,c.recorded_at DESC,c.id DESC LIMIT 1) v`, id, now)
	if err != nil {
		return nil, err
	}
	if len(checks) == 0 && len(prompts) == 0 {
		return nil, nil
	}
	feedback := first(checks)
	if feedback == nil {
		feedback = object{"checkin_id": nil, "observed_at": nil, "recorded_at": nil, "hours_after_end": nil, "pain_reported": nil, "gait_change": nil, "symptoms": []any{}}
	}
	if n, ok := feedback["hours_after_end"].(json.Number); ok {
		hours, err := n.Float64()
		if err != nil {
			return nil, err
		}
		feedback["hours_after_end"] = json.Number(strconv.FormatFloat(hours, 'f', 1, 64))
	}
	feedback["prompt"] = first(prompts)
	return feedback, nil
}
