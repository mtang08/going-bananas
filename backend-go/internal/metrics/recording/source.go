package recording

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
)

type Plan struct {
	UID, RevisionID uuid.UUID
	Head            int
	Kind            string
	Recipe          *string
	Intent          string
	Structure       json.RawMessage
}

func Sources(ctx context.Context, tx pgx.Tx, r *metrics.Run) (map[string]any, *Plan, error) {
	refs := map[string]any{"activity": map[string]any{"id": r.ID, "source_revision": r.SourceRevision, "source_refs": r.Refs}, "fit": r.FIT, "plan": nil, "completion_association_hash": nil}
	var a metrics.CompletionAssociation
	err := tx.QueryRow(ctx, `SELECT session_uid,activity_id,strong_workout_id,manual_session_id,match_method,modification_reason,reason_note,input_version FROM session_completions WHERE activity_id=$1`, r.ID).Scan(&a.SessionUID, &a.ActivityID, &a.StrongWorkoutID, &a.ManualSessionID, &a.MatchMethod, &a.ModificationReason, &a.ReasonNote, &a.InputVersion)
	if errors.Is(err, pgx.ErrNoRows) {
		return refs, nil, nil
	}
	if err != nil {
		return nil, nil, err
	}
	hashed, err := a.Hash()
	if err != nil {
		return nil, nil, err
	}
	refs["completion_association_hash"] = hashed
	p := Plan{UID: a.SessionUID}
	var deleted bool
	err = tx.QueryRow(ctx, `SELECT r.id,h.calendar_head_version,r.kind,r.recipe_id,r.intent,r.structure,r.deleted FROM calendar_session_revisions r JOIN app_state h ON h.id=1 AND r.calendar_version_number<=h.calendar_head_version WHERE session_uid=$1 ORDER BY calendar_version_number DESC, revision DESC LIMIT 1`, a.SessionUID).Scan(&p.RevisionID, &p.Head, &p.Kind, &p.Recipe, &p.Intent, &p.Structure, &deleted)
	if errors.Is(err, pgx.ErrNoRows) || deleted {
		return refs, nil, nil
	}
	if err != nil {
		return nil, nil, err
	}
	val, err := metrics.JSONValue(p.Structure)
	if err != nil {
		return nil, nil, err
	}
	structureHash, err := metrics.Digest(val)
	if err != nil {
		return nil, nil, err
	}
	refs["plan"] = map[string]any{"session_uid": a.SessionUID, "revision_id": p.RevisionID, "calendar_version": p.Head, "structure_hash": structureHash}
	return refs, &p, nil
}
func Steps(ctx context.Context, tx pgx.Tx, id uuid.UUID) ([]FitStep, error) {
	rows, err := tx.Query(ctx, `SELECT message_index,duration_type,coalesce(intensity,''),duration_value,target_type,target_low,target_high,repeat_from,repeat_count FROM activity_workout_steps WHERE activity_id=$1 ORDER BY message_index`, id)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (FitStep, error) {
		var s FitStep
		err := row.Scan(&s.Index, &s.Duration, &s.Intensity, &s.Value, &s.Target, &s.Low, &s.High, &s.RepeatFrom, &s.RepeatCount)
		return s, err
	})
}
