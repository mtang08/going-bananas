package drafts

import (
	"context"
	"encoding/json"
	"errors"
	"slices"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/evidence"
)

const latestSessions = `WITH latest AS (
 SELECT DISTINCT ON(session_uid) * FROM calendar_session_revisions WHERE calendar_version_number <= $1
 ORDER BY session_uid,calendar_version_number DESC,revision DESC
) SELECT session_uid::text, jsonb_build_object('session_uid',session_uid,'revision',revision,
 'local_date',local_date,'slot',slot,'kind',kind,'recipe_id',recipe_id,'custom',custom,'placeholder',placeholder,
 'locked',locked,'legacy_unstructured',legacy_unstructured,'intent',intent,'certainty',
 CASE WHEN local_date <= $2::date + 6 THEN 'committed' ELSE 'provisional' END,
 'planned_duration_s',planned_duration_s,'planned_distance_m',planned_distance_m,'structure',structure,
 'strength_slot_id',strength_slot_id,'brief',brief)
 FROM latest WHERE NOT deleted`

func slots(rows []map[string]any) (map[string]bool, map[string]string) {
	days := map[string]bool{}
	ids := map[string]string{}
	for _, r := range rows {
		d, _ := r["local_date"].(string)
		days[d] = true
		if id, ok := r["strength_slot_id"].(string); ok && id != "" {
			ids[d] = id
		}
	}
	return days, ids
}

func readMap[T any](ctx context.Context, tx pgx.Tx, query string, args ...any) (map[string]T, error) {
	rows, err := tx.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[string]T{}
	for rows.Next() {
		var key string
		var val T
		if err := rows.Scan(&key, &val); err != nil {
			return nil, err
		}
		out[key] = val
	}
	return out, rows.Err()
}

func benchmarkContext(ctx context.Context, tx pgx.Tx, c RuleContext, block uuid.UUID, version int, spec struct {
	Kind    string `json:"kind"`
	EventID string `json:"event_id"`
	Day     string `json:"planned_date"`
}) (*Benchmark, error) {
	if spec.Kind == "" {
		return &Benchmark{Status: "not_set"}, nil
	}
	b := &Benchmark{Status: "pending", EventID: spec.EventID}
	if c.Today > dayOffset(c.ReviewDate, 2) {
		b.Status = "missed"
	}
	first, last := dayOffset(spec.Day, -3), dayOffset(c.ReviewDate, 7)
	var manual, auto string
	err := tx.QueryRow(ctx, "SELECT activity_id::text FROM block_benchmarks WHERE block_uid=$1 AND block_version=$2 AND match_method='manual' AND activity_id IS NOT NULL", block, version).Scan(&manual)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, err
	}
	if manual == "" {
		switch spec.Kind {
		case "event":
			ev, ok := c.Events[spec.EventID]
			if ok && inWindow(ev.Day, first, last) {
				err = tx.QueryRow(ctx, `SELECT a.id::text FROM activities a LEFT JOIN LATERAL (
				 SELECT excluded FROM activity_annotations WHERE activity_id=a.id ORDER BY version DESC LIMIT 1
				) annot ON true WHERE a.sport IN ('running','trail_running','treadmill_running') AND a.resolution_state='resolved'
				AND (a.start_at AT TIME ZONE $1)::date=$2::date AND NOT coalesce(annot.excluded,false)
				ORDER BY coalesce(a.distance_m,0) DESC,a.start_at DESC,a.id LIMIT 1`, c.Timezone, ev.Day).Scan(&auto)
				if err != nil && !errors.Is(err, pgx.ErrNoRows) {
					return nil, err
				}
			}
		case "time_trial":
			var ids []string
			for uid, h := range c.HeadSessions {
				if h.Kind == "run" && h.Recipe == "REC009" && inWindow(h.LocalDate, first, last) {
					ids = append(ids, uid)
				}
			}
			slices.SortFunc(ids, func(a, b string) int {
				if c.HeadSessions[a].LocalDate < c.HeadSessions[b].LocalDate {
					return 1
				}
				if c.HeadSessions[a].LocalDate > c.HeadSessions[b].LocalDate {
					return -1
				}
				if a < b {
					return 1
				}
				if a > b {
					return -1
				}
				return 0
			})
			if len(ids) > 0 {
				err = tx.QueryRow(ctx, `SELECT activity_id::text FROM session_completions WHERE session_uid::text=ANY($1::text[]) AND activity_id IS NOT NULL ORDER BY array_position($1::text[],session_uid::text) LIMIT 1`, ids).Scan(&auto)
				if err != nil && !errors.Is(err, pgx.ErrNoRows) {
					return nil, err
				}
			}
		}
	}
	id := manual
	if id == "" {
		id = auto
	}
	if id != "" {
		err := tx.QueryRow(ctx, `SELECT (start_at AT TIME ZONE $1)::date::text FROM activities WHERE id=$2`, c.Timezone, id).Scan(&b.Day)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return nil, err
		}
		if err == nil {
			b.Status, b.ActivityID = "completed", id
		}
	}
	return b, nil
}

