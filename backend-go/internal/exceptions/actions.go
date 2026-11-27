package exceptions

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

// ActionError identifies a rejected optimistic edit.
type ActionError struct {
	Status        int
	Code, Message string
}

func (e *ActionError) Error() string { return e.Code }

func Dismiss(ctx context.Context, tx pgx.Tx, id uuid.UUID, expected int, note *string, now time.Time) (map[string]any, error) {
	if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
		return nil, err
	}
	var version int
	var status string
	err := tx.QueryRow(ctx, "SELECT version,status FROM exception_findings WHERE id=$1 FOR UPDATE", id).Scan(&version, &status)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		return nil, &ActionError{404, "finding_not_found", "Finding not found"}
	case err != nil:
		return nil, err
	case version != expected:
		return nil, &ActionError{409, "version_conflict", "Finding changed; reload before editing"}
	case status != "open":
		return nil, &ActionError{409, "finding_closed", "Finding is no longer open"}
	}
	_, err = tx.Exec(ctx, "UPDATE exception_findings SET status='dismissed',version=version+1,closed_at=$2,close_note=$3 WHERE id=$1", id, now, note)
	if err != nil {
		return nil, err
	}
	if _, err = db.New(tx).BumpDataRevision(ctx); err != nil {
		return nil, err
	}
	var data map[string]any
	err = tx.QueryRow(ctx, findingProjection+" WHERE id=$1) SELECT to_jsonb(findings) FROM findings", id).Scan(&data)
	formatInstants(data, "evidence_at", "first_seen_at", "last_seen_at")
	return data, err
}

func Resolve(ctx context.Context, tx pgx.Tx, id uuid.UUID, expected int, target string, note *string, now time.Time) (map[string]any, error) {
	if target != "resolved" && target != "escalated" {
		return nil, errors.New("invalid patch resolution")
	}
	if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
		return nil, err
	}
	var version int
	var status string
	err := tx.QueryRow(ctx, "SELECT version,status FROM exception_patches WHERE id=$1 FOR UPDATE", id).Scan(&version, &status)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		return nil, &ActionError{404, "patch_not_found", "Patch not found"}
	case err != nil:
		return nil, err
	case version != expected:
		return nil, &ActionError{409, "version_conflict", "Patch changed; reload before editing"}
	case status != "open" && (status != "escalated" || target != "resolved"):
		return nil, &ActionError{409, "patch_closed", "Patch is no longer open"}
	}
	_, err = tx.Exec(ctx, "UPDATE exception_patches SET status=$2,version=version+1,resolved_at=$3,resolved_by='athlete',resolution_note=$4 WHERE id=$1", id, target, now, note)
	if err != nil {
		return nil, err
	}
	if target == "resolved" {
		_, err = tx.Exec(ctx, "UPDATE exception_findings SET status='resolved',closed_at=$2,close_note=NULL,version=version+1 WHERE patch_id=$1 AND status IN ('open','addressed')", id, now)
		if err != nil {
			return nil, err
		}
	}
	if _, err = db.New(tx).BumpDataRevision(ctx); err != nil {
		return nil, err
	}
	var data map[string]any
	// Both terminal actions clear the open-only reassessment flag.
	err = tx.QueryRow(ctx, patchProjection+" WHERE id=$2) SELECT to_jsonb(patches) FROM patches", now.UTC().Format(time.DateOnly), id).Scan(&data)
	if err != nil {
		return nil, err
	}
	data["resolved_at"] = now.UTC().Truncate(time.Microsecond).Format(time.RFC3339Nano)
	formatInstants(data, "created_at", "resolved_at")
	return data, err
}
