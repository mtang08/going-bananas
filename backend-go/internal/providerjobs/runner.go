package providerjobs

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
)

type Source interface {
	SearchPage(context.Context, int, int, time.Time, time.Time) ([]garmin.Record, error)
	FetchRecovery(context.Context, string, time.Time, time.Time) ([]garmin.Record, error)
}
type PageResult struct {
	Counters      map[string]int
	Newest        *time.Time
	Pending       map[string]any
	Ready         []garmin.Record
	AffectedDates []string
	Activities    map[uuid.UUID]string
}
type Importer interface {
	Apply(context.Context, pgx.Tx, Job, []garmin.Record) (PageResult, error)
}

type Runner struct {
	Pool     *pgxpool.Pool
	Source   Source
	Importer Importer
	Now      func() time.Time
	Wait     func(context.Context, time.Duration) error
	// RefreshPage consumes newly affected source identities before the checkpoint commits.
	RefreshPage func(context.Context, pgx.Tx, Job, PageResult) error
	// RefreshCoverage runs after inserting the interval and bumping the source revision.
	RefreshCoverage func(context.Context, pgx.Tx, Job, uuid.UUID, string) error
	// IngestFIT is a separate best-effort operation after an activity page commits.
	IngestFIT func(context.Context, []garmin.Record)
}

func (r Runner) now() time.Time {
	if r.Now != nil {
		return r.Now().UTC()
	}
	return time.Now().UTC()
}
func (r Runner) wait(ctx context.Context, d time.Duration) error {
	if r.Wait != nil {
		return r.Wait(ctx, d)
	}
	return sleep(ctx, d)
}

func (r Runner) claim(ctx context.Context, conn *pgxpool.Conn) (Job, error) {
	var j Job
	err := pgx.BeginFunc(ctx, conn, func(tx pgx.Tx) error {
		var err error
		now := r.now()
		// Standalone import replay uses a private dataset and checkpoint format.
		j, err = scanJob(tx.QueryRow(ctx, "SELECT "+jobColumns+` FROM sync_jobs WHERE status IN ('queued','running','retry_wait')
			AND dataset <> 'garmin_activity_replay' AND (next_attempt_at IS NULL OR next_attempt_at<=$1)
			ORDER BY created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED`, now))
		if err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `UPDATE sync_jobs SET status='running',heartbeat_at=$2 WHERE id=$1`, j.ID, now); err != nil {
			return err
		}
		j.Status = "running"
		_, err = tx.Exec(ctx, `INSERT INTO sync_state(dataset,last_attempt_at,status,requested_start,requested_end,fully_enumerated)
			VALUES($1,$2,'running',$3,$4,false) ON CONFLICT(dataset) DO UPDATE SET last_attempt_at=EXCLUDED.last_attempt_at,
			status='running',requested_start=EXCLUDED.requested_start,requested_end=EXCLUDED.requested_end`, j.Dataset, now, j.Start, j.End)
		return err
	})
	return j, err
}

// RunOne holds the Python-compatible session lock on a dedicated connection
// across fetches and transaction boundaries. An interrupted process leaves the
// last committed checkpoint available as soon as PostgreSQL releases its lock.
func (r Runner) RunOne(ctx context.Context) (string, error) {
	conn, err := r.Pool.Acquire(ctx)
	if err != nil {
		return "", err
	}
	var locked bool
	defer func() {
		if locked {
			clean, cancel := context.WithTimeout(context.WithoutCancel(ctx), 3*time.Second)
			defer cancel()
			var unlocked bool
			if err := conn.QueryRow(clean, "SELECT pg_advisory_unlock($1)", workerLock).Scan(&unlocked); err != nil || !unlocked {
				_ = conn.Hijack().Close(clean)
				return
			}
		}
		conn.Release()
	}()
	if err := conn.QueryRow(ctx, "SELECT pg_try_advisory_lock($1)", workerLock).Scan(&locked); err != nil {
		// The server might have acquired the lock before the response was lost.
		locked = true
		return "", err
	}
	if !locked {
		return "", nil
	}
	j, err := r.claim(ctx, conn)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	status, err := r.process(ctx, conn, &j)
	if err == nil {
		return status, nil
	}
	if ctx.Err() != nil {
		return "", ctx.Err()
	}
	return r.finish(ctx, conn, &j, failureCode(err))
}