// LoadRuleContext reads all validation facts from the transaction that owns the
// planner lock. Input evidence and recurrence are reused by the freshness gate.
func LoadRuleContext(ctx context.Context, tx pgx.Tx, s Snapshot, now time.Time) (RuleContext, CurrentEvidence, error) {
	var c RuleContext
	var current CurrentEvidence
	inputs, err := evidence.CollectInputs(ctx, tx, s.Operation, s.AsOf, now)
	if err != nil {
		return c, current, err
	}
	current.Sources = inputs.Sources
	guard, err := json.Marshal(inputs.SafetyGuard)
	if err != nil {
		return c, current, err
	}
	if err = json.Unmarshal(guard, &c.Guard); err != nil {
		return c, current, err
	}
	c.ConfirmedDates, c.ConfirmedSlots = slots(inputs.ConfirmedStrengthSessions)
	rows, _ := inputs.Sources["accepted_strength_omissions"].([]map[string]any)
	c.OmittedDates, c.OmittedSlots = slots(rows)
	var facts struct {
		Restriction  *restriction  `json:"running_restriction"`
		Interruption *interruption `json:"running_interruption"`
	}
	c.Timezone = "America/New_York"
	err = tx.QueryRow(ctx, `SELECT coalesce(nullif(timezone,''),'America/New_York'),coalesce(CASE WHEN anchor_confirmed THEN cycle_anchor::text END,''),facts FROM profile_versions ORDER BY version DESC LIMIT 1`).Scan(&c.Timezone, &c.CycleAnchor, &facts)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return c, current, err
	}
	c.Restriction, c.Interruption = facts.Restriction, facts.Interruption
	zone, err := time.LoadLocation(c.Timezone)
	if err != nil {
		return c, current, err
	}
	c.Today = now.In(zone).Format(time.DateOnly)
	current.Today = c.Today
	if err := tx.QueryRow(ctx, "SELECT calendar_head_version FROM app_state WHERE id=1").Scan(&current.Head); err != nil {
		return c, current, err
	}
	c.HeadSessions, err = readMap[sessionFields](ctx, tx, latestSessions, current.Head, c.Today)
	if err != nil {
		return c, current, err
	}
	c.Events, err = readMap[Event](ctx, tx, `WITH ranks AS (SELECT id,row_number() OVER(ORDER BY rank NULLS LAST,event_date,id) AS rank FROM events WHERE status IN ('planned','registered') AND event_date >= $1::date)
	 SELECT e.id::text,jsonb_build_object('status',e.status,'day',e.event_date,'rank',r.rank) FROM events e LEFT JOIN ranks r USING(id)`, c.Today)
	if err != nil {
		return c, current, err
	}
	c.Findings, err = readMap[string](ctx, tx, "SELECT id::text,status FROM exception_findings")
	if err != nil {
		return c, current, err
	}
	c.Patches, err = readMap[string](ctx, tx, "SELECT id::text,status FROM exception_patches")
	if err != nil {
		return c, current, err
	}
	if err := tx.QueryRow(ctx, "SELECT coalesce(array_agg(DISTINCT rule_code),'{}') FROM exception_findings WHERE status='open'").Scan(&c.OpenCodes); err != nil {
		return c, current, err
	}
	if err := tx.QueryRow(ctx, "SELECT coalesce(max(local_date)::text,'') FROM block_benchmarks WHERE outcome IN ('progress','consolidate','recalibrate_only')").Scan(&c.LastBenchmark); err != nil {
		return c, current, err
	}
	var id, block uuid.UUID
	var version int
	var spec struct {
		Kind    string `json:"kind"`
		EventID string `json:"event_id"`
		Day     string `json:"planned_date"`
	}
	err = tx.QueryRow(ctx, `SELECT id,block_uid,version,eligible_recipe_ids,review_date::text,coalesce(benchmark,'{}'::jsonb) FROM (
		SELECT DISTINCT ON(block_uid) * FROM block_versions ORDER BY block_uid,version DESC
	) b WHERE status IN ('active','consolidating') ORDER BY created_at DESC, version DESC,id DESC LIMIT 1`).Scan(&id, &block, &version, &c.EligibleRecipes, &c.ReviewDate, &spec)
	if errors.Is(err, pgx.ErrNoRows) {
		return c, current, nil
	}
	if err != nil {
		return c, current, err
	}
	current.BlockID = &id
	c.BlockUID = block.String()
	c.Benchmark, err = benchmarkContext(ctx, tx, c, block, version, spec)
	return c, current, err
}

func projectChanges(payload json.RawMessage, c RuleContext) ([]Change, error) {
	var doc struct {
		Changes []changeRequest `json:"changes"`
	}
	if err := json.Unmarshal(payload, &doc); err != nil {
		return nil, err
	}
	items := make([]Change, 0, len(doc.Changes))
	for _, ch := range doc.Changes {
		change := Change{ID: ch.ID, Operation: ch.Op, Reason: ch.Reason, Decision: "pending"}
		if ch.SessionUID != "" {
			id, err := uuid.Parse(ch.SessionUID)
			if err != nil {
				return nil, err
			}
			change.SessionUID = &id
			if h, ok := c.HeadSessions[ch.SessionUID]; ok {
				change.Before, err = json.Marshal(h.raw)
				if err != nil {
					return nil, err
				}
			}
		}
		if ch.After != nil {
			var err error
			if ch.Op == "add" && slices.Contains(ch.Flags, "strength_omission") {
				if slot := c.ConfirmedSlots[ch.After.LocalDate]; slot != "" {
					ch.After.raw["strength_slot_id"], err = json.Marshal(slot)
					if err != nil {
						return nil, err
					}
				}
			}
			change.After, err = json.Marshal(ch.After.raw)
			if err != nil {
				return nil, err
			}
		}
		items = append(items, change)
	}
	return items, nil
}
