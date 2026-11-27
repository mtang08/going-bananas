package snapshotreads

import (
	"bytes"
	"context"
	"encoding/json"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/blockbenchmark"
	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
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
	if err == nil {
		b.Anchors, err = typedFloatFields(b.Anchors, "value_low", "value_high")
	}
	return b, err
}

// PostgreSQL JSON aggregates render integral float8 values without a decimal
// point. Restore the ORM column type before hashing the snapshot wire data.
func typedFloatFields(raw json.RawMessage, keys ...string) (json.RawMessage, error) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var rows []map[string]any
	if err := dec.Decode(&rows); err != nil {
		return nil, err
	}
	for _, r := range rows {
		for _, k := range keys {
			if n, ok := r[k].(json.Number); ok {
				f, err := n.Float64()
				if err != nil {
					return nil, err
				}
				r[k] = f
			}
		}
	}
	return canonicaljson.Coaching(rows)
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
), ` + blockbenchmark.Selection + `, view AS (
 SELECT s.status,s.objective,s.why,s.legacy_text,s.maintained_qualities,s.non_goals,s.eligible_recipe_ids,s.progression_dimension,
        s.constraints,s.start_date,s.review_date,s.indicators,s.early_review_triggers,s.objective_status,s.benchmark,s.target_event_id,
        s.build_outline,s.block_uid,s.id AS version_id,s.version,
        CASE WHEN s.target_event_id=(SELECT id FROM ranks WHERE rank=1) THEN 'current'
             WHEN s.target_event_id IS NOT NULL THEN 'changed' WHEN EXISTS(SELECT 1 FROM ranks) THEN 'unset' ELSE 'none' END AS target_event_status,
        ` + blockbenchmark.StatusJSON(utcISO("COALESCE(m.end_at,m.start_at)")) + ` AS benchmark_status
 FROM spec s CROSS JOIN zone LEFT JOIN matched m ON true
)
SELECT COALESCE((SELECT to_jsonb(v) FROM view v),'null'::jsonb),
       COALESCE((SELECT jsonb_agg(e ORDER BY event_date,event_id) FROM events_view e),'[]'::jsonb)`
