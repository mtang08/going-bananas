package strong

import (
	"context"
	"errors"
	"path/filepath"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/rawobject"
)

const adapterVersion = "strong-csv-v1"

type Summary struct {
	Status       string   `json:"status"`
	Workouts     int      `json:"workouts"`
	SetRows      int      `json:"set_rows"`
	FirstDate    string   `json:"first_date"`
	LastDate     string   `json:"last_date"`
	New          int      `json:"new"`
	Unchanged    int      `json:"unchanged"`
	Changed      int      `json:"changed_revisions"`
	Unknowns     []string `json:"unknowns"`
	Added        *int     `json:"added,omitempty"`
	NewConflicts *int     `json:"revision_conflicts_new,omitempty"`
}

type Result struct {
	Summary  Summary              `json:"summary"`
	Affected map[uuid.UUID]string `json:"affected_workout_dates"`
}

type priorWorkout struct {
	ID                    uuid.UUID
	Identity, Hash, State string
}

func prior(ctx context.Context, tx pgx.Tx) (uuid.UUID, map[string]priorWorkout, error) {
	var account uuid.UUID
	var scope string
	err := tx.QueryRow(ctx, `SELECT id,account_scope FROM source_accounts WHERE provider='strong'
		ORDER BY (account_scope<>'local-csv') DESC LIMIT 1`).Scan(&account, &scope)
	if errors.Is(err, pgx.ErrNoRows) {
		return uuid.Nil, nil, nil
	}
	if err != nil {
		return uuid.Nil, nil, err
	}
	if scope != "local-csv" {
		return uuid.Nil, nil, Error("mixed_source_account")
	}
	rows, err := tx.Query(ctx, `SELECT id,source_identity,payload_hash,resolution_state FROM strong_workouts WHERE source_account_id=$1`, account)
	if err != nil {
		return uuid.Nil, nil, err
	}
	records, err := pgx.CollectRows(rows, pgx.RowToStructByPos[priorWorkout])
	if err != nil {
		return uuid.Nil, nil, err
	}
	lookup := make(map[string]priorWorkout, len(records))
	for _, record := range records {
		lookup[record.Identity] = record
	}
	return account, lookup, nil
}

func summarize(workouts []Workout, existing map[string]priorWorkout) Summary {
	s := Summary{Status: "preflight_ok", Workouts: len(workouts), FirstDate: workouts[0].LocalDate, LastDate: workouts[len(workouts)-1].LocalDate,
		Unknowns: []string{"source_timezone", "weight_unit", "dumbbell_weight_convention_change_date"}}
	for _, w := range workouts {
		old, ok := existing[w.SourceIdentity]
		switch {
		case !ok:
			s.New++
		case old.Hash == w.PayloadHash:
			s.Unchanged++
		default:
			s.Changed++
		}
		s.SetRows += w.RowCount
	}
	return s
}

