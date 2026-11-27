// Package exceptions detects and maintains athlete-facing findings in the caller's transaction.
package exceptions

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type Evidence struct {
	Type   string         `json:"type"`
	ID     *string        `json:"id"`
	At     string         `json:"at"`
	Detail map[string]any `json:"detail"`
}

type item struct {
	at   time.Time
	wire Evidence
}

type Candidate struct {
	Code     string     `json:"rule_code"`
	Category string     `json:"category"`
	Severity string     `json:"severity"`
	Key      string     `json:"entity_key"`
	Summary  string     `json:"summary"`
	At       time.Time  `json:"evidence_at"`
	Evidence []Evidence `json:"evidence"`
}

func evidence(kind string, id *string, at time.Time, detail map[string]any) item {
	layout := "2006-01-02T15:04:05"
	if at.Nanosecond()/1000 != 0 {
		layout += ".000000"
	}
	return item{at, Evidence{kind, id, at.UTC().Format(layout + "-07:00"), detail}}
}

func candidate(code, category, severity, key string, items []item, summary string) Candidate {
	var at time.Time
	for _, v := range items {
		if v.wire.Type != "recovery_night" && v.at.After(at) {
			at = v.at
		}
	}
	slices.SortStableFunc(items, func(a, b item) int {
		if n := b.at.Compare(a.at); n != 0 {
			return n
		}
		id := func(s *string) string {
			if s == nil {
				return ""
			}
			return *s
		}
		return strings.Compare(id(b.wire.ID), id(a.wire.ID))
	})
	ev := make([]Evidence, 0, min(len(items), 8))
	for _, v := range items[:cap(ev)] {
		ev = append(ev, v.wire)
	}
	runes := []rune(summary)
	if len(runes) > 240 {
		summary = string(runes[:239]) + "…"
	}
	return Candidate{code, category, severity, key, summary, at, ev}
}

func maintain(ctx context.Context, tx pgx.Tx, now time.Time, today string, found []Candidate) (map[string]any, error) {
	ids := []uuid.UUID{}
	for _, c := range found {
		tag, err := tx.Exec(ctx, `UPDATE exception_findings SET last_seen_at=$3,evidence=$4::jsonb,summary=$5,evidence_at=$6,
			severity=CASE WHEN array_position(ARRAY['observe','caution','hold','escalate'],severity::text) <
			array_position(ARRAY['observe','caution','hold','escalate'],$7::text) THEN $7::text ELSE severity END
			WHERE rule_code=$1 AND entity_key=$2 AND status IN ('open','addressed')`, c.Code, c.Key, now, c.Evidence, c.Summary, c.At, c.Severity)
		if err != nil {
			return nil, err
		}
		if tag.RowsAffected() > 0 {
			continue
		}
		id := uuid.New()
		tag, err = tx.Exec(ctx, `INSERT INTO exception_findings(id,rule_code,rule_version,category,severity,entity_key,status,summary,evidence,evidence_at,first_seen_at,last_seen_at)
			SELECT $1::uuid,$2::text,'exceptions.v1',$3::text,$4::text,$5::text,'open',$6::text,$7::jsonb,$8::timestamptz,$9::timestamptz,$9::timestamptz
			WHERE NOT coalesce((SELECT closed_at >= $8::timestamptz FROM exception_findings WHERE rule_code=$2::text AND entity_key=$5::text
				AND status NOT IN ('open','addressed') ORDER BY closed_at DESC NULLS LAST,id DESC LIMIT 1),false)`, id, c.Code, c.Category, c.Severity, c.Key, c.Summary, c.Evidence, c.At, now)
		if err != nil {
			return nil, err
		}
		if tag.RowsAffected() > 0 {
			ids = append(ids, id)
		}
	}
	_, err := tx.Exec(ctx, `UPDATE exception_findings f SET status='expired',closed_at=$1::timestamptz,close_note=NULL,version=version+1
		WHERE status='open' AND ((severity='observe' AND last_seen_at < $1::timestamptz - interval '336 hours')
		OR (rule_code='POST_EVENT_REVIEW_DUE' AND NOT EXISTS (SELECT FROM events e WHERE `+eventEntityJoin+` AND e.event_date+7 >= $2::text::date)))`, now, today)
	if err != nil {
		return nil, err
	}
	recs, err := recommend(ctx, tx, today)
	if err != nil {
		return nil, err
	}
	return map[string]any{"new_finding_ids": ids, "review_recommended": recs}, nil
}

