package replay

import (
	"context"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// RefreshScope describes inputs changed in the current source transaction.
type RefreshScope struct {
	Activities    map[uuid.UUID]string
	AffectedDates []string
	RecoveryDates []string
	CoverageIDs   []uuid.UUID
}

type Refresh func(context.Context, pgx.Tx, RefreshScope) error
