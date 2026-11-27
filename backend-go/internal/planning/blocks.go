package planning

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/blockbenchmark"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
)

func sessionTime(column string) string {
	return "(to_char(" + column + ", 'YYYY-MM-DD\"T\"HH24:MI:SS') || CASE WHEN mod(extract(microseconds from " + column + ")::int,1000000)=0 THEN '' ELSE to_char(" + column + ",'.US') END || CASE WHEN extract(timezone from " + column + ")=0 THEN 'Z' ELSE to_char(" + column + ",'TZH:TZM') END)"
}

var blockRow = "to_jsonb(b) || jsonb_build_object('created_at'," + sessionTime("b.created_at") + ")"

func jsonRow(ctx context.Context, tx pgx.Tx, query string, args ...any) (json.RawMessage, error) {
	var data json.RawMessage
	err := tx.QueryRow(ctx, query, args...).Scan(&data)
	return data, err
}
func ensure(ctx context.Context, tx pgx.Tx, query string, id uuid.UUID, code, message string) error {
	var ok bool
	if err := tx.QueryRow(ctx, query, id).Scan(&ok); err != nil {
		return err
	}
	if !ok {
		return &Problem{404, code, message}
	}
	return nil
}
func BlockHistory(ctx context.Context, tx pgx.Tx, id uuid.UUID) (json.RawMessage, error) {
	if err := ensure(ctx, tx, "SELECT EXISTS(SELECT FROM blocks WHERE block_uid=$1)", id, "block_not_found", "Block not found"); err != nil {
		return nil, err
	}
	return jsonRow(ctx, tx, "SELECT coalesce(jsonb_agg(("+blockRow+") ORDER BY version,id),'[]') FROM block_versions b WHERE block_uid=$1", id)
}
func EventBlocks(ctx context.Context, tx pgx.Tx, id uuid.UUID) (json.RawMessage, error) {
	if err := ensure(ctx, tx, "SELECT EXISTS(SELECT FROM events WHERE id=$1)", id, "event_not_found", "Event not found"); err != nil {
		return nil, err
	}
	return jsonRow(ctx, tx, `WITH grouped AS (SELECT b.*,coalesce((SELECT max(to_version) FROM block_decisions d WHERE d.block_uid=b.block_uid AND decision IN ('start','transition','replace') AND to_version<=b.version),0) AS first FROM block_versions b WHERE target_event_id=$1),
 latest AS (SELECT DISTINCT ON (block_uid,first) block_uid,version,status,objective,start_date,review_date,benchmark,build_outline FROM grouped ORDER BY block_uid,first,version DESC)
 SELECT coalesce(jsonb_agg(latest ORDER BY start_date,block_uid,version),'[]') FROM latest`, id)
}
func BenchmarkHistory(ctx context.Context, tx pgx.Tx) (json.RawMessage, error) {
	return jsonRow(ctx, tx, `SELECT coalesce(jsonb_agg((to_jsonb(r)-'updated_at'-'proposal_id') || jsonb_build_object('objective',b.objective) ORDER BY r.local_date DESC NULLS LAST,r.updated_at DESC),'[]') FROM block_benchmarks r JOIN block_versions b ON (r.block_uid,r.block_version)=(b.block_uid,b.version) WHERE outcome IS NOT NULL`)
}

var statusProjection = blockbenchmark.StatusJSON(sessionTime("COALESCE(m.end_at,m.start_at)"))

