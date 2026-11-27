// Package preflight inspects the selected workspace before an owner-scheduled cutover.
package preflight

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/athleteprofile"
	"github.com/mtang08/going-bananas/backend-go/internal/calendarhttp"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drafts"
	"github.com/mtang08/going-bananas/backend-go/internal/weeklydigest"
	baseline "github.com/mtang08/going-bananas/backend-go/sql"
)

type Report struct {
	Ready  bool              `json:"ready"`
	Checks map[string]string `json:"checks"`
}

func Check(ctx context.Context, conn *pgx.Conn, private, kbRoot string, now time.Time) (Report, error) {
	r := Report{Checks: map[string]string{}}
	mark := func(name string, err error) error {
		if err != nil {
			r.Checks[name] = "failed"
			return errors.New(name + "_failed")
		}
		r.Checks[name] = "ok"
		return nil
	}
	err := pgx.BeginTxFunc(ctx, conn, pgx.TxOptions{AccessMode: pgx.ReadOnly, IsoLevel: pgx.RepeatableRead}, func(tx pgx.Tx) error {

		var ready bool
		err := tx.QueryRow(ctx, "SELECT count(*)=1 AND coalesce(bool_and(version_num=$1),false) FROM alembic_version", baseline.Head()).Scan(&ready)
		if err == nil && ready {
			err = tx.QueryRow(ctx, `SELECT NOT EXISTS(SELECT col FROM unnest($1::text[]) AS expected(col) EXCEPT SELECT c.relname||'.'||a.attname FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relkind IN ('r','p') AND a.attnum>0 AND NOT a.attisdropped)`, baseline.RequiredColumns()).Scan(&ready)
		}
		if err == nil && !ready {
			err = errors.New("wrong migration stamp")
		}
		if err = mark("schema", err); err != nil {
			return err
		}
		var zone string
		err = tx.QueryRow(ctx, "SELECT coalesce((SELECT timezone FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York') FROM app_state WHERE id=1").Scan(&zone)
		if err != nil {
			return mark("profile", err)
		}
		loc, err := time.LoadLocation(zone)
		if err != nil {
			return mark("profile", err)
		}
		local := now.In(loc)
		today := local.Format(time.DateOnly)
		_, err = athleteprofile.LoadProfile(ctx, tx, today)
		if err = mark("profile", err); err != nil {
			return err
		}
		if err = mark("accepted_calendar", calendarhttp.CheckAcceptedWeek(ctx, tx, now)); err != nil {
			return err
		}
		d, err := drafts.ReadActive(ctx, tx, now, kbRoot)
		if err = mark("active_draft", err); err != nil {
			return err
		}
		if d == nil {
			r.Checks["active_draft"] = "none"
		} else if d.Status == "pending" && !d.IsCurrent {
			r.Checks["active_draft"] = "stale"
		} else {
			r.Checks["active_draft"] = d.Status
		}
		monday := local.AddDate(0, 0, -(int(local.Weekday())+6)%7)
		_, err = weeklydigest.LoadWeek(ctx, tx, monday.Format(time.DateOnly), today, now)
		if err = mark("weekly_summary", err); err != nil {
			return err
		}
		if err = mark("sync_checkpoints", checkpoints(ctx, tx)); err != nil {
			return err
		}
		if err = mark("raw_references", rawFiles(ctx, tx, private)); err != nil {
			return err
		}
		return credentials(private, r.Checks)
	})
	r.Ready = err == nil
	return r, err
}
func checkpoints(ctx context.Context, tx pgx.Tx) error {
	// A running job must first finish or be reconciled by the existing writer.
	var ok bool
	err := tx.QueryRow(ctx, `SELECT NOT EXISTS(SELECT FROM sync_jobs WHERE status='running'
 OR jsonb_typeof(checkpoint) IS DISTINCT FROM 'object' OR jsonb_typeof(counters) IS DISTINCT FROM 'object'
 OR (checkpoint ? 'offset' AND (jsonb_typeof(checkpoint->'offset')<>'number' OR checkpoint->>'offset' !~ '^[0-9]+$'))
 OR (checkpoint ? 'attempts' AND (jsonb_typeof(checkpoint->'attempts')<>'number' OR checkpoint->>'attempts' !~ '^[0-9]+$'))
 OR (checkpoint ? 'next_date' AND (jsonb_typeof(checkpoint->'next_date')<>'string' OR (checkpoint->>'next_date')::date IS NULL))
 OR (checkpoint ? 'pending_treadmill' AND jsonb_typeof(checkpoint->'pending_treadmill')<>'object')
 OR start_date>end_date) AND NOT EXISTS(SELECT FROM sync_state WHERE requested_start>requested_end)`).Scan(&ok)
	if err != nil {
		return err
	}
	if !ok {
		return errors.New("inconsistent or running sync")
	}
	return nil
}
func rawFiles(ctx context.Context, tx pgx.Tx, private string) error {
	var broken bool
	err := tx.QueryRow(ctx, `WITH refs AS (SELECT raw_object_id id FROM fit_files UNION ALL SELECT raw_object_id FROM strong_workouts UNION ALL SELECT raw_object_id FROM source_records WHERE raw_object_id IS NOT NULL)
 SELECT EXISTS(SELECT FROM refs LEFT JOIN raw_objects r USING(id) WHERE r.id IS NULL) OR EXISTS(SELECT FROM fit_files f JOIN raw_objects r ON r.id=f.raw_object_id WHERE f.zip_sha256<>r.sha256)`).Scan(&broken)
	if err != nil {
		return err
	}
	if broken {
		return errors.New("broken raw reference")
	}
	root, err := os.OpenRoot(private)
	if err != nil {
		return err
	}
	defer func() { _ = root.Close() }()
	rows, err := tx.Query(ctx, "SELECT relative_path,sha256,byte_size FROM raw_objects ORDER BY id")
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var path, digest string
		var size int64
		if err := rows.Scan(&path, &digest, &size); err != nil {
			return err
		}
		if err := verify(root, path, digest, size); err != nil {
			return err
		}
	}
	return rows.Err()
}
func verify(root *os.Root, path, digest string, size int64) error {
	base := strings.ToLower(filepath.Base(path))
	if strings.Contains(base, "token") || strings.Contains(base, "key") || base == ".env" {
		return errors.New("raw file excluded from backup")
	}
	if !fs.ValidPath(path) || !strings.HasPrefix(path, "raw/") || strings.Contains(path, "\\") {
		return errors.New("unsafe raw path")
	}
	parts := strings.Split(path, "/")
	for i := range parts {
		info, err := root.Lstat(filepath.Join(parts[:i+1]...))
		if err != nil {
			return err
		}
		if (i == len(parts)-1 && !info.Mode().IsRegular()) || info.Mode()&os.ModeSymlink != 0 {
			return errors.New("linked raw path")
		}
	}
	f, err := root.Open(path)
	if err != nil {
		return err
	}
	defer func() { _ = f.Close() }()
	info, err := f.Stat()
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() || info.Size() != size {
		return errors.New("raw size mismatch")
	}
	h := sha256.New()
	n, err := io.Copy(h, f)
	if err != nil {
		return err
	}
	if n != size || hex.EncodeToString(h.Sum(nil)) != digest {
		return errors.New("raw digest mismatch")
	}
	return nil
}

// Provider setup is optional. Report only presence/permissions and never read secret contents.
func credentials(private string, checks map[string]string) error {
	key := os.Getenv("GARMIN_KEY_FILE")
	if key == "" {
		key = filepath.Join(private, "garmin-key")
	}
	for name, path := range map[string]string{"garmin_key": key, "garmin_token": filepath.Join(private, "garmin-token.json"), "calendar_client": filepath.Join(private, "google-calendar-client.json"), "calendar_token": filepath.Join(private, "google-calendar-token.json")} {
		info, err := os.Lstat(path)
		if errors.Is(err, fs.ErrNotExist) {
			checks[name] = "absent"
			if name == "garmin_key" && (os.Getenv("GARMIN_API_KEY") != "" || os.Getenv("GARMIN_PERSONAL_API_KEY") != "") {
				checks[name] = "environment"
			}
			continue
		}
		if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
			checks[name] = "unsafe_permissions"
			return errors.New("provider_permissions")
		}
		checks[name] = "private"
	}
	return nil
}
