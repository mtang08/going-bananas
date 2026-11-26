package providerjobs

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
)

func (r Runner) commitPage(ctx context.Context, conn *pgxpool.Conn, j *Job, page []garmin.Record, offset int, next time.Time) (PageResult, error) {
	var result PageResult
	var saved Job
	err := pgx.BeginTxFunc(ctx, conn, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		q := db.New(tx)
		if err := q.LockGlobalWriter(ctx); err != nil {
			return err
		}
		var err error
		saved, err = scanJob(tx.QueryRow(ctx, "SELECT "+jobColumns+" FROM sync_jobs WHERE id=$1 FOR UPDATE", j.ID))
		if err != nil {
			return err
		}
		result, err = r.Importer.Apply(ctx, tx, saved, page)
		if err != nil {
			return err
		}
		if r.RefreshPage != nil {
			if err := r.RefreshPage(ctx, tx, saved, result); err != nil {
				return err
			}
		}
		for k, v := range result.Counters {
			saved.Counters[k] += v
		}
		if j.Dataset == "activities" {
			// Resolving an existing treadmill review can edit this checkpoint in the importer.
			if err := tx.QueryRow(ctx, "SELECT checkpoint FROM sync_jobs WHERE id=$1", j.ID).Scan(&saved.Checkpoint); err != nil {
				return err
			}
			saved.Checkpoint["offset"] = offset
			if len(result.Pending) > 0 {
				pending, _ := saved.Checkpoint["pending_treadmill"].(map[string]any)
				if pending == nil {
					pending = make(map[string]any)
				}
				for k, v := range result.Pending {
					pending[k] = v
				}
				saved.Checkpoint["pending_treadmill"] = pending
			}
		} else {
			saved.Checkpoint = map[string]any{"next_date": next.Format(time.DateOnly)}
		}
		saved.Checkpoint["attempts"] = 0
		if _, err := tx.Exec(ctx, `UPDATE sync_jobs SET checkpoint=$2::jsonb,counters=$3::jsonb,heartbeat_at=$4 WHERE id=$1`, j.ID, saved.Checkpoint, saved.Counters, r.now()); err != nil {
			return err
		}
		if result.Newest != nil {
			_, err = tx.Exec(ctx, `UPDATE sync_state SET newest_observation_at=greatest(newest_observation_at,$2::timestamptz) WHERE dataset=$1`, j.Dataset, result.Newest)
		}
		return err
	})
	if err == nil {
		*j = saved
	}
	return result, err
}

func (r Runner) finish(ctx context.Context, conn *pgxpool.Conn, j *Job, failure string) (string, error) {
	var status string
	err := pgx.BeginTxFunc(ctx, conn, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		q := db.New(tx)
		if err := q.LockGlobalWriter(ctx); err != nil {
			return err
		}
		current, err := scanJob(tx.QueryRow(ctx, "SELECT "+jobColumns+" FROM sync_jobs WHERE id=$1 FOR UPDATE", j.ID))
		if err != nil {
			return err
		}
		now := r.now()
		status = "complete"
		coverageStatus := "complete"
		// Successful enumeration can still leave a treadmill run awaiting review.
		reason := failure
		switch {
		case failure != "":
			status, coverageStatus = "failed", "failed"
		case current.Counters["rejected"] > 0:
			status, coverageStatus, reason = "partial", "partial", "rejected_records"
		case current.Dataset == "activities":
			if pending, ok := current.Checkpoint["pending_treadmill"].(map[string]any); ok && len(pending) > 0 {
				coverageStatus, reason = "partial", "treadmill_review_pending"
			}
		}
		jobReason := reason
		if status == "complete" {
			jobReason = ""
		}
		if _, err := tx.Exec(ctx, `UPDATE sync_jobs SET status=$2,finished_at=$3,error_code=nullif($4,'') WHERE id=$1`, j.ID, status, now, jobReason); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `UPDATE sync_state SET status=$2::text,reason=nullif($3,''),fully_enumerated=$4,
			last_success_at=CASE WHEN $2::text='complete' THEN $5 ELSE last_success_at END WHERE dataset=$1`, j.Dataset, coverageStatus, reason, failure == "", now); err != nil {
			return err
		}
		coverageID := uuid.New()
		var completed *time.Time
		if failure == "" {
			completed = &now
		}
		if _, err := tx.Exec(ctx, `INSERT INTO coverage_intervals(id,dataset,start_date,end_date,status,reason,completed_at,fully_enumerated)
			VALUES($1,$2,$3,$4,$5,nullif($6,''),$7,$8)`, coverageID, j.Dataset, j.Start, j.End, coverageStatus, reason, completed, failure == ""); err != nil {
			return err
		}
		if reason == "treadmill_review_pending" {
			if _, err := tx.Exec(ctx, `UPDATE sync_jobs SET checkpoint=checkpoint||jsonb_build_object('pending_coverage_id',$2::text) WHERE id=$1`, j.ID, coverageID.String()); err != nil {
				return err
			}
		}
		if _, err := q.BumpDataRevision(ctx); err != nil {
			return err
		}
		if r.RefreshCoverage != nil {
			return r.RefreshCoverage(ctx, tx, current, coverageID, coverageStatus)
		}
		return nil
	})
	if err != nil {
		return "", err
	}
	return status, nil
}