// Import reads and validates a complete file before opening its transaction.
// Preview only reads the current inventory; apply recomputes it under the same
// locks as Python and preserves rows with manual associations on source changes.
func Import(ctx context.Context, pool *pgxpool.Pool, root, path string, apply bool) (Result, error) {
	scan, err := ScanFile(path)
	if err != nil {
		return Result{}, err
	}
	options := pgx.TxOptions{AccessMode: pgx.ReadOnly, IsoLevel: pgx.RepeatableRead}
	if apply {
		options = pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}
	}
	result := Result{Affected: map[uuid.UUID]string{}}
	err = pgx.BeginTxFunc(ctx, pool, options, func(tx pgx.Tx) error {
		if apply {
			if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock(837150921)"); err != nil {
				return err
			}
			if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
				return err
			}
		}
		account, existing, err := prior(ctx, tx)
		if err != nil {
			return err
		}
		result.Summary = summarize(scan.Workouts, existing)
		if !apply {
			return nil
		}
		relative := filepath.Join("raw", "strong", scan.Digest+".csv")
		if err := rawobject.Write(root, relative, scan.bytes); err != nil {
			return Error("csv_copy_mismatch")
		}
		var raw uuid.UUID
		err = tx.QueryRow(ctx, `WITH added AS (
			INSERT INTO raw_objects(id,sha256,relative_path,byte_size,media_type)
			VALUES(gen_random_uuid(),$1,$2,$3,'text/csv') ON CONFLICT(sha256) DO NOTHING RETURNING id)
			SELECT id FROM added UNION ALL SELECT id FROM raw_objects WHERE sha256=$1 LIMIT 1`, scan.Digest, relative, len(scan.bytes)).Scan(&raw)
		if err != nil {
			return err
		}
		if account == uuid.Nil {
			err = tx.QueryRow(ctx, `INSERT INTO source_accounts(id,provider,account_scope) VALUES(gen_random_uuid(),'strong','local-csv') RETURNING id`).Scan(&account)
			if err != nil {
				return err
			}
		}
		batch := uuid.New()
		_, err = tx.Exec(ctx, `INSERT INTO import_batches(id,source_kind,adapter_version,status,counters) VALUES($1,'strong_csv',$2,'running','{}')`, batch, adapterVersion)
		if err != nil {
			return err
		}
		added, conflicts := 0, 0
		for _, w := range scan.Workouts {
			record, err := addSource(ctx, tx, w, account, raw, batch)
			if err != nil {
				return err
			}
			old, ok := existing[w.SourceIdentity]
			switch {
			case !ok:
				id, err := insertWorkout(ctx, tx, w, account, raw, record)
				if err != nil {
					return err
				}
				result.Affected[id] = w.LocalDate
				added++
			case old.Hash != w.PayloadHash && old.State != "revision_conflict":
				if _, err := tx.Exec(ctx, "UPDATE strong_workouts SET resolution_state='revision_conflict' WHERE id=$1", old.ID); err != nil {
					return err
				}
				result.Affected[old.ID] = w.LocalDate
				conflicts++
			}
		}
		if added+conflicts > 0 {
			if _, err := db.New(tx).BumpDataRevision(ctx); err != nil {
				return err
			}
		}
		s := &result.Summary
		s.Status = "complete"
		if s.Changed > 0 {
			s.Status = "partial"
		}
		s.Added = &added
		s.NewConflicts = &conflicts
		counters := map[string]any{"workouts": s.Workouts, "set_rows": s.SetRows, "new": added, "unchanged": s.Unchanged,
			"changed_revisions": s.Changed, "revision_conflicts_new": conflicts, "csv_sha256": scan.Digest}
		_, err = tx.Exec(ctx, "UPDATE import_batches SET status=$2,finished_at=now(),counters=$3 WHERE id=$1", batch, s.Status, counters)
		return err
	})
	if err != nil {
		return Result{}, err
	}
	return result, nil
}

func addSource(ctx context.Context, tx pgx.Tx, w Workout, account, raw, batch uuid.UUID) (uuid.UUID, error) {
	fields := map[string]any{"local_start": w.LocalStart, "row_count": w.RowCount, "timestamp_semantics": "source_local_timezone_unknown", "weight_unit": "unknown"}
	var id uuid.UUID
	err := tx.QueryRow(ctx, `WITH added AS (
		INSERT INTO source_records(id,source_account_id,import_batch_id,raw_object_id,source_identity,payload_hash,
			fetched_at,parser_version,source_kind,fields)
		VALUES(gen_random_uuid(),$1,$2,$3,$4,$5,now(),$6,'strong_csv',$7)
		ON CONFLICT(source_account_id,source_identity,payload_hash) DO NOTHING RETURNING id)
		SELECT id FROM added UNION ALL SELECT id FROM source_records WHERE source_account_id=$1 AND source_identity=$4 AND payload_hash=$5 LIMIT 1`,
		account, batch, raw, w.SourceIdentity, w.PayloadHash, adapterVersion, fields).Scan(&id)
	return id, err
}

func insertWorkout(ctx context.Context, tx pgx.Tx, w Workout, account, raw, source uuid.UUID) (uuid.UUID, error) {
	id := uuid.New()
	_, err := tx.Exec(ctx, `INSERT INTO strong_workouts(id,source_account_id,source_identity,source_record_id,raw_object_id,payload_hash,
	local_date,local_start,workout_name,duration_s,sets,row_count) VALUES($1,$2,$3,$4,$5,$6,$7::text::date,$8,$9,$10,$11,$12)`,
		id, account, w.SourceIdentity, source, raw, w.PayloadHash, w.LocalDate, w.LocalStart, w.WorkoutName, w.DurationS, w.Sets, w.RowCount)
	return id, err
}
