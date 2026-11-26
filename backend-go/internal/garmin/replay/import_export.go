package replay

import (
	"bytes"
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/zipinput"
)

type observedDataset struct {
	First           string `json:"first_date"`
	Last            string `json:"last_date"`
	Count           int    `json:"count"`
	FullyEnumerated bool   `json:"fully_enumerated"`
}

func addObserved(datasets map[string]observedDataset, metric, day string) {
	o := datasets[metric]
	if o.Count == 0 || o.First > day {
		o.First = day
	}
	if o.Last < day {
		o.Last = day
	}
	o.Count++
	datasets[metric] = o
}

func exportPreflight(ctx context.Context, tx pgx.Tx, scan ExportScan, loc *time.Location, scope string, datasets map[string]observedDataset) (map[string]any, error) {
	var mixed bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS(SELECT FROM source_accounts WHERE provider='garmin' AND account_scope<>$1)`, scope).Scan(&mixed); err != nil {
		return nil, err
	}
	if mixed {
		return nil, errors.New("mixed_source_account")
	}
	ids := make([]string, len(scan.Records))
	rowsByID := map[string]map[string]any{}
	for i, r := range scan.Records {
		n, err := Normalize(r.Record, loc)
		if err != nil {
			return nil, err
		}
		ids[i] = n.ProviderID
		rowsByID[n.ProviderID] = r.Record
		addObserved(datasets, "activities", n.Fields["local_date"].(string))
	}
	rows, err := tx.Query(ctx, `SELECT a.garmin_id,a.start_at,a.distance_m,a.elapsed_s,a.moving_s,a.avg_hr_bpm,
		EXISTS(SELECT FROM source_accounts s WHERE s.provider='garmin' AND s.id<>a.source_account_id)
		FROM activities a WHERE a.garmin_id=ANY($1::text[])`, ids)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	overlap, compared, different := 0, 0, 0
	for rows.Next() {
		var id string
		var start time.Time
		var vals [4]*float64
		if err := rows.Scan(&id, &start, &vals[0], &vals[1], &vals[2], &vals[3], &mixed); err != nil {
			return nil, err
		}
		if mixed {
			return nil, errors.New("mixed_source_account")
		}
		row := rowsByID[id]
		at, _, _ := parseISO(row["startTimeGMT"].(string))
		overlap++
		compared++
		if math.Abs(start.Sub(at).Seconds()) > 1 {
			different++
		}
		for i, key := range []string{"distance", "elapsedDuration", "movingDuration", "averageHR"} {
			if n, ok := numeric(row[key]); ok && vals[i] != nil {
				compared++
				if math.Abs(n-*vals[i]) > math.Max(.05, math.Abs(*vals[i])*.001) {
					different++
				}
			}
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return map[string]any{"existing_activity_overlap": overlap, "new_activity_candidates": len(ids) - overlap, "overlap_comparable_fields": compared, "overlap_differing_fields": different}, nil
}

// archiveObject retains and verifies the original archive using bounded memory.
func archiveObject(root string, f *os.File, hash string, size int64) (object, error) {
	rel := filepath.Join("raw", "archives", hash+".zip")
	o := object{hash, rel, "application/zip", int(size)}
	target := filepath.Join(root, rel)
	dir := filepath.Dir(target)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return o, err
	}
	if err := os.Chmod(dir, 0700); err != nil {
		return o, err
	}
	if _, err := os.Stat(target); errors.Is(err, os.ErrNotExist) {
		tmp, err := os.CreateTemp(dir, "archive-*")
		if err != nil {
			return o, err
		}
		defer func() { _ = os.Remove(tmp.Name()) }()
		_, err = io.Copy(tmp, io.NewSectionReader(f, 0, size))
		if err == nil {
			err = tmp.Sync()
		}
		err = errors.Join(err, tmp.Close())
		if err != nil {
			return o, err
		}
		if err = os.Link(tmp.Name(), target); err != nil && !errors.Is(err, os.ErrExist) {
			return o, err
		}
	} else if err != nil {
		return o, err
	}
	stored, err := os.Open(target)
	if err != nil {
		return o, err
	}
	defer func() { _ = stored.Close() }()
	h := sha256.New()
	n, err := io.Copy(h, stored)
	if err != nil {
		return o, err
	}
	if n != size || fmt.Sprintf("%x", h.Sum(nil)) != hash {
		return o, errors.New("archive_copy_mismatch")
	}
	return o, nil
}

// ImportExport previews or imports supported account-export JSON. Source rows,
// observations, coverage, and the import receipt share one transaction.
func ImportExport(ctx context.Context, pool *pgxpool.Pool, root, path string, apply bool) (map[string]any, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, errors.New("invalid_export_archive")
	}
	defer func() { _ = f.Close() }()
	st, err := f.Stat()
	if err != nil || !st.Mode().IsRegular() {
		return nil, errors.New("invalid_export_archive")
	}
	reader, err := zipinput.NewReaderAt(f, st.Size())
	if err != nil {
		return nil, errors.New("invalid_export_archive")
	}
	hash := sha256.New()
	if _, err = io.Copy(hash, f); err != nil {
		return nil, errors.New("invalid_export_archive")
	}
	archiveHash := fmt.Sprintf("%x", hash.Sum(nil))
	scan, err := scanExportReader(reader, archiveHash)
	if err != nil {
		return nil, err
	}
	recovery, err := scanExportRecovery(reader, archiveHash, scan.Owner)
	if err != nil {
		return nil, err
	}
	datasets := map[string]observedDataset{}
	recoveryCounts := map[string]int{}
	for k, rows := range recovery.rows {
		recoveryCounts[k] = len(rows)
		for _, r := range rows {
			addObserved(datasets, k, r.Record["calendarDate"].(string))
		}
	}
	scope := "garmin-owner:" + scan.Owner
	opts := pgx.TxOptions{AccessMode: pgx.ReadOnly, IsoLevel: pgx.RepeatableRead}
	if apply {
		opts = pgx.TxOptions{AccessMode: pgx.ReadWrite}
	}
	var summary map[string]any
	err = pgx.BeginTxFunc(ctx, pool, opts, func(tx pgx.Tx) error {
		if apply {
			if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock($1)", int64(837150921)); err != nil {
				return err
			}
			if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
				return err
			}
		}
		zone, err := db.New(tx).CalendarTimezone(ctx)
		if err != nil {
			return err
		}
		loc, err := time.LoadLocation(zone)
		if err != nil {
			return err
		}
		summary, err = exportPreflight(ctx, tx, scan, loc, scope, datasets)
		if err != nil {
			return err
		}
		summary["status"] = "preflight_ok"
		summary["entries"] = scan.MemberCount
		summary["activities"] = len(scan.Records)
		summary["recovery"] = recoveryCounts
		summary["datasets"] = datasets
		summary["preserved_only"] = recovery.skipped
		if !apply {
			return nil
		}
		stored, err := archiveObject(root, f, archiveHash, st.Size())
		if err != nil {
			return err
		}
		if _, err = stored.persist(ctx, tx); err != nil {
			return err
		}
		page := Page{SourceKind: "garmin_export", AccountScope: scope, Records: scan.Records, FetchedAt: time.Now().UTC(), importBatch: uuid.New(), ExportMember: scan.MemberBytes}
		if _, err = tx.Exec(ctx, `INSERT INTO import_batches(id,source_kind,status,adapter_version,counters) VALUES($1,'garmin_export','running','garmin-export-v1','{}')`, page.importBatch); err != nil {
			return err
		}
		prepared, err := prepare(root, page)
		if err != nil {
			return err
		}
		result := Result{Activities: map[uuid.UUID]string{}}
		if err = applyRecords(ctx, tx, page, prepared, &result, true); err != nil {
			return err
		}
		for _, member := range recovery.members {
			var buf bytes.Buffer
			if err := readExportMember(reader, member, &buf, "invalid_export_archive"); err != nil {
				return err
			}
			obj, err := retain(root, "json", buf.Bytes())
			if err != nil {
				return err
			}
			if _, err = obj.persist(ctx, tx); err != nil {
				return err
			}
		}
		counts := map[string]map[string]int{}
		replayed := result.Counts.NewRevisions == 0
		changed := result.Counts.Changed > 0
		status := "complete"
		for reason, n := range recovery.skipped {
			if n > 0 && !strings.HasSuffix(reason, "_unsupported") {
				status = "partial"
			}
		}
		if result.Counts.Rejected > 0 {
			status = "partial"
		}
		for _, metric := range []string{"sleep", "hrv", "resting_hr"} {
			rows := recovery.rows[metric]
			if len(rows) == 0 {
				continue
			}
			res, err := importRecoveryRows(ctx, tx, root, metric, rows, page.FetchedAt, page.importBatch, "garmin_export", "garmin-export-v1")
			if err != nil {
				return err
			}
			counts[metric] = res.Counters
			replayed = replayed && res.Counters["new_revisions"] == 0
			changed = changed || res.Counters["changed"] > 0
			if res.Counters["rejected"] > 0 {
				status = "partial"
			}
		}
		for dataset, o := range datasets {
			tag, err := tx.Exec(ctx, `INSERT INTO coverage_intervals(id,dataset,start_date,end_date,observed_start,observed_end,status,completed_at,reason,fully_enumerated)
			SELECT gen_random_uuid(),$1::varchar,$2::text::date,$3::text::date,$2::text::date,$3::text::date,'partial',now(),'export_snapshot_observed',false
			WHERE NOT EXISTS(SELECT FROM coverage_intervals WHERE dataset=$1::varchar AND start_date=$2::text::date AND end_date=$3::text::date AND reason='export_snapshot_observed')`, dataset, o.First, o.Last)
			if err != nil {
				return err
			}
			changed = changed || tag.RowsAffected() > 0
		}
		if changed {
			if _, err = db.New(tx).BumpDataRevision(ctx); err != nil {
				return err
			}
		}
		activityCounts := result.Counts.providerCounts()
		summary["activity_counts"], summary["recovery_counts"], summary["replayed"], summary["status"] = activityCounts, counts, replayed, status
		_, err = tx.Exec(ctx, `UPDATE import_batches SET status=$2,finished_at=now(),counters=$3 WHERE id=$1`, page.importBatch, status, map[string]any{"activities": activityCounts, "recovery": counts, "archive_sha256": archiveHash, "datasets": datasets, "preserved_only": recovery.skipped})
		return err
	})
	if err != nil {
		return nil, err
	}
	return summary, nil
}
