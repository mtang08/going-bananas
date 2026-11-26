package replay

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/fit"
)

type Page struct {
	importBatch                 uuid.UUID // provided by an archive import spanning multiple datasets
	JobID                       uuid.UUID
	Index                       int
	Final                       bool
	FetchedAt                   time.Time
	SourceKind                  string
	AccountScope                string
	Records                     []ActivityRecord
	FIT                         map[string][]byte // key is Garmin's external activity ID
	ExportArchive, ExportMember []byte
}

type Counts struct {
	Seen         int `json:"seen"`
	NewRevisions int `json:"new_revisions"`
	Changed      int `json:"changed"`
	Rejected     int `json:"rejected"`
	FITDecoded   int `json:"fit_decoded"`
	FITFailed    int `json:"fit_failed"`
}

type Result struct {
	Counts        Counts               `json:"counters"`
	Status        string               `json:"status"`
	NextPage      int                  `json:"next_page"`
	Offset        int                  `json:"offset"`
	Duplicate     bool                 `json:"duplicate"`
	AffectedDates []string             `json:"affected_dates"`
	Activities    map[uuid.UUID]string `json:"affected_activity_dates"`
}

type storedInput struct {
	activity ActivityRecord
	raw      object
}
type storedFIT struct {
	raw                  object
	decoded              *fit.DecodedFit
	failure, payloadHash string
}
type prepared struct {
	inputs []storedInput
	files  []object
	fits   map[string]storedFIT
	hash   string
}

func prepare(root string, page Page) (prepared, error) {
	p := prepared{fits: map[string]storedFIT{}}
	parts := []any{page.SourceKind, page.AccountScope, page.Final}
	for _, r := range page.Records {
		raw := r.Original
		if raw == nil {
			raw = r.Record
		}
		body, err := canonicaljson.Coaching(raw)
		if err != nil {
			return p, err
		}
		o, err := retain(root, "json", body)
		if err != nil {
			return p, err
		}
		p.inputs = append(p.inputs, storedInput{r, o})
		parts = append(parts, []any{o.Hash, r.Record, r.Metadata})
	}
	for _, extra := range []struct {
		kind string
		data []byte
	}{{"export", page.ExportArchive}, {"json", page.ExportMember}} {
		if extra.data == nil {
			continue
		}
		o, err := retain(root, extra.kind, extra.data)
		if err != nil {
			return p, err
		}
		p.files = append(p.files, o)
		parts = append(parts, o.Hash)
	}
	hashes := map[string]string{}
	for id, b := range page.FIT {
		o, err := retain(root, "fit", b)
		if err != nil {
			return p, err
		}
		p.fits[id] = decodeFile(o, b)
		hashes[id] = o.Hash
	}
	body, err := canonicaljson.Coaching(append(parts, hashes))
	if err != nil {
		return p, err
	}
	p.hash = digest(body)
	return p, nil
}

type checkpoint struct {
	Pages         []string `json:"pages"`
	Offset        int      `json:"offset"`
	AffectedDates []string `json:"affected_dates"`
}

