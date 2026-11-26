package replay

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
)

// FITRefresh updates dependent metrics inside the FIT write transaction.
type FITRefresh func(context.Context, pgx.Tx, uuid.UUID, string) error

type FITSource interface {
	DownloadActivity(context.Context, string) ([]byte, error)
}

// RunFIT downloads eligible activity files after the summary page commits.
// Each activity has its own transaction so a failed file cannot undo siblings.
func RunFIT(ctx context.Context, pool *pgxpool.Pool, root string, source FITSource, records []garmin.Record, now time.Time, refresh FITRefresh) error {
	var failures []error
	for _, r := range records {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if r["activityId"] == nil || r["ownerId"] == nil {
			continue
		}
		if err := runActivityFIT(ctx, pool, root, source, fmt.Sprint(r["activityId"]), fmt.Sprint(r["ownerId"]), now, refresh); err != nil {
			failures = append(failures, err)
		}
	}
	return errors.Join(failures...)
}

func runActivityFIT(ctx context.Context, pool *pgxpool.Pool, root string, source FITSource, remoteID, owner string, now time.Time, refresh FITRefresh) error {
	const eligible = `SELECT a.id,a.local_date::text FROM activities a JOIN source_accounts s ON s.id=a.source_account_id
		WHERE s.provider='garmin' AND s.account_scope=$1 AND a.garmin_id=$2 AND a.resolution_state='resolved'
		AND a.sport IN ('running','trail_running','treadmill_running')`
	scope := "garmin-owner:" + owner
	var id uuid.UUID
	var date string
	err := pool.QueryRow(ctx, eligible, scope, remoteID).Scan(&id, &date)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil
	}
	if err != nil {
		return err
	}
	b, fetchErr := source.DownloadActivity(ctx, remoteID)
	if ctx.Err() != nil {
		return ctx.Err()
	}
	var f storedFIT
	if fetchErr == nil {
		raw, err := retain(root, "fit", b)
		if err != nil {
			return err
		}
		f = decodeFile(raw, b)
	}
	return pgx.BeginFunc(ctx, pool, func(tx pgx.Tx) error {
		q := db.New(tx)
		if err := q.LockGlobalWriter(ctx); err != nil {
			return err
		}
		var current uuid.UUID
		err := tx.QueryRow(ctx, eligible+" FOR UPDATE OF a", scope, remoteID).Scan(&current, &date)
		if errors.Is(err, pgx.ErrNoRows) {
			return nil
		}
		if err != nil {
			return err
		}
		if current != id {
			return nil
		}
		// Python excludes attempt timestamps and transient errors from source revisions.
		const sourceState = `SELECT jsonb_build_array(a.fit_status,f.id,f.decode_error,f.raw_object_id,f.fit_sha256)::text
			FROM activities a LEFT JOIN fit_files f ON f.activity_id=a.id WHERE a.id=$1`
		var before string
		if err := tx.QueryRow(ctx, sourceState, id).Scan(&before); err != nil {
			return err
		}
		if fetchErr == nil {
			changed, failed, err := applyFIT(ctx, tx, id, f, now)
			if err == nil && changed && refresh != nil {
				return refresh(ctx, tx, id, date)
			}
			if err != nil || !failed {
				return err
			}
		} else {
			code, status := "fit_download_error", "decode_error"
			var remote *garmin.RemoteError
			if errors.As(fetchErr, &remote) && remote.StatusCode == 404 {
				code, status = "fit_http_404", "unavailable"
			}
			if _, err := tx.Exec(ctx, `UPDATE fit_files SET last_attempt_at=$2,last_error=$3,decode_error=CASE WHEN decoded_at IS NULL THEN $3 ELSE decode_error END WHERE activity_id=$1`, id, now, code); err != nil {
				return err
			}
			_, err = tx.Exec(ctx, `UPDATE activities SET fit_status=$2 WHERE id=$1 AND fit_status IS DISTINCT FROM $2
			AND NOT EXISTS(SELECT FROM fit_files WHERE activity_id=$1 AND decoded_at IS NOT NULL)`, id, status)
			if err != nil {
				return err
			}
		}
		var after string
		if err := tx.QueryRow(ctx, sourceState, id).Scan(&after); err != nil {
			return err
		}
		if after != before {
			_, err = q.BumpDataRevision(ctx)
			if err == nil && refresh != nil {
				return refresh(ctx, tx, id, date)
			}
		}
		return err
	})
}
