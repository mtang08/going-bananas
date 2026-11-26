// Package prompts maintains source-derived prompts within the caller's writer transaction.
package prompts

import (
	"context"
	_ "embed"
	"github.com/jackc/pgx/v5"
	"time"
)

//go:embed refresh.sql
var generateSQL string

type Counts struct{ Created, Expired, Answered int }

func Generate(ctx context.Context, tx pgx.Tx, now time.Time) (Counts, error) {
	var counts Counts
	err := tx.QueryRow(ctx, generateSQL, now.UTC()).Scan(&counts.Created, &counts.Expired, &counts.Answered)
	return counts, err
}