// Apply commits a fetched page, its source history and its job checkpoint together.
// A matching replay of an already committed page returns the current checkpoint.
func Apply(ctx context.Context, pool *pgxpool.Pool, root string, page Page) (Result, error) {
	var result Result
	if page.JobID == uuid.Nil || page.Index < 0 || (page.SourceKind != "garmin_api" && page.SourceKind != "garmin_export") {
		return result, errors.New("invalid_replay_page")
	}
	p, err := prepare(root, page)
	if err != nil {
		return result, err
	}
	if page.FetchedAt.IsZero() {
		page.FetchedAt = time.Now().UTC()
	}
	err = pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
			return err
		}
		_, err := tx.Exec(ctx, `INSERT INTO sync_jobs(id,dataset,status,checkpoint,counters)
			VALUES($1,'garmin_activity_replay','replaying','{}','{}') ON CONFLICT(id) DO NOTHING`, page.JobID)
		if err != nil {
			return err
		}
		var cp checkpoint
		var dataset string
		if err := tx.QueryRow(ctx, `SELECT dataset,status,checkpoint,counters FROM sync_jobs WHERE id=$1 FOR UPDATE`, page.JobID).Scan(&dataset, &result.Status, &cp, &result.Counts); err != nil {
			return err
		}
		if dataset != "garmin_activity_replay" {
			return errors.New("wrong_replay_job")
		}
		result.Activities = map[uuid.UUID]string{}
		result.AffectedDates = []string{}
		result.NextPage, result.Offset = len(cp.Pages), cp.Offset
		if page.Index < len(cp.Pages) {
			if cp.Pages[page.Index] != p.hash {
				return errors.New("replay_page_changed")
			}
			result.Duplicate = true
			return nil
		}
		if page.Index != len(cp.Pages) || result.Status != "replaying" {
			return errors.New("replay_page_out_of_order")
		}
		if err := applyRecords(ctx, tx, page, p, &result, false); err != nil {
			return err
		}
		cp.Pages = append(cp.Pages, p.hash)
		cp.AffectedDates = append(cp.AffectedDates, result.AffectedDates...)
		slices.Sort(cp.AffectedDates)
		cp.AffectedDates = slices.Compact(cp.AffectedDates)
		cp.Offset += len(page.Records)
		result.NextPage, result.Offset = len(cp.Pages), cp.Offset
		if page.Final {
			result.Status = "complete"
			if result.Counts.Rejected+result.Counts.FITFailed > 0 {
				result.Status = "partial"
			}
		}
		_, err = tx.Exec(ctx, `UPDATE sync_jobs SET checkpoint=$2,counters=$3,status=$4::varchar,heartbeat_at=now(),
			finished_at=CASE WHEN $4::varchar='replaying' THEN NULL ELSE now() END,
			error_code=CASE WHEN $4::varchar='partial' THEN 'rejected_records' END WHERE id=$1`,
			page.JobID, cp, result.Counts, result.Status)
		return err
	})
	if err != nil {
		return Result{}, err
	}
	return result, nil
}

func accountID(ctx context.Context, tx pgx.Tx, scope string) (uuid.UUID, error) {
	var id uuid.UUID
	var prior string
	err := tx.QueryRow(ctx, "SELECT id,account_scope FROM source_accounts WHERE provider='garmin' ORDER BY (account_scope<>$1) DESC LIMIT 1", scope).Scan(&id, &prior)
	if errors.Is(err, pgx.ErrNoRows) {
		err = tx.QueryRow(ctx, "INSERT INTO source_accounts(id,provider,account_scope) VALUES(gen_random_uuid(),'garmin',$1) RETURNING id", scope).Scan(&id)
	} else if err == nil && prior != scope {
		return id, errors.New("mixed_source_account")
	}
	return id, err
}

func scopeFor(page Page) (string, error) {
	scope := page.AccountScope
	if page.SourceKind == "garmin_api" {
		for _, r := range page.Records {
			owner := r.Record["ownerId"]
			if owner == nil {
				return "", errors.New("missing_or_mixed_garmin_owner")
			}
			next := "garmin-owner:" + fmt.Sprint(owner)
			if scope == "" || scope == "auto" {
				scope = next
			}
			if scope != next {
				return "", errors.New("mixed_source_account")
			}
		}
	}
	if scope == "" || scope == "auto" || len(scope) > 256 {
		return "", errors.New("invalid_account_scope")
	}
	return scope, nil
}