func benchmarkView(ctx context.Context, tx pgx.Tx, today string) (json.RawMessage, error) {
	return jsonRow(ctx, tx, "WITH "+blockbenchmark.Selection+" SELECT jsonb_build_object('benchmark',s.benchmark,'benchmark_status',"+statusProjection+") FROM spec s CROSS JOIN zone LEFT JOIN matched m ON true", today)
}
func SetBenchmark(ctx context.Context, tx pgx.Tx, block uuid.UUID, activity *uuid.UUID, today string) (json.RawMessage, error) {
	var version int
	var spec json.RawMessage
	err := tx.QueryRow(ctx, "WITH "+blockbenchmark.Selection+" SELECT version,benchmark FROM active WHERE block_uid=$1", block).Scan(&version, &spec)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, &Problem{404, "block_not_found", "Block not found"}
	}
	if err != nil {
		return nil, err
	}
	var input struct {
		Protocol string
		Event    *uuid.UUID `json:"event_id"`
	}
	if len(spec) > 0 {
		if err = json.Unmarshal(spec, &input); err != nil {
			return nil, err
		}
	}
	if input.Protocol == "" {
		return nil, &Problem{409, "benchmark_not_set", "The active block has no benchmark"}
	}
	if activity == nil {
		_, err = tx.Exec(ctx, `UPDATE block_benchmarks SET match_method='auto',activity_id=NULL,distance_m=NULL,local_date=NULL,result_s=NULL,updated_at=clock_timestamp() WHERE block_uid=$1 AND block_version=$2`, block, version)
	} else {
		tag, e := tx.Exec(ctx, `INSERT INTO block_benchmarks(id,block_uid,block_version,match_method,activity_id,event_id,protocol,distance_m,local_date,result_s,updated_at)
 SELECT gen_random_uuid(),$1,$2,'manual',id,$3,$4,round(distance_m::float8),(start_at AT TIME ZONE coalesce((SELECT timezone FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York'))::date,round(timer_s::float8),clock_timestamp() FROM activities WHERE id=$5 AND sport IN ('running','trail_running','treadmill_running')
 ON CONFLICT(block_uid,block_version) DO UPDATE SET match_method='manual',activity_id=excluded.activity_id,event_id=excluded.event_id,protocol=excluded.protocol,distance_m=excluded.distance_m,local_date=excluded.local_date,result_s=excluded.result_s,updated_at=excluded.updated_at`, block, version, input.Event, input.Protocol, *activity)
		err = e
		if err == nil && tag.RowsAffected() == 0 {
			return nil, &Problem{404, "activity_not_found", "Activity not found"}
		}
	}
	if err != nil {
		return nil, err
	}
	return benchmarkView(ctx, tx, today)
}
func ActiveBlock(ctx context.Context, tx pgx.Tx, today, kbRoot string) (map[string]any, error) {
	var b map[string]any
	var uid uuid.UUID
	var version int
	var target *uuid.UUID
	err := tx.QueryRow(ctx, "WITH "+blockbenchmark.Selection+" SELECT "+blockRow+",b.block_uid,b.version,b.target_event_id FROM active b").Scan(&b, &uid, &version, &target)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	bv, err := benchmarkView(ctx, tx, today)
	if err != nil {
		return nil, err
	}
	if err = json.Unmarshal(bv, &b); err != nil {
		return nil, err
	}
	events, err := Events(ctx, tx, today)
	if err != nil {
		return nil, err
	}
	b["target_event"] = nil
	b["target_event_status"] = "none"
	if target != nil {
		b["target_event_status"] = "changed"
	}
	for _, e := range events {
		if target == nil && e.Rank != nil {
			b["target_event_status"] = "unset"
		}
		if target != nil && *target == e.ID {
			b["target_event"] = map[string]any{"id": e.ID, "name": e.Name, "event_date": e.Date, "distance_m": e.Distance, "purpose": e.Purpose, "goal_time_s": e.GoalTime, "rank": e.Rank}
			if e.Rank != nil && *e.Rank == 1 {
				b["target_event_status"] = "current"
			}
		}
	}
	var evidence, policies []string
	err = tx.QueryRow(ctx, "SELECT evidence_ids,policy_ids FROM block_decisions WHERE block_uid=$1 AND to_version=$2 ORDER BY decided_at DESC LIMIT 1", uid, version).Scan(&evidence, &policies)
	b["sources"] = []coaching.Citation{}
	if errors.Is(err, pgx.ErrNoRows) {
		return b, nil
	}
	if err != nil {
		return nil, err
	}
	if citations, e := coaching.CitedSources(kbRoot, evidence, policies); e == nil {
		b["sources"] = citations
	}
	return b, nil
}
