package replay

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
)

// JobPage describes the observations and review decisions the caller commits
// alongside the job cursor and coverage. Ready activities can be offered to FIT ingestion.
type JobPage struct {
	Activities    map[uuid.UUID]string
	AffectedDates []string
	Counters      map[string]int
	Newest        *time.Time
	Pending       map[string]any
	Ready         []garmin.Record
}

func (c Counts) providerCounts() map[string]int {
	return map[string]int{"seen": c.Seen, "new_revisions": c.NewRevisions, "changed": c.Changed, "rejected": c.Rejected}
}

func (p *JobPage) observe(at time.Time) {
	if p.Newest == nil || at.After(*p.Newest) {
		p.Newest = &at
	}
}

// ApplyJobPage imports one fetched page using the caller's writer transaction.
func ApplyJobPage(ctx context.Context, tx pgx.Tx, root, dataset, scope string, records []garmin.Record, at time.Time) (JobPage, error) {
	if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
		return JobPage{}, err
	}
	if dataset != "activities" {
		return recoveryJobPage(ctx, tx, root, dataset, records, at)
	}
	p := Page{FetchedAt: at, SourceKind: "garmin_api", AccountScope: scope}
	for _, r := range records {
		p.Records = append(p.Records, ActivityRecord{Record: r})
	}
	result, err := partitionActivities(ctx, tx, p)
	if err != nil {
		return JobPage{}, err
	}
	p.Records = nil
	for _, r := range result.Ready {
		p.Records = append(p.Records, ActivityRecord{Record: r})
	}
	inputs, err := prepare(root, p)
	if err != nil {
		return JobPage{}, err
	}
	replayed := Result{Activities: map[uuid.UUID]string{}}
	if err := applyRecords(ctx, tx, p, inputs, &replayed, true); err != nil {
		return JobPage{}, err
	}
	result.Counters = replayed.Counts.providerCounts()
	result.Activities = replayed.Activities
	result.AffectedDates = replayed.AffectedDates
	coverageChanged, err := resolveImportedReviews(ctx, tx, result.Ready, at)
	if err != nil {
		return JobPage{}, err
	}
	if coverageChanged || replayed.Counts.Changed > 0 {
		if _, err := db.New(tx).BumpDataRevision(ctx); err != nil {
			return JobPage{}, err
		}
	}
	return result, nil
}

func partitionActivities(ctx context.Context, tx pgx.Tx, p Page) (JobPage, error) {
	result := JobPage{Pending: map[string]any{}}
	if len(p.Records) == 0 {
		return result, nil
	}
	scope, err := scopeFor(p)
	if err != nil {
		return result, err
	}
	var prior string
	err = tx.QueryRow(ctx, `SELECT account_scope FROM source_accounts WHERE provider='garmin' ORDER BY (account_scope<>$1) DESC LIMIT 1`, scope).Scan(&prior)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return result, err
	}
	if err == nil && prior != scope {
		return result, errors.New("mixed_source_account")
	}
	zone, err := db.New(tx).CalendarTimezone(ctx)
	if err != nil {
		return result, err
	}
	loc, err := time.LoadLocation(zone)
	if err != nil {
		return result, err
	}
	ids := make([]string, 0, len(p.Records))
	for _, r := range p.Records {
		ids = append(ids, fmt.Sprint(firstTruthy(r.Record["activityId"], r.Record["id"])))
	}
	rows, err := tx.Query(ctx, `SELECT a.garmin_id FROM activities a JOIN source_accounts s ON a.source_account_id=s.id WHERE s.provider='garmin' AND s.account_scope=$1 AND a.garmin_id=ANY($2::text[])`, scope, ids)
	if err != nil {
		return result, err
	}
	existing, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return result, err
	}
	known := make(map[string]bool, len(existing))
	for _, id := range existing {
		known[id] = true
	}
	for _, r := range p.Records {
		n, err := Normalize(r.Record, loc)
		if err == nil {
			if n.Fields["subtype"] == "treadmill_running" && n.ProviderID != "" && !known[n.ProviderID] {
				result.Pending[n.ProviderID] = map[string]string{"local_date": n.Fields["local_date"].(string), "account_scope": scope}
				continue
			}
			start, err := time.Parse(time.RFC3339Nano, n.Fields["start_at"].(string))
			if err != nil {
				return result, err
			}
			result.observe(start)
		}
		result.Ready = append(result.Ready, r.Record)
	}
	return result, nil
}

func resolveImportedReviews(ctx context.Context, tx pgx.Tx, records []garmin.Record, at time.Time) (bool, error) {
	ids := make([]string, 0, len(records))
	for _, r := range records {
		ids = append(ids, fmt.Sprint(firstTruthy(r["activityId"], r["id"])))
	}
	if len(ids) == 0 {
		return false, nil
	}
	var changed bool
	err := tx.QueryRow(ctx, `WITH imported AS (
		SELECT ARRAY(SELECT DISTINCT garmin_id FROM activities WHERE garmin_id=ANY($1::text[])) AS ids
	), changed AS (
		SELECT j.id,j.checkpoint,j.finished_at,(j.checkpoint->'pending_treadmill')-i.ids AS pending
		FROM sync_jobs j CROSS JOIN imported i WHERE dataset='activities' AND (j.checkpoint->'pending_treadmill') ?| i.ids
	), update_jobs AS (
		UPDATE sync_jobs j SET checkpoint=CASE WHEN c.pending='{}'::jsonb THEN j.checkpoint-'pending_treadmill'-'pending_coverage_id'
			ELSE jsonb_set(j.checkpoint,'{pending_treadmill}',c.pending) END FROM changed c WHERE j.id=c.id
	), coverage AS (
		UPDATE coverage_intervals cv SET status='complete',reason=NULL,completed_at=$2 FROM changed c
		WHERE c.pending='{}' AND cv.id=(c.checkpoint->>'pending_coverage_id')::uuid RETURNING cv.id
	), sync AS (
	UPDATE sync_state SET status='complete',reason=NULL,last_success_at=$2 WHERE dataset='activities' AND reason='treadmill_review_pending'
	AND EXISTS(SELECT FROM changed WHERE pending='{}' AND checkpoint ? 'pending_coverage_id' AND last_attempt_at<=finished_at)) SELECT EXISTS(SELECT FROM coverage)`, ids, at).Scan(&changed)
	return changed, err
}