func checkpointInt(j *Job, key string) (int, error) {
	switch n := j.Checkpoint[key].(type) {
	case nil:
		return 0, nil
	case int:
		return n, nil
	case float64:
		if n >= 0 && float64(int(n)) == n {
			return int(n), nil
		}
	}
	return 0, errors.New("invalid checkpoint")
}

func pageSignature(records []garmin.Record) string {
	ids := make([]string, len(records))
	for i, record := range records {
		ids[i] = fmt.Sprint(record["activityId"])
	}
	key, _ := json.Marshal(ids)
	return string(key)
}

func (r Runner) process(ctx context.Context, conn *pgxpool.Conn, j *Job) (string, error) {
	activity := j.Dataset == "activities"
	if !activity && j.Dataset != "sleep" && j.Dataset != "hrv" && j.Dataset != "resting_hr" {
		return "", errors.New("unsupported_dataset")
	}
	offset, err := checkpointInt(j, "offset")
	if err != nil {
		return "", err
	}
	cursor := j.Start
	if s, ok := j.Checkpoint["next_date"].(string); ok {
		cursor, err = time.Parse(time.DateOnly, s)
		if err != nil {
			return "", err
		}
	}
	signatures := map[string]bool{}
	for n := 0; activity || !cursor.After(j.End); n++ {
		if activity && n >= 200 {
			return "", errors.New("activity_page_limit")
		}
		last := cursor.AddDate(0, 0, 6)
		if last.After(j.End) {
			last = j.End
		}
		fetch := func() ([]garmin.Record, error) {
			if activity {
				return r.Source.SearchPage(ctx, offset, 50, j.Start, j.End)
			}
			return r.Source.FetchRecovery(ctx, j.Dataset, cursor, last)
		}
		page, deferred, err := r.fetch(ctx, conn, j, fetch)
		if err != nil {
			return "", err
		}
		if deferred {
			return "retry_wait", nil
		}
		if activity && len(page) > 0 {
			key := pageSignature(page)
			if signatures[key] {
				return "", errors.New("repeated_activity_page")
			}
			signatures[key] = true
		}
		offset += len(page)
		cursor = last.AddDate(0, 0, 1)
		result, err := r.commitPage(ctx, conn, j, page, offset, cursor)
		if err != nil {
			return "", err
		}
		if activity {
			if r.IngestFIT != nil && len(result.Ready) > 0 {
				r.IngestFIT(ctx, result.Ready)
			}
			if len(page) < 50 {
				break
			}
		}
	}
	return r.finish(ctx, conn, j, "")
}

func (r Runner) fetch(ctx context.Context, conn *pgxpool.Conn, j *Job, fn func() ([]garmin.Record, error)) ([]garmin.Record, bool, error) {
	attempt, err := checkpointInt(j, "attempts")
	if err != nil {
		return nil, false, err
	}
	for {
		page, err := fn()
		if err == nil {
			return page, false, nil
		}
		if ctx.Err() != nil {
			return nil, false, ctx.Err()
		}
		attempt++
		now := r.now()
		delay, retry := retryDelay(err, attempt, now)
		if !retry || attempt >= 4 {
			return nil, false, err
		}
		if delay > 30*time.Second {
			_, err = conn.Exec(ctx, `UPDATE sync_jobs SET status='retry_wait',next_attempt_at=$2,error_code='remote_retry',
				checkpoint=checkpoint||jsonb_build_object('attempts',$3::int) WHERE id=$1`, j.ID, now.Add(delay), attempt)
			return nil, err == nil, err
		}
		if err := r.wait(ctx, delay); err != nil {
			return nil, false, err
		}
	}
}
