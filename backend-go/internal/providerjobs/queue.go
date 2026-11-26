// Package providerjobs manages Garmin jobs against the shared PostgreSQL queue.
package providerjobs

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

const workerLock int64 = 837150921

type Job struct {
	ID              uuid.UUID
	Dataset, Status string
	Start, End      time.Time
	Checkpoint      map[string]any
	Counters        map[string]int
}

// The application stores inclusive local calendar dates; offsets and DST
// transitions must never change their count.
func day(t time.Time) time.Time { y, m, d := t.Date(); return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }

const jobColumns = "id,dataset,status,start_date,end_date,checkpoint,counters"

func scanJob(row pgx.Row) (Job, error) {
	var j Job
	err := row.Scan(&j.ID, &j.Dataset, &j.Status, &j.Start, &j.End, &j.Checkpoint, &j.Counters)
	return j, err
}

var ErrInvalidRange = errors.New("invalid_sync_range")
var datasets = []struct {
	name string
	days int
}{{"activities", 14}, {"sleep", 7}, {"hrv", 7}, {"resting_hr", 7}}

// Enqueue returns the oldest active job for the dataset, or creates one.
// The same transaction advisory lock also serializes Python's enqueue path.
func Enqueue(ctx context.Context, tx pgx.Tx, dataset string, first, last time.Time) (Job, error) {
	first, last = day(first), day(last)
	if first.After(last) || last.After(first.AddDate(0, 0, 366)) {
		return Job{}, ErrInvalidRange
	}
	if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock($1)", workerLock+1); err != nil {
		return Job{}, err
	}
	j, err := scanJob(tx.QueryRow(ctx, "SELECT "+jobColumns+` FROM sync_jobs WHERE dataset=$1 AND status IN ('queued','running','retry_wait') ORDER BY created_at,id LIMIT 1`, dataset))
	if !errors.Is(err, pgx.ErrNoRows) {
		return j, err
	}
	return scanJob(tx.QueryRow(ctx, `INSERT INTO sync_jobs(id,dataset,status,start_date,end_date,checkpoint,counters)
		VALUES(gen_random_uuid(),$1,'queued',$2,$3,'{"offset":0}','{"seen":0,"changed":0,"rejected":0}') RETURNING `+jobColumns, dataset, first, last))
}

func latest(ctx context.Context, tx pgx.Tx, dataset string, end time.Time) (*time.Time, error) {
	var last *time.Time
	err := tx.QueryRow(ctx, `SELECT max(end_date) FROM coverage_intervals WHERE dataset=$1 AND status='complete' AND fully_enumerated AND end_date<=$2`, dataset, end).Scan(&last)
	return last, err
}

func catchupWindow(end time.Time, latest *time.Time, bootstrap int) (time.Time, time.Time) {
	start := end.AddDate(0, 0, 1-bootstrap)
	if latest != nil {
		start = day(*latest)
	}
	capEnd := start.AddDate(0, 0, 365)
	if end.After(capEnd) {
		end = capEnd
	}
	return start, end
}

func EnqueueRequested(ctx context.Context, tx pgx.Tx, start *time.Time, end time.Time) ([]Job, error) {
	end = day(end)
	var jobs []Job
	for _, d := range datasets {
		var first, last time.Time
		if start != nil {
			first, last = day(*start), end
		} else {
			coverage, err := latest(ctx, tx, d.name, end)
			if err != nil {
				return nil, err
			}
			first, last = catchupWindow(end, coverage, d.days)
		}
		j, err := Enqueue(ctx, tx, d.name, first, last)
		if err != nil {
			return nil, err
		}
		jobs = append(jobs, j)
	}
	return jobs, nil
}

func EnqueueCatchup(ctx context.Context, tx pgx.Tx, today time.Time, zone *time.Location) ([]Job, error) {
	today = day(today)
	var jobs []Job
	for _, d := range datasets {
		var attempted *time.Time
		err := tx.QueryRow(ctx, `SELECT last_attempt_at FROM sync_state WHERE dataset=$1 AND status IN ('partial','failed','retry_wait','running')`, d.name).Scan(&attempted)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return nil, err
		}
		if attempted != nil && !day(attempted.In(zone)).Before(today) {
			continue
		}
		coverage, err := latest(ctx, tx, d.name, today)
		if err != nil {
			return nil, err
		}
		if coverage != nil && day(*coverage).Equal(today) {
			continue
		}
		first, last := catchupWindow(today, coverage, d.days)
		j, err := Enqueue(ctx, tx, d.name, first, last)
		if err != nil {
			return nil, err
		}
		jobs = append(jobs, j)
	}
	return jobs, nil
}
