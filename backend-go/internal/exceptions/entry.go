package exceptions

import (
	"context"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"time"
)

func Detect(ctx context.Context, tx pgx.Tx, now time.Time) (map[string]any, error) {
	if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
		return nil, err
	}
	in, err := LoadInputs(ctx, tx, now)
	if err != nil {
		return nil, err
	}
	return maintain(ctx, tx, now, in.Today, Candidates(in))
}
