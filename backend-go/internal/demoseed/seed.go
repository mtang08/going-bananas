// Package demoseed builds the synthetic dashboard workspace in one writer transaction.
package demoseed

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
)

var totalTables = []string{"gcal_events", "trip_legs", "trips", "activities", "activity_laps", "activity_streams", "activity_workout_steps", "calendar_session_revisions", "calendar_versions", "checkins_v2", "coverage_intervals", "metric_results", "prompts", "recovery_observations", "session_completions", "session_rpe", "strength_routine_slots"}

func requireEmpty(ctx context.Context, tx pgx.Tx, revision int) error {
	notEmpty := errors.New("calendar_preview_requires_empty_database")
	if revision != 0 {
		return notEmpty
	}
	rows, err := tx.Query(ctx, `SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename NOT IN ('alembic_version','app_state')`)
	if err != nil {
		return err
	}
	names, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return err
	}
	for _, name := range names {
		var present bool
		if err = tx.QueryRow(ctx, "SELECT EXISTS(SELECT FROM "+pgx.Identifier{name}.Sanitize()+")").Scan(&present); err != nil {
			return err
		}
		if present {
			return notEmpty
		}
	}
	return nil
}
func profile(ctx context.Context, tx pgx.Tx, today, now time.Time) error {
	_, err := tx.Exec(ctx, `INSERT INTO profile_versions(id,version,effective_at,timezone,cycle_anchor,anchor_confirmed,strength_days_confirmed,scheduled_strength_days,facts,preferences,unknowns)
 VALUES(gen_random_uuid(),1,$1,'America/New_York',$2,true,true,'[0,4]','{}','{"weekly_review_weekday":6}','[]')`, now, today.AddDate(0, 0, -28).Format(time.DateOnly))
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `INSERT INTO strength_routine_slots(id,label,default_weekday,lower_body_cost,typical_duration_s)
 VALUES(gen_random_uuid(),'Full body A',0,'moderate',3600),(gen_random_uuid(),'Full body B',4,'moderate',3600)`)
	return err
}
func checkin(ctx context.Context, tx pgx.Tx, today, now time.Time) error {
	var id uuid.UUID
	day := today.AddDate(0, 0, -5)
	observed := time.Date(day.Year(), day.Month(), day.Day(), 8, 0, 0, 0, day.Location())
	err := tx.QueryRow(ctx, `INSERT INTO checkins_v2(id,idempotency_key,kind,observed_at,recorded_at)
 VALUES(gen_random_uuid(),'demo-seed-checkin-t5','exception',$1,$2) RETURNING id`, observed, now).Scan(&id)
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `INSERT INTO symptom_reports(id,checkin_id,site,side,severity,timing) VALUES(gen_random_uuid(),$1,'posterior tibial tendon','left',2,'next_morning')`, id)
	return err
}

func seed(ctx context.Context, tx pgx.Tx, root string, now time.Time) error {
	if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
		return err
	}
	var head, revision int
	if err := tx.QueryRow(ctx, `SELECT calendar_head_version,data_revision FROM app_state WHERE id=1 FOR UPDATE`).Scan(&head, &revision); err != nil {
		return err
	}
	zone, err := time.LoadLocation("America/New_York")
	if err != nil {
		return err
	}
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, zone)
	if head == 0 {
		if err := requireEmpty(ctx, tx, revision); err != nil {
			return err
		}
		if err := profile(ctx, tx, today, now); err != nil {
			return err
		}
	}
	rows, err := tx.Query(ctx, `SELECT label,id FROM strength_routine_slots WHERE label IN ('Full body A','Full body B') AND version=1`)
	if err != nil {
		return err
	}
	slots := map[string]uuid.UUID{}
	for rows.Next() {
		var label string
		var id uuid.UUID
		if err := rows.Scan(&label, &id); err != nil {
			rows.Close()
			return err
		}
		slots[label] = id
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	if len(slots) != 2 {
		return errors.New("demo_strength_slots_missing")
	}
	var account uuid.UUID
	if err = tx.QueryRow(ctx, `INSERT INTO source_accounts(id,provider,account_scope) VALUES(gen_random_uuid(),'demo_fixture','synthetic-demo')
 ON CONFLICT(provider,account_scope) DO UPDATE SET provider=EXCLUDED.provider RETURNING id`).Scan(&account); err != nil {
		return err
	}
	if err = seedActivities(ctx, tx, root, account, today, now); err != nil {
		return fmt.Errorf("demo activities: %w", err)
	}
	if err = seedRecovery(ctx, tx, root, account, today, now); err != nil {
		return fmt.Errorf("demo recovery: %w", err)
	}
	if head == 0 {
		if err = checkin(ctx, tx, today, now); err != nil {
			return err
		}
		if err = seedCalendar(ctx, tx, today, now, slots); err != nil {
			return fmt.Errorf("demo calendar: %w", err)
		}
		if err = seedTravel(ctx, tx, today, now); err != nil {
			return fmt.Errorf("demo travel: %w", err)
		}
	}
	if err = refresh.Source(ctx, tx, []string{"since:" + today.AddDate(0, 0, -42).Format(time.DateOnly)}, now, refresh.Runs); err != nil {
		return fmt.Errorf("demo refresh: %w", err)
	}
	if err = refresh.EnsureWindows(ctx, tx, today, now, refresh.Runs); err != nil {
		return err
	}
	planned := uuid.NewSHA1(uuid.NameSpaceURL, []byte("going-bananas-demo:"+today.AddDate(0, 0, -6).Format(time.DateOnly)+":run:0"))
	var matched bool
	if err = tx.QueryRow(ctx, `SELECT EXISTS(SELECT FROM session_completions WHERE session_uid=$1 AND activity_id IS NOT NULL)`, planned).Scan(&matched); err != nil {
		return err
	}
	if !matched {
		return errors.New("demo_structured_match_missing")
	}
	if head == 0 {
		if _, err = db.New(tx).BumpDataRevision(ctx); err != nil {
			return err
		}
		// The initial profile and coverage history also invalidate existing recovery nights.
		err = refresh.Source(ctx, tx, []string{"timezone"}, now, refresh.Runs)
	}
	return err
}

// Seed runs against a caller-selected synthetic database and returns demo_totals after all refreshes.
func Seed(ctx context.Context, pool *pgxpool.Pool, root string, now time.Time) (map[string]int, error) {
	totals := map[string]int{}
	err := pgx.BeginFunc(ctx, pool, func(tx pgx.Tx) error {
		if err := seed(ctx, tx, root, now); err != nil {
			return err
		}
		for _, name := range totalTables {
			var count int
			if err := tx.QueryRow(ctx, "SELECT count(*) FROM "+pgx.Identifier{name}.Sanitize()).Scan(&count); err != nil {
				return err
			}
			totals[name] = count
		}
		return nil
	})
	return totals, err
}
