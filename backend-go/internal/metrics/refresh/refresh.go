// Package refresh runs the calendar's affected metric writes on its caller-owned transaction.
package refresh

import (
	"context"
	"fmt"

	"slices"

	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/calendar"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/assessment"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/recovery"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/spacing"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/trainingwindows"
)

type RunMetrics func(context.Context, pgx.Tx, uuid.UUID, string, time.Time) error
type batch struct {
	ctx            context.Context
	tx             pgx.Tx
	now            time.Time
	zone           *time.Location
	calculate      RunMetrics
	runs, plans    map[uuid.UUID]bool
	broad          bool
	coverage, full []string
	explicit       []uuid.UUID
}

func newBatch(ctx context.Context, tx pgx.Tx, now time.Time, calculate RunMetrics) (*batch, error) {
	name, err := db.New(tx).CalendarTimezone(ctx)
	if err != nil {
		return nil, err
	}
	zone, err := time.LoadLocation(name)
	if err != nil {
		return nil, err
	}
	if err := ensureConfigs(ctx, tx); err != nil {
		return nil, err
	}
	if calculate == nil {
		calculate = Runs
	}
	return &batch{ctx: ctx, tx: tx, now: now, zone: zone, calculate: calculate, runs: map[uuid.UUID]bool{}, plans: map[uuid.UUID]bool{}}, nil
}

