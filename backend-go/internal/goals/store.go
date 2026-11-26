// Package goals applies optimistic, versioned edits to an athlete's planning goals.
package goals

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

var (
	ErrNotFound        = errors.New("goal not found")
	ErrVersionConflict = errors.New("goal version conflict")
	ErrNullField       = errors.New("goal fields cannot be null")
)

type Patch struct {
	ExpectedVersion int
	Text            *string
	Horizon         *string
	Priority        *int
	Status          *string
	// HasNull distinguishes an explicit null from an omitted field. The Python
	// command checks it after the goal existence and version checks.
	HasNull bool
}

type Goal struct {
	ID       uuid.UUID
	Text     string
	Horizon  string
	Priority int
	Status   string
	Version  int
}

type Result struct {
	Goal         Goal
	DataRevision int
}

type Store struct{ pool *pgxpool.Pool }

func New(pool *pgxpool.Pool) *Store {
	return &Store{pool: pool}
}

func (s *Store) Patch(ctx context.Context, id uuid.UUID, patch Patch) (Result, error) {
	return s.write(ctx, func(q *db.Queries) (db.Goal, error) {
		key := pgtype.UUID{Bytes: id, Valid: true}
		version, err := q.GoalVersion(ctx, key)
		switch {
		case errors.Is(err, pgx.ErrNoRows):
			return db.Goal{}, ErrNotFound
		case err != nil:
			return db.Goal{}, err
		case patch.ExpectedVersion != int(version):
			return db.Goal{}, ErrVersionConflict
		case patch.HasNull:
			return db.Goal{}, ErrNullField
		}
		params := db.PatchGoalParams{
			ID: key, GoalText: optionalText(patch.Text), Horizon: optionalText(patch.Horizon),
			Status: optionalText(patch.Status),
		}
		if patch.Priority != nil {
			params.Priority = pgtype.Int8{Int64: int64(*patch.Priority), Valid: true}
		}
		return q.PatchGoal(ctx, params)
	})
}

func (s *Store) Create(ctx context.Context, text, horizon string, priority int) (Result, error) {
	return s.write(ctx, func(q *db.Queries) (db.Goal, error) {
		id, err := uuid.NewRandom()
		if err != nil {
			return db.Goal{}, err
		}
		return q.CreateGoal(ctx, db.CreateGoalParams{ID: pgtype.UUID{Bytes: id, Valid: true}, GoalText: text, Horizon: horizon, Priority: int64(priority)})
	})
}

func (s *Store) write(ctx context.Context, apply func(*db.Queries) (db.Goal, error)) (Result, error) {
	var result Result
	// READ COMMITTED gives the version check a fresh snapshot after waiting
	// for the same transaction lock as the Python goal writer.
	err := pgx.BeginTxFunc(ctx, s.pool, pgx.TxOptions{
		IsoLevel: pgx.ReadCommitted, AccessMode: pgx.ReadWrite,
	}, func(tx pgx.Tx) error {
		q := db.New(tx)
		if err := q.LockGlobalWriter(ctx); err != nil {
			return err
		}
		row, err := apply(q)
		if err != nil {
			return err
		}
		revision, err := q.BumpDataRevision(ctx)
		if err != nil {
			return err
		}
		result = Result{
			Goal: Goal{ID: uuid.UUID(row.ID.Bytes), Text: row.Text, Horizon: row.Horizon,
				Priority: int(row.Priority), Status: row.Status, Version: int(row.Version)},
			DataRevision: int(revision),
		}
		return nil
	})
	if err != nil {
		return Result{}, err
	}
	return result, nil
}

func optionalText(value *string) pgtype.Text {
	if value == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *value, Valid: true}
}
