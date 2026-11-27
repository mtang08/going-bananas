package replay

import (
	"context"
	"errors"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/intervals"
)

// SaveTreadmill imports a verified pending summary, its reviewed file and the
// athlete's lap paces in the caller's locked transaction.
func SaveTreadmill(ctx context.Context, tx pgx.Tx, root, scope, remoteID string, row garmin.Record, archive []byte, paces map[int]float64, now time.Time, refresh Refresh) (uuid.UUID, error) {
	page := Page{SourceKind: "garmin_api", AccountScope: scope, Records: []ActivityRecord{{Record: row}}, FetchedAt: now}
	inputs, err := prepare(root, page)
	if err != nil {
		return uuid.Nil, err
	}
	result := Result{Activities: map[uuid.UUID]string{}}
	if err = applyRecords(ctx, tx, page, inputs, &result, true); err != nil {
		return uuid.Nil, err
	}
	var id uuid.UUID
	var start time.Time
	var day string
	err = tx.QueryRow(ctx, `SELECT a.id,a.start_at,a.local_date::text FROM activities a JOIN source_accounts s ON a.source_account_id=s.id WHERE s.account_scope=$1 AND a.garmin_id=$2 AND a.sport='treadmill_running'`, scope, remoteID).Scan(&id, &start, &day)
	if errors.Is(err, pgx.ErrNoRows) {
		return uuid.Nil, errors.New("treadmill_import_failed")
	}
	if err != nil {
		return uuid.Nil, err
	}
	if archive != nil {
		raw, err := retain(root, "fit", archive)
		if err != nil {
			return uuid.Nil, err
		}
		_, failed, err := applyFIT(ctx, tx, id, decodeFile(raw, archive), now)
		if err != nil {
			return uuid.Nil, err
		}
		if failed && len(paces) > 0 {
			return uuid.Nil, errors.New("treadmill_fit_changed")
		}
	}
	if err := saveReviewedPaces(ctx, tx, id, paces); err != nil {
		return uuid.Nil, err
	}
	if _, err = tx.Exec(ctx, `UPDATE sync_jobs SET counters=counters||jsonb_build_object('seen',coalesce((counters->>'seen')::int,0)+1,'changed',coalesce((counters->>'changed')::int,0)+1,'new_revisions',coalesce((counters->>'new_revisions')::int,0)+1) WHERE dataset='activities' AND (checkpoint->'pending_treadmill') ? $1`, remoteID); err != nil {
		return uuid.Nil, err
	}
	ids, err := resolveImportedReviews(ctx, tx, []garmin.Record{row}, now)
	if err != nil {
		return uuid.Nil, err
	}
	if _, err = tx.Exec(ctx, `UPDATE sync_state SET newest_observation_at=greatest(newest_observation_at,$1) WHERE dataset='activities'`, start); err != nil {
		return uuid.Nil, err
	}
	if _, err = db.New(tx).BumpDataRevision(ctx); err != nil {
		return uuid.Nil, err
	}
	result.Activities[id] = day
	var days []string
	err = tx.QueryRow(ctx, `SELECT array_remove(ARRAY[a.local_date::text,(a.start_at AT TIME ZONE z)::date::text,(a.end_at AT TIME ZONE z)::date::text],NULL) FROM activities a CROSS JOIN (SELECT coalesce((SELECT timezone FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York') z) zone WHERE a.id=$1`, id).Scan(&days)
	if err != nil {
		return uuid.Nil, err
	}
	return id, refresh(ctx, tx, RefreshScope{Activities: result.Activities, AffectedDates: append(result.AffectedDates, days...), CoverageIDs: ids})
}

func saveReviewedPaces(ctx context.Context, tx pgx.Tx, id uuid.UUID, paces map[int]float64) error {
	var saved map[string]any
	for i, pace := range paces {
		var stamp time.Time
		var end *time.Time
		var elapsed, timer *float64
		var ref *int
		err := tx.QueryRow(ctx, "SELECT start_at,end_at,elapsed_s,timer_s,wkt_step_index FROM activity_laps WHERE activity_id=$1 AND lap_index=$2", id, i).Scan(&stamp, &end, &elapsed, &timer, &ref)
		if err != nil {
			return err
		}
		if saved == nil {
			saved = map[string]any{}
		}
		saved[strconv.Itoa(i)] = map[string]any{"lap_identity": intervals.LapIdentity(stamp, end, elapsed, timer, ref), "pace_s_per_mile": pace}
	}
	_, err := tx.Exec(ctx, "UPDATE activities SET treadmill_interval_paces=$2 WHERE id=$1", id, saved)
	return err
}
