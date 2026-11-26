package snapshotreads

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// ExceptionContext is the read-only detector state projected into snapshots.
type ExceptionContext struct {
	Findings        []map[string]any `json:"exception_findings"`
	Patches         []map[string]any `json:"exception_patches"`
	Recommendations []map[string]any `json:"review_recommended"`
}

func LoadExceptions(ctx context.Context, tx pgx.Tx, asOf string, now time.Time) (ExceptionContext, error) {
	var out ExceptionContext
	findings, err := contextRows(ctx, tx, `WITH last_review AS (
		SELECT max(decided_at) AS instant FROM coach_proposals WHERE status IN ('accepted','partially_accepted')
		AND operation IN ('review_rolling_plan','review_training_block'))
		SELECT id::text,rule_code,category,severity,status,entity_key,summary,evidence,evidence_at,
		first_seen_at,last_seen_at,patch_id::text,version,
		(instant IS NULL OR first_seen_at > instant) AS is_new_since_last_review
		FROM exception_findings CROSS JOIN last_review
		WHERE status IN ('open','addressed') OR first_seen_at >= $1 ORDER BY first_seen_at DESC,id`, now.Add(-14*24*time.Hour))
	if err != nil {
		return out, err
	}
	out.Findings = findings
	out.Patches, err = contextRows(ctx, tx, `SELECT id::text,proposal_id::text,calendar_version_number,category,severity,
		ladder_level,window_start::text,window_end::text,reassess_on::text,monitor,return_criteria,escalate_criteria,
		unchanged,status,resolved_at,resolved_by,resolution_note,created_at,version,
		ARRAY(SELECT DISTINCT session_uid::text FROM calendar_session_revisions r
		WHERE r.calendar_version_number=p.calendar_version_number ORDER BY 1) AS session_uids,
		(status='open' AND reassess_on <= $1::date) AS reassess_due FROM exception_patches p
		WHERE status IN ('open','escalated') OR window_end >= $1::date-13 ORDER BY created_at DESC,id`, asOf)
	if err != nil {
		return out, err
	}
	out.Recommendations, err = recommendations(ctx, tx, out)
	return out, err
}

func contextRows(ctx context.Context, tx pgx.Tx, query string, args ...any) ([]map[string]any, error) {
	rows, err := tx.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (map[string]any, error) {
		value, err := pgx.RowToMap(row)
		if err != nil {
			return nil, err
		}
		for key, v := range value {
			if ts, ok := v.(time.Time); ok {
				value[key] = feedbackInstant(ts)
			}
		}
		return value, nil
	})
}

type recommendation struct {
	op, reason, prompt string
	ids                []string
}

func (r recommendation) wire() map[string]any {
	if r.ids == nil {
		r.ids = []string{}
	}
	return map[string]any{"operation": r.op, "reason": r.reason, "finding_ids": r.ids, "prompt": r.prompt}
}

func recommendations(ctx context.Context, tx pgx.Tx, state ExceptionContext) ([]map[string]any, error) {
	const prefix = "Use $going-bananas-coach "
	caution := recommendation{op: "exception_review", reason: "Open findings at caution or hold need an exception review", prompt: prefix + "for an exception review. Read the open findings in the app and patch only what they require."}
	block := recommendation{op: "review_training_block", reason: "A finding needs a bigger review", prompt: prefix + "for a block review. An exception needs a bigger review."}
	complete := recommendation{op: "review_training_block", reason: "Block benchmark complete — review the block and recalibrate", prompt: prefix + "for a block review. Review the block benchmark."}
	missed := recommendation{op: "review_training_block", reason: "Block benchmark missed — review the block to reschedule it or extend the block", prompt: complete.prompt}
	reassess := recommendation{op: "exception_review", reason: "Patch reassessment due", prompt: prefix + "to reassess the open exception patch."}
	due := map[string]bool{}
	for _, p := range state.Patches {
		if p["reassess_due"] == true {
			due[p["id"].(string)] = true
		}
	}
	races := []map[string]any{}
	// Use the detector's oldest-first order, preserving ascending IDs on timestamp ties.
	active, err := contextRows(ctx, tx, `SELECT id::text,entity_key,rule_code,status,severity,category,patch_id::text
		FROM exception_findings WHERE status IN ('open','addressed') ORDER BY first_seen_at,id`)
	if err != nil {
		return nil, err
	}
	for _, f := range active {
		id := f["id"].(string)
		if f["severity"] == "escalate" {
			block.ids = append(block.ids, id)
			if f["category"] == "symptoms_illness" {
				block.reason = "A symptom or illness finding needs a bigger review. Outside evaluation may be needed."
			}
		}
		if patchID, ok := f["patch_id"].(string); ok && due[patchID] {
			reassess.ids = append(reassess.ids, id)
		}
		if f["status"] != "open" {
			continue
		}
		if f["severity"] == "caution" || f["severity"] == "hold" {
			caution.ids = append(caution.ids, id)
		}
		switch f["rule_code"] {
		case "BLOCK_BENCHMARK_COMPLETED":
			complete.ids = append(complete.ids, id)
		case "BLOCK_BENCHMARK_MISSED":
			missed.ids = append(missed.ids, id)
		case "POST_EVENT_REVIEW_DUE":
			eventID, err := parseEventKey(f["entity_key"].(string))
			if err != nil {
				continue
			}
			events, err := contextRows(ctx, tx, "SELECT name,event_date::text FROM events WHERE id=$1", eventID)
			if err != nil {
				return nil, err
			}
			if len(events) > 0 {
				label := fmt.Sprintf("%s on %s", events[0]["name"], events[0]["event_date"])
				races = append(races, (recommendation{"post_event_review", "Race review due for " + label, prefix + "for a post-race review of " + label + ".", []string{id}}).wire())
			}
		}
	}
	out := []map[string]any{}
	for _, r := range []recommendation{caution, block} {
		if len(r.ids) > 0 {
			out = append(out, r.wire())
		}
	}
	out = append(out, races...)
	for _, r := range []recommendation{complete, missed} {
		if len(r.ids) > 0 {
			out = append(out, r.wire())
		}
	}
	if len(due) > 0 {
		out = append(out, reassess.wire())
	}
	return out, nil
}

func parseEventKey(key string) (uuid.UUID, error) {
	const prefix = "event:"
	if len(key) >= len(prefix) && key[:len(prefix)] == prefix {
		key = key[len(prefix):]
	}
	return uuid.Parse(key)
}
