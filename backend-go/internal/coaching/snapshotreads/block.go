package snapshotreads

import (
	"context"
	"encoding/json"

	"github.com/jackc/pgx/v5"
)

// Block groups the live block, event, intensity calibration and proposal history projections.
type Block struct {
	ActiveBlock      json.RawMessage `json:"active_block"`
	BlockDecisions   json.RawMessage `json:"block_decisions"`
	BenchmarkHistory json.RawMessage `json:"benchmark_history"`
	Events           json.RawMessage `json:"events"`
	Anchors          json.RawMessage `json:"anchors"`
	Proposals        json.RawMessage `json:"proposals"`
}

func LoadBlock(ctx context.Context, tx pgx.Tx, asOf string) (Block, error) {
	var b Block
	if err := tx.QueryRow(ctx, blockSQL, asOf).Scan(&b.ActiveBlock, &b.Events); err != nil {
		return b, err
	}
	err := tx.QueryRow(ctx, blockHistorySQL).Scan(&b.BlockDecisions, &b.BenchmarkHistory, &b.Anchors, &b.Proposals)
	return b, err
}

// Python's canonical datetime string uses six fractional digits when there are
// microseconds and no fractional part for whole seconds, always in UTC.
func utcISO(column string) string {
	return "to_char(" + column + " AT TIME ZONE 'UTC', CASE WHEN mod(extract(microseconds FROM " + column + ")::int,1000000)=0 THEN 'YYYY-MM-DD\"T\"HH24:MI:SS' ELSE 'YYYY-MM-DD\"T\"HH24:MI:SS.US' END) || '+00:00'"
}

var blockHistorySQL = `
WITH decisions AS (
 SELECT decision, from_version, to_version, rationale, confidence, ` + utcISO("decided_at") + ` AS decided_at,
        proposal_id,block_uid,id FROM block_decisions
), history AS (
 SELECT b.block_uid,v.objective,b.protocol,b.distance_m,b.local_date,b.result_s,b.outcome,b.updated_at
 FROM block_benchmarks b LEFT JOIN block_versions v ON v.block_uid=b.block_uid AND v.version=b.block_version
 WHERE b.outcome IS NOT NULL ORDER BY b.local_date DESC NULLS LAST,b.updated_at DESC LIMIT 6
), anchors AS (
 SELECT anchor_key, kind, value_low, value_high, unit, protocol, confidence, status,
        ` + utcISO("calibrated_at") + ` AS calibrated_at, valid_from, review_after, supersedes_key FROM intensity_anchors
), recent AS (
 SELECT * FROM coach_proposals WHERE status!='invalid' ORDER BY submitted_at DESC,id DESC LIMIT 20
), proposals AS (
 SELECT p.id AS proposal_id,p.operation,p.status,` + utcISO("p.submitted_at") + ` AS submitted_at,
        ` + utcISO("p.decided_at") + ` AS decided_at,p.headline,p.next_check,
        COALESCE((
          SELECT jsonb_agg(jsonb_build_object('change_id',c.change_id,'op',c.op,'session_uid',c.session_uid,
                    'decision',c.decision,'before',c.before,'after',c.after) ||
                 CASE WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(p.payload->'changes') entry
                        WHERE entry->>'change_id'=c.change_id AND (entry->'material_flags') ? 'strength_omission')
                      THEN jsonb_build_object('material_flags',jsonb_build_array('strength_omission'),'reason',c.reason)
                      ELSE '{}'::jsonb END ORDER BY c.change_id)
          FROM coach_proposal_changes c WHERE c.proposal_id=p.id
        ),'[]'::jsonb) AS changes
 FROM recent p
)
SELECT
 COALESCE((SELECT jsonb_agg(to_jsonb(d)-'id' ORDER BY d.decided_at::timestamptz,d.id) FROM decisions d),'[]'::jsonb),
 COALESCE((SELECT jsonb_agg(to_jsonb(h)-'updated_at' ORDER BY local_date DESC NULLS LAST,updated_at DESC) FROM history h),'[]'::jsonb),
 COALESCE((SELECT jsonb_agg(a ORDER BY valid_from,calibrated_at::timestamptz,anchor_key) FROM anchors a),'[]'::jsonb),
 COALESCE((SELECT jsonb_agg(p ORDER BY submitted_at::timestamptz DESC,proposal_id DESC) FROM proposals p),'[]'::jsonb)`

