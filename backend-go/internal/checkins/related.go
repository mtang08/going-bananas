package checkins

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

func matchesID(a, b *uuid.UUID) bool { return a == b || a != nil && b != nil && *a == *b }

func related(ctx context.Context, tx pgx.Tx, in Input, prior *View, now time.Time) error {
	follow := in.Kind == "post_run" || in.Kind == "delayed_followup"
	if follow && in.ActivityID == nil {
		return problem("activity_required", "Follow-up check-in requires an activity", 422)
	}
	var ended, opens *time.Time
	if in.ActivityID != nil {
		var sport string
		err := tx.QueryRow(ctx, "SELECT sport,end_at FROM activities WHERE id=$1", in.ActivityID).Scan(&sport, &ended)
		if errors.Is(err, pgx.ErrNoRows) {
			return problem("activity_not_found", "Activity not found", 404)
		}
		if err != nil {
			return err
		}
		if follow && sport != "running" && sport != "treadmill_running" && sport != "trail_running" {
			return problem("activity_not_run", "Follow-up check-in requires a run", 422)
		}
	}
	if in.PromptID != nil {
		var err error
		opens, err = checkPrompt(ctx, tx, in, prior)
		if err != nil {
			return err
		}
	}
	if in.Kind != "delayed_followup" {
		return nil
	}
	if prior == nil || prior.Kind != in.Kind || !matchesID(prior.ActivityID, in.ActivityID) {
		var exists bool
		if err := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM checkins_v2 WHERE kind='delayed_followup' AND activity_id=$1)`, in.ActivityID).Scan(&exists); err != nil {
			return err
		}
		if exists {
			return problem("activity_response_exists", "A delayed response has already been recorded for this run", 409)
		}
	}
	if prior != nil && prior.Kind == in.Kind && matchesID(prior.ActivityID, in.ActivityID) && matchesID(prior.PromptID, in.PromptID) && prior.ObservedAt == wireInstant(in.ObservedAt) {
		return nil
	}
	if ended != nil {
		window := ended.Add(16 * time.Hour)
		if opens == nil || window.After(*opens) {
			opens = &window
		}
	}
	if opens == nil || now.Before(*opens) || in.ObservedAt.Before(*opens) {
		return problem("delayed_response_not_due", "Delayed feedback opens 16 hours after the recorded run ends", 422)
	}
	return nil
}

func checkPrompt(ctx context.Context, tx pgx.Tx, in Input, prior *View) (*time.Time, error) {
	var kind, status string
	var activity *uuid.UUID
	var opens *time.Time
	var hasOwner, hasRPE bool
	mismatch := problem("prompt_subject_mismatch", "Prompt does not match check-in subject", 422)
	err := tx.QueryRow(ctx, `SELECT p.kind,p.status,p.activity_id,p.opens_at,
		EXISTS(SELECT 1 FROM checkins_v2 WHERE prompt_id=p.id),
		EXISTS(SELECT 1 FROM session_rpe WHERE activity_id=$2)
		FROM prompts p WHERE p.id=$1`, in.PromptID, in.ActivityID).Scan(&kind, &status, &activity, &opens, &hasOwner, &hasRPE)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, mismatch
	}
	if err != nil {
		return nil, err
	}
	kindMatches := (kind == "rpe" && in.Kind == "post_run") || (kind == "delayed_symptom" && in.Kind == "delayed_followup")
	if !matchesID(in.ActivityID, activity) || !kindMatches {
		return nil, mismatch
	}
	owns := prior != nil && matchesID(prior.PromptID, in.PromptID)
	answeredAllowed := status == "answered" && (owns || in.Kind == "post_run" && hasRPE && !hasOwner)
	if hasOwner && !owns || status != "open" && status != "expired" && !answeredAllowed {
		return nil, mismatch
	}
	if in.Kind == "post_run" && !hasRPE && !owns {
		return nil, problem("prompt_subject_mismatch", "RPE prompt requires a recorded RPE", 422)
	}
	return opens, nil
}
