package replay

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

var errMissingRemote = errors.New("fit_remote_id_missing")
var errAmbiguousRemote = errors.New("fit_remote_id_ambiguous")

type BackfillSummary struct {
	Attempted   int `json:"attempted"`
	Decoded     int `json:"decoded"`
	Unavailable int `json:"unavailable"`
	Failed      int `json:"failed"`
}

func Backfill(ctx context.Context, pool *pgxpool.Pool, root string, src FITSource, since time.Time, now func() time.Time, refresh Refresh) (BackfillSummary, error) {
	var counts BackfillSummary
	rows, err := pool.Query(ctx, `SELECT id FROM activities WHERE local_date >= $1::text::date AND sport IN ('running','trail_running','treadmill_running') AND fit_status IN ('not_fetched','decode_error') ORDER BY start_at,id`, since.Format(time.DateOnly))
	if err != nil {
		return counts, err
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
	if err != nil {
		return counts, err
	}
	for _, id := range ids {
		if err := ctx.Err(); err != nil {
			return counts, err
		}
		counts.Attempted++
		outcome, err := backfillActivity(ctx, pool, root, src, id, now().UTC(), refresh)
		if ctx.Err() != nil {
			return counts, ctx.Err()
		}
		switch {
		case err != nil:
			counts.Failed++
		case outcome == "decoded":
			counts.Decoded++
		case outcome == "unavailable":
			counts.Unavailable++
		default:
			counts.Failed++
		}
	}
	return counts, nil
}
func backfillActivity(ctx context.Context, pool *pgxpool.Pool, root string, src FITSource, id uuid.UUID, now time.Time, refresh Refresh) (string, error) {
	rows, err := pool.Query(ctx, `SELECT DISTINCT substr(s.source_identity,8) FROM source_records s JOIN activity_sources a ON a.source_record_id=s.id WHERE a.activity_id=$1 AND s.rejected_reason IS NULL AND s.source_identity LIKE 'garmin:_%'`, id)
	if err != nil {
		return "", err
	}
	remote, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return "", err
	}
	var f storedFIT
	var fetchErr error
	switch len(remote) {
	case 0:
		fetchErr = errMissingRemote
	case 1:
		var b []byte
		b, fetchErr = src.DownloadActivity(ctx, remote[0])
		if ctx.Err() != nil {
			return "", ctx.Err()
		}
		if fetchErr == nil {
			raw, err := retain(root, "fit", b)
			if err != nil {
				return "", err
			}
			f = decodeFile(raw, b)
		}
	default:
		fetchErr = errAmbiguousRemote
	}
	var status string
	err = pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
			return err
		}
		var date string
		if err := tx.QueryRow(ctx, "SELECT local_date::text FROM activities WHERE id=$1 FOR UPDATE", id).Scan(&date); err != nil {
			return err
		}
		if err := persistJobFIT(ctx, tx, id, date, f, fetchErr, now, refresh); err != nil {
			return err
		}
		return tx.QueryRow(ctx, "SELECT fit_status FROM activities WHERE id=$1", id).Scan(&status)
	})
	return status, err
}

type ReprocessSummary struct {
	Mode        string         `json:"mode"`
	Selected    int            `json:"selected"`
	Reprocessed int            `json:"reprocessed"`
	Unchanged   int            `json:"unchanged"`
	Errors      map[string]int `json:"errors"`
}

func ReprocessRange(ctx context.Context, pool *pgxpool.Pool, root string, since time.Time, id *uuid.UUID, apply bool, now time.Time, refresh Refresh) (ReprocessSummary, error) {
	summary := ReprocessSummary{Mode: "dry_run", Errors: map[string]int{}}
	if apply {
		summary.Mode = "apply"
	}
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return summary, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
		return summary, err
	}
	zone, err := db.New(tx).CalendarTimezone(ctx)
	if err != nil {
		return summary, err
	}
	rows, err := tx.Query(ctx, `SELECT a.id,a.local_date::text,array_remove(ARRAY[a.local_date::text,(a.start_at AT TIME ZONE $3)::date::text,(a.end_at AT TIME ZONE $3)::date::text],NULL) FROM activities a JOIN fit_files f ON f.activity_id=a.id WHERE a.fit_status='decoded' AND coalesce(f.decoder_version,0)<$1 AND (($2::uuid IS NULL AND a.start_at >= ($4::text::date::timestamp AT TIME ZONE $3)) OR a.id=$2) ORDER BY a.start_at,a.id`, decoderVersion, id, zone, since.Format(time.DateOnly))
	if err != nil {
		return summary, err
	}
	type candidate struct {
		ID   uuid.UUID
		Date string
		Days []string
	}
	selected, err := pgx.CollectRows(rows, pgx.RowToStructByPos[candidate])
	if err != nil {
		return summary, err
	}
	summary.Selected = len(selected)
	effects := RefreshScope{Activities: map[uuid.UUID]string{}}
	for _, item := range selected {
		outcome, err := reprocessOne(ctx, tx, root, item.ID, now)
		if err != nil {
			return summary, err
		}
		switch outcome {
		case "unchanged":
			summary.Unchanged++
		case "reprocessed":
			summary.Reprocessed++
			effects.Activities[item.ID] = item.Date
			effects.AffectedDates = append(effects.AffectedDates, item.Days...)
			var end *string
			if err := tx.QueryRow(ctx, "SELECT (end_at AT TIME ZONE $2)::date::text FROM activities WHERE id=$1", item.ID, zone).Scan(&end); err != nil {
				return summary, err
			}
			if end != nil {
				effects.AffectedDates = append(effects.AffectedDates, *end)
			}
		default:
			summary.Errors[outcome]++
		}
	}
	if !apply {
		return summary, tx.Rollback(ctx)
	}
	if len(effects.Activities) > 0 {
		if _, err = db.New(tx).BumpDataRevision(ctx); err != nil {
			return summary, err
		}
		if err = refresh(ctx, tx, effects); err != nil {
			return summary, err
		}
	}
	return summary, tx.Commit(ctx)
}
