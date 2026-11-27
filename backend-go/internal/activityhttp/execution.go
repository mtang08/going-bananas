package activityhttp

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	refresh "github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
	"net/http"
	"strconv"
	"strings"
	"time"
)

func timestamps(row object, keys ...string) {
	for _, key := range keys {
		if s, ok := row[key].(string); ok {
			if t, err := time.Parse(time.RFC3339Nano, s); err == nil {
				row[key] = wireTime(t)
			}
		}
	}
}

// Gather delayed feedback under the same read transaction as the execution results.
func delayed(ctx context.Context, tx pgx.Tx, id uuid.UUID, now time.Time) (object, error) {
	var out object
	err := tx.QueryRow(ctx, `WITH prompt AS (SELECT * FROM prompts WHERE kind='delayed_symptom' AND activity_id=$1),
 c AS (SELECT * FROM checkins_v2 WHERE kind='delayed_followup' AND activity_id=$1 AND observed_at<=$2 AND recorded_at<=$2 ORDER BY observed_at DESC,recorded_at DESC,id DESC LIMIT 1)
 SELECT CASE WHEN p.id IS NULL AND c.id IS NULL THEN NULL ELSE jsonb_build_object(
 'prompt',CASE WHEN p.id IS NOT NULL THEN to_jsonb(p)||jsonb_build_object('status',CASE WHEN p.status='open' AND p.opens_at>$2 THEN 'scheduled' WHEN p.status='open' AND p.closes_at<=$2 THEN 'expired' ELSE p.status END) END,
 'checkin_id',c.id,'observed_at',c.observed_at,'recorded_at',c.recorded_at,'hours_after_end',CASE WHEN c.observed_at>=a.end_at THEN extract(epoch FROM (c.observed_at-a.end_at))/3600 END,
 'pain_reported',c.pain_reported,'gait_change',c.gait_change,'symptoms',coalesce((SELECT jsonb_agg(jsonb_build_object('site',site,'side',side,'severity',severity,'timing',timing) ORDER BY id) FROM symptom_reports WHERE checkin_id=c.id),'[]')) END
 FROM activities a LEFT JOIN prompt p ON true LEFT JOIN c ON true WHERE a.id=$1`, id, now).Scan(&out)
	if out != nil {
		timestamps(out, "observed_at", "recorded_at")
		if p, ok := out["prompt"].(map[string]any); ok {
			timestamps(p, "opens_at", "closes_at")
		}
		if hours, ok := out["hours_after_end"].(float64); ok {
			out["hours_after_end"] = decimal(hours, 1)
		}
	}
	return out, err
}
func prescription(ctx context.Context, tx pgx.Tx, id uuid.UUID, localDay, today string) (object, object, error) {
	var completion object
	err := tx.QueryRow(ctx, `SELECT to_jsonb(c)||jsonb_build_object('local_date',$2::text) FROM session_completions c WHERE activity_id=$1`, id, localDay).Scan(&completion)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil, nil
	}
	if err != nil {
		return nil, nil, err
	}
	timestamps(completion, "updated_at")
	var plan object
	err = tx.QueryRow(ctx, latestPlans+`, picked AS (SELECT p.*,true AS current FROM latest p WHERE session_uid=$1 AND NOT deleted
 UNION ALL SELECT p.*,false AS current FROM calendar_session_revisions p,app_state h WHERE h.id=1 AND h.calendar_head_version>0 AND p.session_uid=$1 AND p.calendar_version_number=1 AND p.deleted AND p.legacy_payload IS NOT NULL)
 SELECT (to_jsonb(p)-'current')||jsonb_build_object('is_original',p.revision=1,'changed_by_version',p.calendar_version_number,
 'certainty',CASE WHEN NOT p.current THEN p.certainty WHEN p.local_date<=$2::text::date+6 THEN 'committed' ELSE 'provisional' END) FROM picked p ORDER BY current DESC LIMIT 1`, completion["session_uid"], today).Scan(&plan)
	if errors.Is(err, pgx.ErrNoRows) {
		err = nil
	}
	return plan, completion, err
}
func (h Handler) execution(ctx context.Context, tx pgx.Tx, r *http.Request, now time.Time, loc *time.Location) (any, error) {
	id, err := activityID(r)
	if err != nil {
		return nil, err
	}
	var activity object
	var saved map[string]struct {
		Identity string  `json:"lap_identity"`
		Pace     float64 `json:"pace_s_per_mile"`
	}
	err = tx.QueryRow(ctx, `SELECT jsonb_build_object('id',id,'start_at',start_at,'end_at',end_at,'local_date',(start_at AT TIME ZONE $2)::date,
 'sport',sport,'distance_m',distance_m,'timer_s',timer_s,'elapsed_s',elapsed_s,'fit_status',fit_status),treadmill_interval_paces FROM activities WHERE id=$1`, id, loc.String()).Scan(&activity, &saved)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, &problem{404, "activity_not_found", "Activity not found", nil}
	}
	if err != nil {
		return nil, err
	}
	sport := activity["sport"].(string)
	if !isRun(sport) {
		return nil, &problem{422, "not_run_activity", "Activity is not a run", nil}
	}
	timestamps(activity, "start_at", "end_at")
	plan, completion, err := prescription(ctx, tx, id, activity["local_date"].(string), now.In(loc).Format(time.DateOnly))
	if err != nil {
		return nil, err
	}
	out := object{"activity": activity, "planned": plan, "completion": completion, "planned_actual": nil, "symptoms": []any{}}
	names := map[string]string{"work_interval_execution": "intervals", "intensity_time_distribution": "intensity", "aerobic_efficiency": "aerobic", "session_rpe_load": "load", "symptom_response_timeline": "response"}
	for metric, name := range names {
		row, err := refresh.ReadResult(ctx, tx, metric, id.String(), now)
		if err != nil {
			return nil, err
		}
		if name == "aerobic" && row != nil && row["id"] == nil {
			row["window_start"] = activity["start_at"]
			row["window_end"] = activity["end_at"]
		}
		if row != nil {
			timestamps(row, "window_start", "window_end", "calculated_at")
		}
		out[name] = row
	}
	if completion != nil {
		row, err := refresh.ReadResult(ctx, tx, "planned_actual_session", completion["session_uid"].(string), now)
		if err != nil {
			return nil, err
		}
		out["planned_actual"] = row
	}
	feedback, err := delayed(ctx, tx, id, now)
	if err != nil {
		return nil, err
	}
	out["delayed_response"] = feedback
	value := func(key string) object {
		row, _ := out[key].(object)
		val, _ := row["value"].(object)
		delete(out, key)
		return val
	}
	load := value("load")
	symptoms := value("response")
	if reports := symptoms["reports"]; reports != nil {
		out["symptoms"] = reports
	}
	var manual, garmin *float64
	err = tx.QueryRow(ctx, `SELECT (SELECT rpe::float8 FROM session_rpe WHERE source='manual' AND activity_id=$1),coalesce((SELECT rpe::float8 FROM session_rpe WHERE source='garmin_fit' AND activity_id=$1),workout_rpe::float8) FROM activities WHERE id=$1`, id).Scan(&manual, &garmin)
	if err != nil {
		return nil, err
	}
	var source any
	effective := garmin
	if manual != nil {
		source = "manual"
		effective = manual
	} else if garmin != nil {
		source = "garmin_fit"
	}
	out["rpe"] = object{"effective": effective, "source": source, "manual": manual, "garmin_fit": garmin, "srpe_load_au": load["load_au"]}
	var laps, watch []object
	err = tx.QueryRow(ctx, `SELECT coalesce(jsonb_agg(to_jsonb(l)-'activity_id'-'id' ORDER BY lap_index),'[]') FROM activity_laps l WHERE activity_id=$1`, id).Scan(&laps)
	if err != nil {
		return nil, err
	}
	for _, l := range laps {
		if sport == "treadmill_running" {
			l["confirmed_pace_s_per_mile"] = nil
			key := strconv.Itoa(int(l["lap_index"].(float64)))
			if p, ok := saved[key]; ok && p.Identity == lapIdentity(l) {
				l["confirmed_pace_s_per_mile"] = p.Pace
			}
		}
		timestamps(l, "start_at", "end_at")
	}
	err = tx.QueryRow(ctx, `SELECT coalesce(jsonb_agg(to_jsonb(s)-'activity_id'-'id' ORDER BY message_index),'[]') FROM activity_workout_steps s WHERE activity_id=$1`, id).Scan(&watch)
	out["laps"] = laps
	out["watch_steps"] = watch
	return out, err
}
func lapIdentity(l object) string {
	bound := func(k string) string {
		if v, ok := l[k].(string); ok {
			if t, err := time.Parse(time.RFC3339Nano, v); err == nil {
				return dateStamp(t.UTC())
			}
		}
		return ""
	}
	number := func(k string) string {
		v, ok := l[k].(float64)
		if !ok {
			return "None"
		}
		if k == "wkt_step_index" {
			return strconv.Itoa(int(v))
		}
		s := strconv.FormatFloat(v, 'g', -1, 64)
		if !strings.ContainsAny(s, ".e") {
			s += ".0"
		}
		return s
	}
	return strings.Join([]string{bound("start_at"), bound("end_at"), number("elapsed_s"), number("timer_s"), number("wkt_step_index")}, "|")
}
