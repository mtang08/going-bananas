package replay

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/fit"
)

const decoderVersion = 2

func decodeFile(raw object, b []byte) storedFIT {
	file := storedFIT{raw: raw}
	payload, err := fit.Extract(b)
	if err == nil {
		file.payloadHash = digest(payload)
		file.decoded, err = fit.Decode(payload)
	}
	if err != nil {
		var invalid *fit.DecodeError
		if errors.As(err, &invalid) {
			file.failure = invalid.Code
		} else {
			file.failure = "decode_failed"
		}
	}
	return file
}

func applyFIT(ctx context.Context, tx pgx.Tx, activity uuid.UUID, f storedFIT, now time.Time) (bool, bool, error) {
	raw, err := f.raw.persist(ctx, tx)
	if err != nil {
		return false, false, err
	}
	_, err = tx.Exec(ctx, `INSERT INTO fit_files(id,activity_id,raw_object_id,zip_sha256,message_inventory,device)
		VALUES(gen_random_uuid(),$1,$2,$3,'{}','{}') ON CONFLICT(activity_id) DO NOTHING`, activity, raw, f.raw.Hash)
	if err != nil {
		return false, false, err
	}
	return updateFIT(ctx, tx, activity, raw, f, now, false)
}

func updateFIT(ctx context.Context, tx pgx.Tx, activity, raw uuid.UUID, f storedFIT, now time.Time, force bool) (bool, bool, error) {
	var id uuid.UUID
	var start time.Time
	var priorHash *string
	var decoded bool
	err := tx.QueryRow(ctx, `SELECT a.start_at,f.id,f.fit_sha256,f.decoded_at IS NOT NULL
		FROM activities a JOIN fit_files f ON f.activity_id=a.id WHERE a.id=$1`, activity).Scan(&start, &id, &priorHash, &decoded)
	if err != nil {
		return false, false, err
	}
	if !force && decoded && priorHash != nil && f.payloadHash == *priorHash {
		_, err = tx.Exec(ctx, "UPDATE fit_files SET last_attempt_at=$2,last_error=NULL WHERE id=$1", id, now)
		return false, false, err
	}
	d := f.decoded
	if f.failure == "" {
		switch {
		case !d.Session.StartAt.Equal(start):
			f.failure = "FIT_START_MISMATCH"
		case d.Session.Sport != "running" && d.Session.Sport != "trail_running" && d.Session.Sport != "treadmill_running":
			f.failure = "fit_not_run"
		}
	}
	if f.failure != "" {
		_, err = tx.Exec(ctx, `UPDATE fit_files SET last_attempt_at=$2,last_error=$3,
			decode_error=CASE WHEN decoded_at IS NULL THEN $3 ELSE decode_error END,
			raw_object_id=CASE WHEN decoded_at IS NULL THEN $4 ELSE raw_object_id END,
			zip_sha256=CASE WHEN decoded_at IS NULL THEN $5 ELSE zip_sha256 END,
			fit_sha256=CASE WHEN decoded_at IS NULL THEN nullif($6,'') ELSE fit_sha256 END WHERE id=$1`,
			id, now, f.failure, raw, f.raw.Hash, f.payloadHash)
		if err == nil && !decoded {
			_, err = tx.Exec(ctx, "UPDATE activities SET fit_status='decode_error' WHERE id=$1", activity)
		}
		return false, true, err
	}
	if err := replaceObservations(ctx, tx, activity, d); err != nil {
		return false, false, err
	}
	s := d.Session
	var end *time.Time
	if s.ElapsedS != nil {
		t := start.Add(time.Duration(*s.ElapsedS * float64(time.Second)))
		end = &t
	}
	lineage := map[string]map[string]string{}
	for _, key := range []string{"timer_s", "end_at", "workout_rpe", "workout_feel"} {
		lineage[key] = map[string]string{"source_kind": "garmin_fit", "fit_sha256": d.FITSHA256}
	}
	_, err = tx.Exec(ctx, `UPDATE activities SET timer_s=$2,end_at=$3,workout_rpe=$4,workout_feel=$5,
		fit_status='decoded',fit_file_id=$6,field_provenance=field_provenance || $7::jsonb,canonical_revision=canonical_revision+1 WHERE id=$1`,
		activity, s.TimerS, end, s.WorkoutRPE, s.WorkoutFeel, id, lineage)
	if err != nil {
		return false, false, err
	}
	// The existing column is varchar(20). Preserve both module identity and version.
	sdk := strings.Replace(strings.TrimPrefix(d.SDKVersion, "github.com/"), " v", "@", 1)
	_, err = tx.Exec(ctx, `UPDATE fit_files SET raw_object_id=$2,zip_sha256=$3,fit_sha256=$4,profile_version=$5,sdk_version=$6,
		decoded_at=$7,decoder_version=$8,decode_error=NULL,last_attempt_at=$7,last_error=NULL,message_inventory=$9,device=$10 WHERE id=$1`,
		id, raw, f.raw.Hash, d.FITSHA256, d.ProfileVersion, sdk, now, decoderVersion, d.MessageInventory, d.Device)
	if err != nil {
		return false, false, err
	}
	if s.WorkoutRPE == nil || end == nil {
		_, err = tx.Exec(ctx, "DELETE FROM session_rpe WHERE activity_id=$1 AND source='garmin_fit'", activity)
	} else {
		_, err = tx.Exec(ctx, `INSERT INTO session_rpe(id,activity_id,rpe,source,collected_at) VALUES(gen_random_uuid(),$1,$2,'garmin_fit',$3)
			ON CONFLICT(activity_id,source) DO UPDATE SET rpe=excluded.rpe,collected_at=excluded.collected_at`, activity, s.WorkoutRPE, end)
	}
	return true, false, err
}

