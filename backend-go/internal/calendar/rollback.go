package calendar

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"maps"
	"reflect"
	"slices"
)

func lockedHead(ctx context.Context, tx pgx.Tx) (int, error) {
	if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
		return 0, err
	}
	var head int
	err := tx.QueryRow(ctx, "SELECT calendar_head_version FROM app_state WHERE id=1 FOR UPDATE").Scan(&head)
	return head, err
}
func liveFields(row revisionRow) map[string]any {
	if row.deleted {
		return nil
	}
	return row.fields
}
func Rollback(ctx context.Context, tx pgx.Tx, expected, target int, reason *string, today string, check CheckPrescription) (AppliedEdits, error) {
	out := AppliedEdits{Created: map[string]uuid.UUID{}, Preserved: []uuid.UUID{}, Stale: []uuid.UUID{}}
	head, err := lockedHead(ctx, tx)
	if err != nil {
		return out, err
	}
	if head != expected {
		return out, &Problem{"calendar_head_moved", "Calendar changed; reload before editing"}
	}
	var exists bool
	if err := tx.QueryRow(ctx, "SELECT $1::integer=0 OR EXISTS(SELECT 1 FROM calendar_versions WHERE number=$1)", target).Scan(&exists); err != nil {
		return out, err
	}
	if target < 0 || target > head || !exists {
		return out, &Problem{"calendar_version_not_found", "Calendar version not found"}
	}
	if target >= head {
		return out, &Problem{"rollback_no_change", "No earlier version to restore"}
	}
	current, edits, protected, err := inverse(ctx, tx, head, target, today)
	if err != nil {
		return out, err
	}
	out.Preserved = protected
	if len(edits) == 0 {
		return out, &Problem{"rollback_no_change", "No eligible calendar change to restore"}
	}
	if len(out.Preserved) > 0 && (reason == nil || *reason == "") {
		return out, &Problem{"rollback_reason_required", "Reason required when preserving protected sessions"}
	}
	for _, to := range edits {
		from := current[to.uid]
		if !to.deleted {
			before, err := json.Marshal(liveFields(from))
			if err != nil {
				return out, err
			}
			after, err := json.Marshal(to.fields)
			if err != nil {
				return out, err
			}
			legacy, _ := to.fields["legacy_unstructured"].(bool)
			if err := check(before, after, legacy); err != nil {
				return out, err
			}
		}
	}
	b := EditBatch{Head: head, Today: today, Kind: "rollback", Actor: "user", RestoredFrom: &target, Reason: reason}
	return appendEdits(ctx, tx, b, current, edits, out)
}

func inverse(ctx context.Context, tx pgx.Tx, head, target int, today string) (map[uuid.UUID]revisionRow, []revisionRow, []uuid.UUID, error) {
	b := EditBatch{Head: target, Kind: "rollback", Actor: "user", Today: today, RestoredFrom: &target}
	then, err := readEditHead(ctx, tx, b)
	if err != nil {
		return nil, nil, nil, err
	}
	b.Head = head
	current, err := readEditHead(ctx, tx, b)
	if err != nil {
		return nil, nil, nil, err
	}
	var edits []revisionRow
	protected := []uuid.UUID{}
	for _, uid := range slices.SortedFunc(maps.Keys(current), func(a, b uuid.UUID) int { return slices.Compare(a[:], b[:]) }) {
		from := current[uid]
		to, was := then[uid]
		if reflect.DeepEqual(liveFields(from), liveFields(to)) {
			continue
		}
		if from.protected || to.protected {
			protected = append(protected, uid)
			continue
		}
		if !was {
			to = from
			to.deleted = true
		}
		to.revision = from.revision + 1
		edits = append(edits, to)
	}
	return current, edits, protected, nil
}

type UndoPreview struct {
	TargetVersion        int         `json:"target_version"`
	Eligible             bool        `json:"eligible"`
	ProtectedSessionUIDs []uuid.UUID `json:"protected_session_uids"`
}

func PreviewUndo(ctx context.Context, tx pgx.Tx, head int, today string) (*UndoPreview, error) {
	if head == 0 {
		return nil, nil
	}
	var target int
	err := tx.QueryRow(ctx, `SELECT parent_number FROM calendar_versions WHERE number=(SELECT max(calendar_version_number) FROM calendar_session_revisions WHERE calendar_version_number <= $1) AND parent_number IS NOT NULL AND kind<>'legacy_import'`, head).Scan(&target)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	_, edits, protected, err := inverse(ctx, tx, head, target, today)
	if err != nil {
		return nil, err
	}
	if len(edits)+len(protected) == 0 {
		return nil, nil
	}
	return &UndoPreview{target, len(edits) > 0, protected}, nil
}
