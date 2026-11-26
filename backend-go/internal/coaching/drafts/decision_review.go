package drafts

import (
	"context"
	"encoding/json"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"time"
)

func reviewEffects(ctx context.Context, tx pgx.Tx, p PreparedDecision, r *DecisionReceipt, now time.Time) error {
	var d struct {
		Operation string
		Exception json.RawMessage
		Review    *struct {
			EventID  string `json:"event_id"`
			Outcome  string
			Compared string `json:"compared_with"`
		} `json:"event_review"`
		Resolutions []struct {
			ID     uuid.UUID `json:"patch_id"`
			Status string
			Note   *string
		} `json:"patch_resolutions"`
	}
	if err := json.Unmarshal(p.parsed.Document, &d); err != nil {
		return err
	}
	closeReviewed := func(where string, args ...any) error {
		_, err := tx.Exec(ctx, "UPDATE exception_findings SET status='reviewed',closed_at=$1,close_note=NULL,reviewed_by_proposal_id=$2,version=version+1 WHERE status IN ('open','addressed') AND "+where, append([]any{now, p.ProposalID}, args...)...)
		return err
	}
	if d.Operation == "exception_review" && has(d.Exception) {
		var e struct {
			IDs []uuid.UUID `json:"finding_ids"`
		}
		if err := json.Unmarshal(d.Exception, &e); err != nil {
			return err
		}
		if r.CalendarVersion != nil {
			patch := uuid.New()
			_, err := tx.Exec(ctx, `INSERT INTO exception_patches(id,proposal_id,calendar_version_number,category,severity,ladder_level,window_start,window_end,reassess_on,monitor,return_criteria,escalate_criteria,unchanged)
    SELECT $1,$2,$3,f.category,f.severity,f.ladder_level,($4::jsonb#>>'{patch_window,start}')::date,($4::jsonb#>>'{patch_window,end}')::date,f.reassess_on,f.monitor,f.return_criteria,f.escalate_criteria,f.unchanged FROM jsonb_populate_record(NULL::exception_patches,$4::jsonb) f`, patch, p.ProposalID, r.CalendarVersion, d.Exception)
			if err != nil {
				return err
			}
			if _, err := tx.Exec(ctx, "UPDATE exception_findings SET status='addressed',patch_id=$1,version=version+1 WHERE id=ANY($2) AND status IN ('open','addressed')", patch, e.IDs); err != nil {
				return err
			}
		} else if err := closeReviewed("id=ANY($3)", e.IDs); err != nil {
			return err
		}
	}
	handled := []uuid.UUID{}
	for _, res := range d.Resolutions {
		tag, err := tx.Exec(ctx, "UPDATE exception_patches SET status=$2,resolved_at=$3,resolved_by='coach',resolution_note=$4,version=version+1 WHERE id=$1 AND status IN ('open','escalated')", res.ID, res.Status, now, res.Note)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			continue
		}
		handled = append(handled, res.ID)
		if res.Status == "resolved" {
			if _, err := tx.Exec(ctx, "UPDATE exception_findings SET status='resolved',closed_at=$1,close_note=NULL,version=version+1 WHERE patch_id=$2 AND status IN ('open','addressed')", now, res.ID); err != nil {
				return err
			}
		}
	}
	switch d.Operation {
	case "review_rolling_plan":
		return closeReviewed("status='open' AND severity<>'escalate' AND evidence_at<=$3", p.snapshot.GeneratedAt)
	case "post_event_review":
		if d.Review != nil {
			return closeReviewed("rule_code='POST_EVENT_REVIEW_DUE' AND entity_key=$3", "event:"+d.Review.EventID)
		}
	case "review_training_block":
		if err := closeReviewed("true"); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, "UPDATE exception_patches SET status='superseded',resolved_at=$1,resolved_by='coach',resolution_note=NULL,version=version+1 WHERE status IN ('open','escalated') AND NOT(id=ANY($2))", now, handled); err != nil {
			return err
		}
		b := p.rules.Benchmark
		if d.Review != nil && p.current.BlockID != nil && b != nil && b.Status == "completed" {
			_, err := tx.Exec(ctx, `INSERT INTO block_benchmarks(id,block_uid,block_version,match_method,activity_id,event_id,protocol,distance_m,local_date,result_s,outcome,compared_with,proposal_id)
    SELECT $1,v.block_uid,v.version,'auto',a.id,e.id,coalesce(v.benchmark->>'protocol',''),round(a.distance_m::double precision)::integer,$2::date,
    coalesce(CASE WHEN prior.match_method IS DISTINCT FROM 'manual' THEN e.result_s END,round(a.timer_s::double precision)::integer),$3,$4,$5
    FROM block_versions v JOIN activities a ON a.id=$6 LEFT JOIN events e ON e.id=nullif($7,'')::uuid LEFT JOIN block_benchmarks prior ON prior.block_uid=v.block_uid AND prior.block_version=v.version
    WHERE v.id=$8 ON CONFLICT(block_uid,block_version) DO UPDATE SET activity_id=excluded.activity_id,event_id=excluded.event_id,protocol=excluded.protocol,distance_m=excluded.distance_m,local_date=excluded.local_date,result_s=excluded.result_s,outcome=excluded.outcome,compared_with=excluded.compared_with,proposal_id=excluded.proposal_id`, uuid.New(), b.Day, d.Review.Outcome, d.Review.Compared, p.ProposalID, b.ActivityID, b.EventID, p.current.BlockID)
			return err
		}
	}
	return nil
}
