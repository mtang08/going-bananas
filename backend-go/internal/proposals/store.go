// Package proposals reads coach proposal summaries from the calendar database.
package proposals

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

type Item struct {
	ID                  uuid.UUID
	Revision            int
	Operation           string
	Status              string
	SubmittedAt         time.Time
	DecidedAt           *time.Time
	DiscardedAt         *time.Time
	Headline            string
	BaseCalendarVersion int
	ChangeCount         int
}

type List struct {
	DataRevision int
	Items        []Item
}

type Store struct {
	pool *pgxpool.Pool
}

func New(pool *pgxpool.Pool) *Store {
	return &Store{pool: pool}
}

// List reads the revision and rows from one MVCC snapshot, including when the
// filter matches no rows. A concurrent proposal decision can change both.
func (s *Store) List(ctx context.Context, status string) (List, error) {
	var result List
	err := pgx.BeginTxFunc(ctx, s.pool, pgx.TxOptions{
		IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly,
	}, func(tx pgx.Tx) error {
		queries := db.New(tx)
		revision, err := queries.DataRevision(ctx)
		if err != nil {
			return err
		}
		rows, err := queries.ListProposals(ctx, status)
		if err != nil {
			return err
		}
		result = List{DataRevision: int(revision), Items: make([]Item, 0, len(rows))}
		for _, row := range rows {
			result.Items = append(result.Items, Item{
				ID:                  uuid.UUID(row.ID.Bytes),
				Revision:            int(row.Revision),
				Operation:           row.Operation,
				Status:              row.Status,
				Headline:            row.Headline,
				SubmittedAt:         row.SubmittedAt.Time.In(time.FixedZone("", int(row.SubmittedOffset))),
				DecidedAt:           optionalTime(row.DecidedAt, row.DecidedOffset),
				DiscardedAt:         optionalTime(row.DiscardedAt, row.DiscardedOffset),
				BaseCalendarVersion: int(row.BaseCalendarVersion),
				ChangeCount:         int(row.ChangeCount),
			})
		}
		return nil
	})
	if err != nil {
		return List{}, err
	}
	return result, nil
}

// pgx decodes binary timestamptz as an instant. PostgreSQL returns the session
// offset for each individual instant, including changes across DST.
func optionalTime(v pgtype.Timestamptz, offset int32) *time.Time {
	if !v.Valid {
		return nil
	}
	t := v.Time.In(time.FixedZone("", int(offset)))
	return &t
}