func replaceObservations(ctx context.Context, tx pgx.Tx, id uuid.UUID, d *fit.DecodedFit) error {
	for _, table := range []string{"activity_laps", "activity_workout_steps", "activity_streams"} {
		if _, err := tx.Exec(ctx, "DELETE FROM "+table+" WHERE activity_id=$1", id); err != nil {
			return err
		}
	}
	for _, group := range []struct {
		table   string
		records any
	}{{"activity_laps", d.Laps}, {"activity_workout_steps", d.Steps}} {
		_, err := tx.Exec(ctx, "INSERT INTO "+group.table+" SELECT (jsonb_populate_record(NULL::"+group.table+
			", item || jsonb_build_object('id',gen_random_uuid(),'activity_id',$1::uuid))).* FROM jsonb_array_elements($2::jsonb) item", id, group.records)
		if err != nil {
			return err
		}
	}
	s := d.Stream
	_, err := tx.Exec(ctx, `INSERT INTO activity_streams SELECT (jsonb_populate_record(NULL::activity_streams,$2::jsonb || jsonb_build_object('activity_id',$1::uuid))).*`, id, s)
	return err
}

// Reprocess upgrades a retained decode on the existing activity. On a missing or
// corrupt archive only the attempt metadata changes; its successful observations remain intact.
func Reprocess(ctx context.Context, pool *pgxpool.Pool, root string, activity uuid.UUID) (string, error) {
	status := "unchanged"
	err := pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
			return err
		}
		var err error
		status, err = reprocessOne(ctx, tx, root, activity, time.Now().UTC())
		if err == nil && status == "reprocessed" {
			_, err = db.New(tx).BumpDataRevision(ctx)
		}
		return err
	})
	return status, err
}

func reprocessOne(ctx context.Context, tx pgx.Tx, root string, activity uuid.UUID, now time.Time) (string, error) {
	status := "unchanged"
	var raw, id uuid.UUID
	var path, hash, zipHash string
	err := tx.QueryRow(ctx, `SELECT f.id,r.id,r.relative_path,r.sha256,f.zip_sha256 FROM fit_files f
			JOIN activities a ON a.id=f.activity_id JOIN raw_objects r ON r.id=f.raw_object_id
			WHERE a.id=$1 AND a.fit_status='decoded' AND coalesce(f.decoder_version,0)<$2`, activity, decoderVersion).Scan(&id, &raw, &path, &hash, &zipHash)
	if errors.Is(err, pgx.ErrNoRows) {
		return "unchanged", nil
	}
	if err != nil {
		return status, err
	}

	var payload []byte
	if filepath.IsLocal(path) {
		rootFS, openErr := os.OpenRoot(root)
		if openErr == nil {
			payload, err = rootFS.ReadFile(path)
			_ = rootFS.Close()
		} else {
			err = openErr
		}
	}
	switch {
	case !filepath.IsLocal(path):
		status = "fit_raw_hash_mismatch"
	case errors.Is(err, os.ErrNotExist) || errors.Is(err, syscall.ENOTDIR):
		status = "raw_missing"
	case err != nil || digest(payload) != hash || hash != zipHash:
		status = "fit_raw_hash_mismatch"
	}
	if status != "unchanged" {
		_, err = tx.Exec(ctx, `UPDATE fit_files SET last_attempt_at=$2,last_error=$3 WHERE id=$1`, id, now, status)
		return status, err
	}
	f := decodeFile(object{Hash: hash}, payload)
	changed, failed, err := updateFIT(ctx, tx, activity, raw, f, now, true)
	if changed {
		status = "reprocessed"
	} else if failed && err == nil {
		err = tx.QueryRow(ctx, "SELECT last_error FROM fit_files WHERE id=$1", id).Scan(&status)
	}
	return status, err
}