func applyRecords(ctx context.Context, tx pgx.Tx, page Page, p prepared, r *Result, summaryOnly bool) error {
	for _, o := range p.files {
		if _, err := o.persist(ctx, tx); err != nil {
			return err
		}
	}
	var zone string
	err := tx.QueryRow(ctx, `SELECT coalesce((SELECT timezone FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York')`).Scan(&zone)
	if err != nil {
		return err
	}
	loc, err := time.LoadLocation(zone)
	if err != nil {
		return err
	}
	var owner uuid.UUID
	if len(p.inputs) > 0 || len(p.fits) > 0 {
		scope, err := scopeFor(page)
		if err != nil {
			return err
		}
		owner, err = accountID(ctx, tx, scope)
		if err != nil {
			return err
		}
	}
	version := "garmin-personal-v1"
	if page.SourceKind == "garmin_export" {
		version = "garmin-export-v1"
	}
	batch := page.importBatch
	if batch == uuid.Nil {
		batch = uuid.New()
		_, err = tx.Exec(ctx, `INSERT INTO import_batches(id,source_kind,status,adapter_version,counters) VALUES($1,$2,'running',$3,'{}')`, batch, page.SourceKind, version)
		if err != nil {
			return err
		}
	}
	counts := Counts{}
	for _, item := range p.inputs {
		counts.Seen++
		normalized, parseErr := Normalize(item.activity.Record, loc)
		fields := normalized.Fields
		if fields == nil {
			fields = map[string]any{}
		}
		var rejected *string
		if parseErr != nil {
			message := parseErr.Error()
			rejected = &message
			counts.Rejected++
		}
		if metadata := item.activity.Metadata; metadata != nil {
			fields["export_provenance"] = metadata
			if parseErr == nil {
				for _, k := range []string{"field_paths", "original_start", "source_timezone"} {
					if v, ok := metadata[k]; ok {
						fields[k] = v
					}
				}
			}
		}
		identity := "hash:" + item.raw.Hash
		if normalized.ProviderID != "" && parseErr == nil {
			identity = "garmin:" + normalized.ProviderID
		}
		raw, err := item.raw.persist(ctx, tx)
		if err != nil {
			return err
		}
		tag, err := tx.Exec(ctx, `INSERT INTO source_records(id,source_account_id,import_batch_id,raw_object_id,source_identity,payload_hash,fetched_at,parser_version,source_kind,fields,rejected_reason)
			VALUES(gen_random_uuid(),$1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(source_account_id,source_identity,payload_hash) DO NOTHING`, owner, batch, raw, identity, item.raw.Hash, page.FetchedAt, version, page.SourceKind, fields, rejected)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			continue
		}
		counts.NewRevisions++
		if rejected != nil {
			continue
		}
		var priorDay string
		err = tx.QueryRow(ctx, "SELECT local_date::text FROM activities WHERE source_account_id=$1 AND source_identity=$2", owner, identity).Scan(&priorDay)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		id, day, changed, err := reconcile(ctx, tx, owner, identity, normalized.ProviderID, !summaryOnly)
		if err != nil {
			return err
		}
		if changed {
			counts.Changed++
			r.Activities[id] = day
			r.AffectedDates = append(r.AffectedDates, day)
			if priorDay != "" {
				r.AffectedDates = append(r.AffectedDates, priorDay)
			}
		}
	}
	for _, id := range sortedIDs(p.fits) {
		var activity uuid.UUID
		var day string
		if err := tx.QueryRow(ctx, `SELECT id,local_date::text FROM activities WHERE source_account_id=$1 AND garmin_id=$2`, owner, id).Scan(&activity, &day); err != nil {
			return fmt.Errorf("FIT activity unavailable: %w", err)
		}
		changed, failed, err := applyFIT(ctx, tx, activity, p.fits[id], page.FetchedAt)
		if err != nil {
			return err
		}
		if changed {
			counts.FITDecoded++
			r.Activities[activity] = day
			r.AffectedDates = append(r.AffectedDates, day)
		}
		if failed {
			counts.FITFailed++
		}
	}
	var batchCounts any = counts
	if summaryOnly {
		batchCounts = counts.providerCounts()
	}
	if page.importBatch == uuid.Nil {
		_, err = tx.Exec(ctx, `UPDATE import_batches SET status='complete',finished_at=now(),counters=$2 WHERE id=$1`, batch, batchCounts)
	}
	slices.Sort(r.AffectedDates)
	r.AffectedDates = slices.Compact(r.AffectedDates)
	r.Counts.Seen += counts.Seen
	r.Counts.Changed += counts.Changed
	r.Counts.NewRevisions += counts.NewRevisions
	r.Counts.Rejected += counts.Rejected
	r.Counts.FITDecoded += counts.FITDecoded
	r.Counts.FITFailed += counts.FITFailed
	return err
}
