package calendarhttp

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

// CheckAcceptedWeek loads the current accepted calendar through the same projection
// as GET /calendar/week. The caller receives no athlete payload.
func CheckAcceptedWeek(ctx context.Context, tx pgx.Tx, now time.Time) error {
	_, err := readView(ctx, tx, viewQuery{}, true, now)
	return err
}
