package providerjobs

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/replay"
)

// GarminImporter projects provider records inside the checkpoint transaction.
type GarminImporter struct {
	PrivateDir, AccountScope string
	Now                      func() time.Time
}

func (g GarminImporter) Apply(ctx context.Context, tx pgx.Tx, job Job, records []garmin.Record) (PageResult, error) {
	at := time.Now().UTC()
	if g.Now != nil {
		at = g.Now().UTC()
	}
	out, err := replay.ApplyJobPage(ctx, tx, g.PrivateDir, job.Dataset, g.AccountScope, records, at)
	if err != nil {
		return PageResult{}, err
	}
	return PageResult{AffectedDates: out.AffectedDates, Activities: out.Activities, Counters: out.Counters, Newest: out.Newest, Pending: out.Pending, Ready: out.Ready}, nil
}
