package weeklydigest

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/weeklyprojection"
)

func plannedDuration(s row, raw json.RawMessage) any {
	return nullable(weeklyprojection.PlannedDuration(num(s["planned_duration_s"]), raw))
}

func followUp(ctx context.Context, tx pgx.Tx, rows, planned []row, today string, now time.Time) (row, error) {
	due := map[string]row{}
	ids, keys, dates := []string{}, []bool{}, []string{}
	for _, s := range rows {
		if s["kind"] != "run" || s["local_date"].(string) > today || s["outcome"] == "planned" {
			continue
		}
		id := s["session_uid"].(string)
		due[id] = s
		ids = append(ids, id)
		keys = append(keys, s["key"].(bool))
		dates = append(dates, s["local_date"].(string))
	}
	if len(due) == 0 {
		return nil, nil
	}
	var ref row
	err := tx.QueryRow(ctx, `SELECT json_build_object('session_uid',r.session_uid,'revision',r.revision,'local_date',r.local_date,'intent',r.intent,
		'planned_duration_s',r.planned_duration_s,'planned_distance_m',r.planned_distance_m,'structure',r.structure::text,
		'effort',r.brief->'effort','op',c.op,'reason',c.reason,'proposal_id',p.id,'next_check',p.next_check)
		FROM unnest($1::uuid[],$2::boolean[],$3::text[]) d(id,key,day) JOIN coach_proposal_changes c ON c.session_uid=d.id
		JOIN coach_proposals p ON p.id=c.proposal_id JOIN calendar_versions v ON v.proposal_id=p.id
		JOIN calendar_session_revisions r ON r.calendar_version_number=v.number AND r.session_uid=c.session_uid
		WHERE c.decision='accepted' AND c.op IN ('add','move','modify') AND p.status IN ('accepted','partially_accepted')
		AND p.decided_at<=$4 AND r.kind='run' AND NOT r.deleted AND NOT r.placeholder
		ORDER BY v.number DESC,(c.op!='add') DESC,d.key DESC,d.day DESC,r.session_uid DESC LIMIT 1`, ids, keys, dates, now).Scan(&ref)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	id := ref["session_uid"].(string)
	s := due[id]
	accepted := pick(ref, "local_date", "intent", "effort")
	raw := structure(ref)
	accepted["duration_s"] = plannedDuration(ref, raw)
	distance, estimated := weeklyprojection.PlannedDistance(num(ref["planned_distance_m"]), nil, raw, nil)
	accepted["distance_m"] = nil
	if !estimated {
		accepted["distance_m"] = nullable(distance)
	}
	var response, actual row
	if a, ok := s["actual"].(map[string]any); ok {
		actual = pick(a, "id", "subject", "local_date", "duration_s", "distance_m", "rpe")
		if a["subject"] == "activity" {
			response, err = delayedResponse(ctx, tx, a["id"].(string), now)
			if err != nil {
				return nil, err
			}
		}
	}
	result := pick(ref, "session_uid", "op", "reason", "proposal_id", "next_check")
	result["accepted"], result["actual"], result["response"] = accepted, optionalRow(actual), optionalRow(response)
	result["outcome"], result["modification_reason"] = s["outcome"], s["modification_reason"]
	for _, p := range planned {
		if p["session_uid"] == id {
			result["edited_since"] = p["revision"] != ref["revision"]
			break
		}
	}
	return result, nil
}

func delayedResponse(ctx context.Context, tx pgx.Tx, id string, now time.Time) (row, error) {
	var r row
	var observed time.Time
	var end *time.Time
	query := tx.QueryRow(ctx, `SELECT json_build_object('pain_reported',c.pain_reported,'gait_change',c.gait_change,
	'symptoms',coalesce((SELECT json_agg(json_build_object('site',s.site,'side',s.side,'severity',s.severity,'timing',s.timing)
	ORDER BY s.id) FROM symptom_reports s WHERE s.checkin_id=c.id),'[]')),c.observed_at,a.end_at,current_setting('TimeZone')
	FROM checkins_v2 c JOIN activities a ON a.id=c.activity_id WHERE c.kind='delayed_followup' AND c.activity_id=$1
	AND c.observed_at<=$2 AND c.recorded_at<=$2 ORDER BY c.observed_at DESC,c.recorded_at DESC,c.id DESC LIMIT 1`, id, now)
	var zone string
	if e := query.Scan(&r, &observed, &end, &zone); errors.Is(e, pgx.ErrNoRows) {
		return nil, nil
	} else if e != nil {
		return nil, e
	}
	loc, e := time.LoadLocation(zone)
	if e != nil {
		return nil, e
	}
	layout := "2006-01-02T15:04:05"
	if observed.Nanosecond() != 0 {
		layout += ".000000"
	}
	r["observed_at"] = observed.In(loc).Format(layout + "-07:00")
	r["hours_after_end"] = nil
	if end != nil && !observed.Before(*end) {
		r["hours_after_end"] = rounded(observed.Sub(*end).Hours())
	}
	return r, nil
}