func (b *batch) ids(sql string, args ...any) ([]uuid.UUID, error) {
	rows, err := b.tx.Query(b.ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
}
func (b *batch) run(ids []uuid.UUID) error {
	for _, id := range ids {
		if b.runs[id] {
			continue
		}
		if err := b.calculate(b.ctx, b.tx, id, b.zone.String(), b.now); err != nil {
			return err
		}
		b.runs[id] = true
	}
	return nil
}

func (b *batch) assess(ids []uuid.UUID) error {
	linked, err := b.ids(`SELECT DISTINCT activity_id FROM session_completions WHERE session_uid=ANY($1) AND activity_id IS NOT NULL ORDER BY activity_id`, ids)
	if err != nil {
		return err
	}
	if err := b.run(linked); err != nil {
		return err
	}
	pending := []uuid.UUID{}
	for _, id := range ids {
		if !b.plans[id] {
			pending = append(pending, id)
			b.plans[id] = true
		}
	}
	return assessment.RefreshBatch(b.ctx, b.tx, pending, b.now)
}

func (b *batch) related(dates []string, since string, changed, matched []uuid.UUID) error {
	ids, err := b.ids(`SELECT a.id FROM activities a WHERE $3 OR a.id=ANY($4) OR EXISTS(SELECT FROM unnest($1::text[]) d WHERE (a.start_at AT TIME ZONE $2)::date BETWEEN d::date-2 AND d::date+30) ORDER BY a.id`, dates, b.zone.String(), b.broad, b.explicit)
	if err != nil {
		return err
	}
	if err := b.run(ids); err != nil {
		return err
	}
	nearby, err := b.ids(`WITH head AS(SELECT DISTINCT ON(session_uid) * FROM calendar_session_revisions
 WHERE calendar_version_number<=(SELECT calendar_head_version FROM app_state WHERE id=1) ORDER BY session_uid,calendar_version_number DESC,revision DESC)
 SELECT session_uid FROM head WHERE NOT deleted AND($4 OR local_date>=nullif($2,'')::date OR EXISTS(SELECT FROM unnest($1::text[]) d WHERE local_date BETWEEN d::date-1 AND d::date+1))
 UNION SELECT session_uid FROM session_completions WHERE activity_id=ANY($3)`, dates, since, ids, b.broad)
	if err != nil {
		return err
	}
	if err := b.assess(append(append(nearby, changed...), matched...)); err != nil {
		return err
	}
	selection, err := trainingwindows.Select(b.ctx, b.tx, trainingwindows.Targets{Broad: b.broad, CoverageDates: b.coverage, Since: since, Dates: dates, HasActivities: len(ids) > 0}, b.now.In(b.zone).Format(time.DateOnly))
	if err != nil {
		return err
	}
	b.full = append(b.full, selection.Training...)
	for _, day := range selection.Training {
		asOf, err := time.ParseInLocation(time.DateOnly, day, b.zone)
		if err != nil {
			return err
		}
		if err := b.windows(asOf); err != nil {
			return err
		}
	}
	return spacing.RefreshDates(b.ctx, b.tx, selection.SpacingOnly, b.now)
}

func (b *batch) windows(day time.Time) error {
	first, end := day.AddDate(0, 0, -83), day.AddDate(0, 0, 1)
	ids, err := b.ids(`SELECT id FROM activities WHERE start_at>=$1 AND start_at<$2 ORDER BY start_at,id`, first, end)
	if err != nil {
		return err
	}
	if err := b.run(ids); err != nil {
		return err
	}
	if err := trainingwindows.RefreshStrength(b.ctx, b.tx, first, end, b.now); err != nil {
		return err
	}
	plans, err := b.ids(`WITH head AS(SELECT DISTINCT ON(session_uid) * FROM calendar_session_revisions WHERE calendar_version_number<=(SELECT calendar_head_version FROM app_state WHERE id=1) ORDER BY session_uid,calendar_version_number DESC,revision DESC)
 SELECT session_uid FROM head WHERE NOT deleted AND local_date BETWEEN $1::text::date AND $2::text::date UNION SELECT session_uid FROM session_completions WHERE activity_id=ANY($3)`, day.AddDate(0, 0, -13).Format(time.DateOnly), day.AddDate(0, 0, 13).Format(time.DateOnly), ids)
	if err != nil {
		return err
	}
	if err := b.assess(plans); err != nil {
		return err
	}
	for offset := -6; offset <= 0; offset++ {
		if _, err := recovery.Refresh(b.ctx, b.tx, "night:"+day.AddDate(0, 0, offset).Format(time.DateOnly), b.now); err != nil {
			return err
		}
	}
	for _, f := range []func(context.Context, pgx.Tx, time.Time, time.Time) error{trainingwindows.RefreshVolume, trainingwindows.RefreshLong, trainingwindows.RefreshRPE, trainingwindows.RefreshIntensity, trainingwindows.RefreshSymptoms, trainingwindows.RefreshAerobic} {
		if err := f(b.ctx, b.tx, day, b.now); err != nil {
			return err
		}
	}
	if _, err := recovery.Refresh(b.ctx, b.tx, "w7:"+day.Format(time.DateOnly), b.now); err != nil {
		return err
	}
	return spacing.RefreshDates(b.ctx, b.tx, []string{day.Format(time.DateOnly)}, b.now)
}

func PlanMetrics(now time.Time, runs RunMetrics) calendar.PlanMetrics {
	return func(ctx context.Context, tx pgx.Tx, scope calendar.PlanScope, matched []uuid.UUID) error {
		b, err := newBatch(ctx, tx, now, runs)
		if err != nil {
			return err
		}
		return b.related(scope.Dates, scope.Since, scope.PlanUIDs, matched)
	}
}
func CompletionMetrics(now time.Time, runs RunMetrics) calendar.RefreshMetrics {
	return func(ctx context.Context, tx pgx.Tx, targets calendar.CompletionTargets) error {
		b, err := newBatch(ctx, tx, now, runs)
		if err != nil {
			return err
		}
		ids := []uuid.UUID{targets.Change.SessionUID}
		if d := targets.Change.Displaced; d != nil {
			ids = append(ids, d.SessionUID)
		}
		if targets.ManualOnly {
			if err := b.assess(ids); err != nil {
				return err
			}
			_, err = spacing.RefreshCompletions(ctx, tx, ids, false, now)
			return err
		}
		if err := b.related(targets.Dates, "", ids, targets.Matched); err != nil {
			return err
		}
		if len(targets.Matched) > 0 {
			_, err = spacing.RefreshCompletions(ctx, tx, slices.Clone(ids), true, now)
		}
		return err
	}
}

// EnsureWindows computes the complete registered training-window set for an athlete-local date.
func EnsureWindows(ctx context.Context, tx pgx.Tx, asOf, now time.Time, runs RunMetrics) error {
	b, err := newBatch(ctx, tx, now, runs)
	if err != nil {
		return err
	}
	day := time.Date(asOf.Year(), asOf.Month(), asOf.Day(), 0, 0, 0, 0, b.zone)
	return b.windows(day)
}

// EnsureNights computes each recovery night in the inclusive local-date interval.
func EnsureNights(ctx context.Context, tx pgx.Tx, first, last, now time.Time) error {
	first = time.Date(first.Year(), first.Month(), first.Day(), 0, 0, 0, 0, time.UTC)
	last = time.Date(last.Year(), last.Month(), last.Day(), 0, 0, 0, 0, time.UTC)
	if last.Before(first) {
		return fmt.Errorf("invalid recovery date window")
	}
	for day := first; !day.After(last); day = day.AddDate(0, 0, 1) {
		if _, err := recovery.Refresh(ctx, tx, "night:"+day.Format(time.DateOnly), now); err != nil {
			return err
		}
	}
	return nil
}
