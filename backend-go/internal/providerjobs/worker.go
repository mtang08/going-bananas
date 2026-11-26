package providerjobs

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

// Work queues catch-up at startup and after completed windows. Idle workers
// poll until cancellation, including while a durable retry is waiting.
func (r Runner) Work(ctx context.Context) error {
	catchup := true
	for ctx.Err() == nil {
		if catchup {
			if err := pgx.BeginTxFunc(ctx, r.Pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
				name, err := db.New(tx).CalendarTimezone(ctx)
				if err != nil {
					return err
				}
				zone, err := time.LoadLocation(name)
				if err != nil {
					return err
				}
				_, err = EnqueueCatchup(ctx, tx, r.now().In(zone), zone)
				return err
			}); err != nil {
				return err
			}
		}
		status, err := r.RunOne(ctx)
		if err != nil {
			return err
		}
		catchup = status == "complete"
		if status == "" {
			if err := r.wait(ctx, 15*time.Second); err != nil {
				return err
			}
		}
	}
	return ctx.Err()
}