var blockSQL = `
WITH ranks AS (
 SELECT id, row_number() OVER(ORDER BY rank NULLS LAST,event_date,id) AS rank
 FROM events WHERE status IN ('planned','registered') AND event_date >= $1::date
), events_view AS (
 SELECT e.id AS event_id, e.name,e.event_date,e.distance_m,e.purpose,e.goal_time_s,
        CASE WHEN e.distance_m!=0 AND e.goal_time_s!=0 THEN trunc(e.goal_time_s::float8*1000/e.distance_m+0.5)::bigint END AS goal_pace_s_per_km,
        ranks.rank,e.status,e.result_s FROM events e LEFT JOIN ranks ON ranks.id=e.id WHERE e.event_date >= $1::date-28
), latest AS (
 SELECT DISTINCT ON (block_uid) * FROM block_versions ORDER BY block_uid,version DESC
), active AS (
 SELECT * FROM latest WHERE status IN ('active','consolidating') ORDER BY created_at DESC,version DESC,id DESC LIMIT 1
), spec AS (
 SELECT b.*, b.benchmark->>'kind' AS kind,(b.benchmark->>'event_id')::uuid AS event_id,
        (b.benchmark->>'planned_date')::date-3 AS first,b.review_date+7 AS last FROM active b
), zone AS (
 SELECT coalesce((SELECT nullif(timezone,'') FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York') AS name
), calendar_head AS (
 SELECT DISTINCT ON (session_uid) session_uid,local_date,kind,recipe_id,deleted
 FROM calendar_session_revisions WHERE calendar_version_number <= COALESCE((SELECT calendar_head_version FROM app_state WHERE id=1),0)
 ORDER BY session_uid,calendar_version_number DESC,revision DESC
), scheduled AS (
 SELECT c.session_uid,c.local_date FROM calendar_head c,spec WHERE NOT c.deleted AND c.kind='run' AND c.recipe_id='REC009'
 AND c.local_date BETWEEN spec.first AND spec.last
), manual_match AS (
 SELECT a.id FROM block_benchmarks b JOIN spec ON b.block_uid=spec.block_uid AND b.block_version=spec.version
 JOIN activities a ON a.id=b.activity_id WHERE b.match_method='manual' AND spec.kind IS NOT NULL
), trial_match AS (
 SELECT c.activity_id AS id FROM scheduled s JOIN session_completions c USING (session_uid),spec
 WHERE spec.kind='time_trial' AND c.activity_id IS NOT NULL ORDER BY s.local_date DESC,s.session_uid DESC LIMIT 1
), event_match AS (
 SELECT a.id,e.result_s FROM spec JOIN events e ON e.id=spec.event_id
 CROSS JOIN zone JOIN activities a ON (a.start_at AT TIME ZONE zone.name)::date=e.event_date
 WHERE spec.kind='event' AND e.event_date BETWEEN spec.first AND spec.last
 AND a.sport IN ('running','trail_running','treadmill_running') AND a.resolution_state='resolved'
 AND NOT COALESCE((SELECT excluded FROM activity_annotations WHERE activity_id=a.id ORDER BY version DESC LIMIT 1),false)
 ORDER BY COALESCE(a.distance_m,0) DESC,a.start_at DESC,a.id LIMIT 1
), candidates AS (
 SELECT id,'manual' AS method, NULL::integer AS result_override,1 AS priority FROM manual_match UNION ALL
 SELECT id,'auto',NULL,2 FROM trial_match UNION ALL SELECT id,'auto',result_s,2 FROM event_match
), matched AS (
 SELECT a.*,c.method,c.result_override FROM candidates c JOIN activities a USING (id) ORDER BY c.priority LIMIT 1
), view AS (
 SELECT s.status,s.objective,s.why,s.legacy_text,s.maintained_qualities,s.non_goals,s.eligible_recipe_ids,s.progression_dimension,
        s.constraints,s.start_date,s.review_date,s.indicators,s.early_review_triggers,s.objective_status,s.benchmark,s.target_event_id,
        s.build_outline,s.block_uid,s.id AS version_id,s.version,
        CASE WHEN s.target_event_id=(SELECT id FROM ranks WHERE rank=1) THEN 'current'
             WHEN s.target_event_id IS NOT NULL THEN 'changed' WHEN EXISTS(SELECT 1 FROM ranks) THEN 'unset' ELSE 'none' END AS target_event_status,
        jsonb_build_object('status',CASE WHEN s.kind IS NULL THEN 'not_set' WHEN m.id IS NOT NULL THEN 'completed'
                     WHEN $1::date <= s.review_date+2 THEN 'pending' ELSE 'missed' END,
          'match_method',m.method,'activity_id',m.id,'event_id',s.event_id,'local_date',(m.start_at AT TIME ZONE zone.name)::date,
          'distance_m',round(m.distance_m)::bigint,'result_s',COALESCE(m.result_override,round(m.timer_s)::bigint),
          'rpe',COALESCE((SELECT rpe FROM session_rpe WHERE activity_id=m.id AND source IN ('manual','garmin_fit')
                    ORDER BY (source='manual') DESC,collected_at DESC,id DESC LIMIT 1),m.workout_rpe),
          'scheduled_date',(SELECT max(local_date) FROM scheduled),'evidence_at',` + utcISO("COALESCE(m.end_at,m.start_at)") + `) AS benchmark_status
 FROM spec s CROSS JOIN zone LEFT JOIN matched m ON true
)
SELECT COALESCE((SELECT to_jsonb(v) FROM view v),'null'::jsonb),
       COALESCE((SELECT jsonb_agg(e ORDER BY event_date,event_id) FROM events_view e),'[]'::jsonb)`
