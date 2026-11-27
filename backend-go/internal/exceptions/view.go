package exceptions

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

// View projects the public active or recent findings without changing detector state.
func View(ctx context.Context, tx pgx.Tx, now time.Time, include string) (map[string]any, error) {
	if include != "active" && include != "recent" {
		return nil, errors.New("invalid exceptions include")
	}
	zone, err := db.New(tx).CalendarTimezone(ctx)
	if err != nil {
		return nil, err
	}
	loc, err := time.LoadLocation(zone)
	if err != nil {
		return nil, err
	}
	today := now.In(loc).Format(time.DateOnly)
	var findings, patches []map[string]any
	err = tx.QueryRow(ctx, findingProjection+` WHERE status IN ('open','addressed') OR ($1 AND closed_at >= $2)`+findingsOrder, include == "recent", now.Add(-28*24*time.Hour)).Scan(&findings)
	if err != nil {
		return nil, err
	}
	err = tx.QueryRow(ctx, patchProjection+` WHERE status IN ('open','escalated') OR (status='resolved' AND resolved_at >= $2)`+patchesOrder, today, now.Add(-14*24*time.Hour)).Scan(&patches)
	if err != nil {
		return nil, err
	}
	recs, err := recommend(ctx, tx, today)
	if err != nil {
		return nil, err
	}
	counts := map[string]int{"observe": 0, "caution": 0, "hold": 0, "escalate": 0}
	for _, f := range findings {
		if f["status"] == "open" {
			counts[f["severity"].(string)]++
		}
		formatInstants(f, "evidence_at", "first_seen_at", "last_seen_at")
	}
	for _, p := range patches {
		formatInstants(p, "created_at", "resolved_at")
	}
	return map[string]any{"rule_version": "exceptions.v1", "findings": findings, "patches": patches, "review_recommended": recs, "counts": counts}, nil
}

func formatInstants(row map[string]any, fields ...string) {
	for _, k := range fields {
		raw, ok := row[k].(string)
		if !ok {
			continue
		}
		at, err := time.Parse(time.RFC3339Nano, raw)
		if err != nil {
			continue
		}
		layout := "2006-01-02T15:04:05"
		if at.Nanosecond() != 0 {
			layout += ".000000"
		}
		row[k] = at.Format(layout + "-07:00")
	}
}

const findingProjection = `WITH last_review AS (
 SELECT max(decided_at) AS instant FROM coach_proposals WHERE status IN ('accepted','partially_accepted')
 AND operation IN ('review_rolling_plan','review_training_block')
 ), findings AS (
 SELECT id,rule_code,category,severity,status,entity_key,summary,evidence,evidence_at,first_seen_at,last_seen_at,patch_id,version,
 (instant IS NULL OR first_seen_at>instant) AS is_new_since_last_review FROM exception_findings CROSS JOIN last_review`
const findingsOrder = `
 ) SELECT coalesce(jsonb_agg(to_jsonb(findings) ORDER BY
 array_position(ARRAY['observe','caution','hold','escalate'],severity::text) DESC,evidence_at DESC,id),'[]') FROM findings`
const patchProjection = `WITH patches AS (
 SELECT id,proposal_id,calendar_version_number,category,severity,ladder_level,window_start,window_end,reassess_on,
 monitor,return_criteria,escalate_criteria,unchanged,status,resolved_at,resolved_by,resolution_note,created_at,version,
 ARRAY(SELECT DISTINCT session_uid FROM calendar_session_revisions r WHERE r.calendar_version_number=p.calendar_version_number ORDER BY 1) AS session_uids,
 (status='open' AND reassess_on <= $1::text::date) AS reassess_due FROM exception_patches p`
const patchesOrder = `
 ) SELECT coalesce(jsonb_agg(to_jsonb(patches) ORDER BY created_at DESC,id),'[]') FROM patches`
