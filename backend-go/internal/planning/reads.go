// Package planning reads planning history and goals for the application.
package planning

import (
	"context"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

type Reader struct{ Pool *pgxpool.Pool }

type List[T any] struct {
	DataRevision int
	Items        []T
}

// A revision describes exactly the rows returned, even for an empty list.
func readList[T any](ctx context.Context, pool *pgxpool.Pool, read func(*db.Queries) ([]T, error)) (List[T], error) {
	var result List[T]
	err := pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly}, func(tx pgx.Tx) error {
		q := db.New(tx)
		revision, err := q.DataRevision(ctx)
		if err != nil {
			return err
		}
		result.DataRevision = int(revision)
		result.Items, err = read(q)
		return err
	})
	return result, err
}

func (r Reader) Versions(ctx context.Context, limit int32) (List[db.ListCalendarVersionsRow], error) {
	return readList(ctx, r.Pool, func(q *db.Queries) ([]db.ListCalendarVersionsRow, error) { return q.ListCalendarVersions(ctx, limit) })
}

func (r Reader) Goals(ctx context.Context) (List[db.Goal], error) {
	return readList(ctx, r.Pool, func(q *db.Queries) ([]db.Goal, error) { return q.ListGoals(ctx) })
}