type recommendation struct {
	Operation string      `json:"operation"`
	Reason    string      `json:"reason"`
	IDs       []uuid.UUID `json:"finding_ids"`
	Prompt    string      `json:"prompt"`
}

const exceptionPrompt = "Use $going-bananas-coach for an exception review. Read the open findings in the app and patch only what they require."
const blockPrompt = "Use $going-bananas-coach for a block review. An exception needs a bigger review."
const benchmarkPrompt = "Use $going-bananas-coach for a block review. Review the block benchmark."

// Python's UUID reader accepts bare IDs, braces, compact hex and UUID URNs.
const eventEntityJoin = `replace(e.id::text,'-','') = lower(replace(trim(both '{}' from
    replace(replace(regexp_replace(f.entity_key,'^event:',''),'urn:',''),'uuid:','')),'-',''))`

func recommend(ctx context.Context, tx pgx.Tx, today string) ([]recommendation, error) {
	rows, err := tx.Query(ctx, `SELECT f.id,f.rule_code,f.severity,f.category,f.status,e.name,to_char(e.event_date,'YYYY-MM-DD'),
		coalesce(p.status='open' AND p.reassess_on <= $1::text::date,false)
		FROM exception_findings f LEFT JOIN events e ON `+eventEntityJoin+`
		LEFT JOIN exception_patches p ON p.id=f.patch_id
		WHERE f.status IN ('open','addressed') ORDER BY f.first_seen_at,f.id`, today)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var caution, high, completed, missed []uuid.UUID
	due := []uuid.UUID{}
	races := []recommendation{}
	reason := "A finding needs a bigger review"
	for rows.Next() {
		var id uuid.UUID
		var code, sev, category, status string
		var name, date *string
		var reassess bool
		if err := rows.Scan(&id, &code, &sev, &category, &status, &name, &date, &reassess); err != nil {
			return nil, err
		}
		if reassess {
			due = append(due, id)
		}
		if sev == "escalate" {
			high = append(high, id)
			if category == "symptoms_illness" {
				reason = "A symptom or illness finding needs a bigger review. Outside evaluation may be needed."
			}
		}
		if status != "open" {
			continue
		}
		if sev == "caution" || sev == "hold" {
			caution = append(caution, id)
		}
		switch code {
		case "POST_EVENT_REVIEW_DUE":
			if name != nil && date != nil {
				races = append(races, recommendation{"post_event_review", fmt.Sprintf("Race review due for %s on %s", *name, *date), []uuid.UUID{id}, fmt.Sprintf("Use $going-bananas-coach for a post-race review of %s on %s.", *name, *date)})
			}
		case "BLOCK_BENCHMARK_COMPLETED":
			completed = append(completed, id)
		case "BLOCK_BENCHMARK_MISSED":
			missed = append(missed, id)
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	out := []recommendation{}
	if len(caution) > 0 {
		out = append(out, recommendation{"exception_review", "Open findings at caution or hold need an exception review", caution, exceptionPrompt})
	}
	if len(high) > 0 {
		out = append(out, recommendation{"review_training_block", reason, high, blockPrompt})
	}
	out = append(out, races...)
	if len(completed) > 0 {
		out = append(out, recommendation{"review_training_block", "Block benchmark complete — review the block and recalibrate", completed, benchmarkPrompt})
	}
	if len(missed) > 0 {
		out = append(out, recommendation{"review_training_block", "Block benchmark missed — review the block to reschedule it or extend the block", missed, benchmarkPrompt})
	}
	var anyDue bool
	if err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT FROM exception_patches WHERE status='open' AND reassess_on <= $1::text::date)", today).Scan(&anyDue); err != nil {
		return nil, err
	}
	if anyDue {
		out = append(out, recommendation{"exception_review", "Patch reassessment due", due, "Use $going-bananas-coach to reassess the open exception patch."})
	}
	return out, nil
}
