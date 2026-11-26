// Package drafts manages saved proposals. Calendar activation belongs to the
// athlete's decision transaction.
package drafts

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

type Error struct {
	Code    string `json:"code"`
	Message string `json:"message"`
	Status  int    `json:"status"`
}

func (e *Error) Error() string { return e.Code + ": " + e.Message }

type Store struct{ Pool *pgxpool.Pool }

type Change struct {
	ID         string          `json:"change_id"`
	Operation  string          `json:"op"`
	SessionUID *uuid.UUID      `json:"session_uid"`
	Before     json.RawMessage `json:"before"`
	After      json.RawMessage `json:"after"`
	Reason     string          `json:"reason"`
	Decision   string          `json:"decision"`
}

type Draft struct {
	ID                  uuid.UUID         `json:"id"`
	Revision            int               `json:"revision"`
	Status              string            `json:"status"`
	SnapshotID          uuid.UUID         `json:"snapshot_id"`
	BaseCalendarVersion int               `json:"base_calendar_version"`
	Payload             json.RawMessage   `json:"payload"`
	ValidationErrors    json.RawMessage   `json:"validation_errors"`
	Changes             map[string]Change `json:"changes"`
}

type Receipt struct {
	ID       uuid.UUID `json:"proposal_id"`
	Revision int       `json:"revision"`
	Status   string    `json:"status"`
}

// LockPlanning takes the locks used by Python's proposal commands in the same order.
func LockPlanning(ctx context.Context, tx pgx.Tx) error {
	if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
		return err
	}
	var head int
	return tx.QueryRow(ctx, "SELECT calendar_head_version FROM app_state WHERE id=1 FOR UPDATE").Scan(&head)
}

func missing(err error) error {
	if errors.Is(err, pgx.ErrNoRows) {
		return &Error{"proposal_not_found", "Proposal not found", 404}
	}
	return err
}

func loadDraft(ctx context.Context, tx pgx.Tx, id uuid.UUID, d *Draft) error {
	err := tx.QueryRow(ctx, `SELECT id,revision,status,snapshot_id,base_calendar_version,payload,
			coalesce(validation_errors,'[]'::jsonb) FROM coach_proposals WHERE id=$1`, id).Scan(
		&d.ID, &d.Revision, &d.Status, &d.SnapshotID, &d.BaseCalendarVersion, &d.Payload, &d.ValidationErrors)
	if err != nil {
		return missing(err)
	}
	rows, err := tx.Query(ctx, `SELECT change_id,op,session_uid,before,after,reason,decision
			FROM coach_proposal_changes WHERE proposal_id=$1`, id)
	if err != nil {
		return err
	}
	defer rows.Close()
	d.Changes = map[string]Change{}
	for rows.Next() {
		var c Change
		if err := rows.Scan(&c.ID, &c.Operation, &c.SessionUID, &c.Before, &c.After, &c.Reason, &c.Decision); err != nil {
			return err
		}
		d.Changes[c.ID] = c
	}
	return rows.Err()
}

func (s Store) Load(ctx context.Context, id uuid.UUID) (Draft, error) {
	var d Draft
	err := pgx.BeginTxFunc(ctx, s.Pool, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly}, func(tx pgx.Tx) error {
		return loadDraft(ctx, tx, id, &d)
	})
	if err != nil {
		return Draft{}, err
	}
	return d, nil
}

func (s Store) Discard(ctx context.Context, id uuid.UUID, expected int, now time.Time) (Receipt, error) {
	var r Receipt
	err := pgx.BeginTxFunc(ctx, s.Pool, pgx.TxOptions{IsoLevel: pgx.ReadCommitted, AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		if err := LockPlanning(ctx, tx); err != nil {
			return err
		}
		if err := tx.QueryRow(ctx, "SELECT id,revision,status FROM coach_proposals WHERE id=$1 FOR UPDATE", id).Scan(&r.ID, &r.Revision, &r.Status); err != nil {
			return missing(err)
		}
		if expected != r.Revision {
			return &Error{"proposal_revision_conflict", "Proposal revision changed. Reload before discarding.", 409}
		}
		switch r.Status {
		case "discarded":
			return nil
		case "pending", "invalid", "stale":
			return tx.QueryRow(ctx, "UPDATE coach_proposals SET status='discarded',discarded_at=$2 WHERE id=$1 RETURNING status", id, now).Scan(&r.Status)
		default:
			return &Error{"proposal_decided", "A decided proposal cannot be discarded", 409}
		}
	})
	if err != nil {
		return Receipt{}, err
	}
	return r, nil
}

// Partition verifies stable change IDs for the eventual acceptance command.
// The caller must revalidate freshness and the accepted subset in its writer transaction.
func (d Draft) Partition(accepted, rejected []string) (map[string]Change, error) {
	chosen := make(map[string]Change, len(accepted))
	seen := make(map[string]bool, len(d.Changes))
	for _, ids := range [][]string{accepted, rejected} {
		for _, id := range ids {
			if seen[id] {
				return nil, fmt.Errorf("duplicate selected change %q", id)
			}
			if _, ok := d.Changes[id]; !ok {
				return nil, fmt.Errorf("unknown selected change %q", id)
			}
			seen[id] = true
		}
	}
	if len(seen) != len(d.Changes) {
		return nil, errors.New("selection must partition all changes")
	}
	for _, id := range accepted {
		chosen[id] = d.Changes[id]
	}
	return chosen, nil
}
