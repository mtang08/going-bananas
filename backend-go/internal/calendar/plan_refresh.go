package calendar

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/matching/rematch"
	"github.com/mtang08/going-bananas/backend-go/internal/prompts"
	"slices"
	"time"
)

// PlanScope holds source dates, session IDs and the earliest changed anchor date.
// Date strings are YYYY-MM-DD in the athlete's zone. An empty scope is revision-only.
type PlanScope struct {
	PlanUIDs []uuid.UUID
	Dates    []string
	Since    string
}
type PlanMetrics func(context.Context, pgx.Tx, PlanScope, []uuid.UUID) error

func RefreshPlans(ctx context.Context, tx pgx.Tx, scope PlanScope, now time.Time, metrics PlanMetrics) error {
	if len(scope.PlanUIDs) == 0 && len(scope.Dates) == 0 && scope.Since == "" {
		return nil
	}
	if metrics == nil {
		return errors.New("plan metric refresh is required")
	}
	days, err := scopeDays(ctx, tx, scope)
	if err != nil {
		return err
	}
	scope.Dates = days
	matched, err := rematchScope(ctx, tx, days, "", now)
	if err != nil {
		return err
	}
	if err = metrics(ctx, tx, scope, matched); err != nil {
		return err
	}
	_, err = prompts.Generate(ctx, tx, now)
	return err
}

func scopeDays(ctx context.Context, tx pgx.Tx, scope PlanScope) ([]string, error) {
	ids := make([]string, len(scope.PlanUIDs))
	for i, id := range scope.PlanUIDs {
		ids[i] = id.String()
	}
	var days []string
	err := tx.QueryRow(ctx, `WITH recent AS (
   SELECT local_date FROM unnest($1::text[]) uid CROSS JOIN LATERAL
      (SELECT local_date FROM calendar_session_revisions WHERE session_uid=uid::uuid
       ORDER BY calendar_version_number DESC,revision DESC LIMIT 2) r),
   since AS (SELECT nullif($3::text,'')::date AS first),
   historical AS (
     SELECT (start_at AT TIME ZONE coalesce((SELECT timezone FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York'))::date AS day FROM activities
     UNION ALL SELECT date FROM manual_sessions UNION ALL SELECT local_date FROM strong_workouts
     UNION ALL SELECT source_date FROM recovery_observations UNION ALL SELECT local_date FROM calendar_session_revisions)
   SELECT ARRAY(SELECT DISTINCT d FROM (SELECT local_date::text AS d FROM recent UNION ALL SELECT unnest($2::text[])
      UNION ALL SELECT day::text FROM historical,since WHERE day>=first) dates ORDER BY d)`, ids, scope.Dates, scope.Since).Scan(&days)
	return days, err
}
func rematchScope(ctx context.Context, tx pgx.Tx, days []string, already string, now time.Time) ([]uuid.UUID, error) {
	zone, err := db.New(tx).CalendarTimezone(ctx)
	if err != nil {
		return nil, err
	}
	loc, err := time.LoadLocation(zone)
	if err != nil {
		return nil, err
	}
	pending := append(slices.Clone(days), now.In(loc).Format(time.DateOnly))
	pending = slices.DeleteFunc(pending, func(d string) bool { return d == already })
	return rematch.Dates(ctx, tx, pending, now)
}
