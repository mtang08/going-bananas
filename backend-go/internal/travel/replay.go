package travel

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

var ErrMissingFetchTime = errors.New("missing_fetch_time")

// Delivery contains one complete events.list window. On pages after the first,
// page_token records the token sent with the request that returned that page.
type Delivery struct {
	Now   time.Time         `json:"now"`
	Pages []json.RawMessage `json:"pages"`
}

type Window struct {
	Start string    `json:"start"`
	End   string    `json:"end"`
	From  time.Time `json:"-"`
	Until time.Time `json:"-"`
}

func SyncWindow(now time.Time, home *time.Location) Window {
	y, m, d := now.In(home).Date()
	today := time.Date(y, m, d, 0, 0, 0, 0, home)
	start, end := today.AddDate(0, 0, -30), today.AddDate(0, 0, 180)
	return Window{Start: start.Format(time.DateOnly), End: end.Format(time.DateOnly),
		From: start, Until: end.AddDate(0, 0, 1)}
}

type EventCounts struct {
	Fetched   int `json:"fetched"`
	Created   int `json:"created"`
	Changed   int `json:"changed"`
	Unchanged int `json:"unchanged"`
	Removed   int `json:"removed"`
	Restored  int `json:"restored"`
}

type SyncReceipt struct {
	StartedAt  time.Time   `json:"started_at"`
	FinishedAt time.Time   `json:"finished_at"`
	Window     Window      `json:"window"`
	Counters   EventCounts `json:"counters"`
}

type Result struct {
	Sync         SyncReceipt `json:"sync"`
	Trips        TripCounts  `json:"trips"`
	DataRevision int32       `json:"-"`
}

func completeWindow(pages []json.RawMessage) (map[string]*Record, error) {
	if len(pages) == 0 || len(pages) > 20 {
		return nil, ErrInvalidResponse
	}
	records := make(map[string]*Record)
	seen := make(map[string]bool)
	var expectedToken string
	for i, raw := range pages {
		var page map[string]json.RawMessage
		if err := json.Unmarshal(raw, &page); err != nil || page == nil {
			return nil, ErrInvalidResponse
		}
		token, ok := pageToken(page["page_token"])
		if !ok || token != expectedToken {
			return nil, ErrInvalidResponse
		}
		next, ok := pageToken(page["nextPageToken"])
		if !ok || seen[next] || (next == "") != (i == len(pages)-1) {
			return nil, ErrInvalidResponse
		}
		seen[next] = true
		expectedToken = next
		if data, exists := page["items"]; exists {
			var items []map[string]any
			if err := json.Unmarshal(data, &items); err != nil || items == nil {
				return nil, ErrInvalidResponse
			}
			for _, item := range items {
				r, err := NormalizeEvent(item)
				if err != nil {
					return nil, err
				}
				if r != nil {
					records[r.GoogleEventID] = r
				}
			}
		}
	}
	return records, nil
}

func pageToken(raw json.RawMessage) (string, bool) {
	if raw == nil {
		return "", true
	}
	var token string
	err := json.Unmarshal(raw, &token)
	return token, err == nil
}

// Apply reconciles previously fetched pages. A complete receipt, all event and
// leg writes, and the source revision commit together under the app writer lock.
func Apply(ctx context.Context, pool *pgxpool.Pool, delivery Delivery) (Result, error) {
	return applyWindow(ctx, pool, delivery, nil)
}

func applyWindow(ctx context.Context, pool *pgxpool.Pool, delivery Delivery, home *time.Location) (Result, error) {
	if delivery.Now.IsZero() {
		return Result{}, ErrMissingFetchTime
	}
	now := delivery.Now.UTC().Truncate(time.Microsecond)
	records, err := completeWindow(delivery.Pages)
	if err != nil {
		if receiptErr := RecordFailure(ctx, pool, now, "gcal_invalid_response"); receiptErr != nil {
			return Result{}, receiptErr
		}
		return Result{}, err
	}
	var result Result
	err = pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		q := db.New(tx)
		if err := q.LockGlobalWriter(ctx); err != nil {
			return err
		}
		if home == nil {
			zone, err := q.CalendarTimezone(ctx)
			if err != nil {
				return err
			}
			home, err = time.LoadLocation(zone)
			if err != nil {
				return err
			}
		}
		window := SyncWindow(now, home)
		events, err := upsertEvents(ctx, tx, records, home, window, now)
		if err != nil {
			return err
		}
		trips, err := reconcileTrips(ctx, tx, home)
		if err != nil {
			return err
		}
		if events.Created+events.Changed+events.Removed+events.Restored > 0 || trips.changed {
			result.DataRevision, err = q.BumpDataRevision(ctx)
		} else {
			err = tx.QueryRow(ctx, "SELECT data_revision FROM app_state WHERE id=1").Scan(&result.DataRevision)
		}
		if err != nil {
			return err
		}
		counters := map[string]int{
			"fetched": events.Fetched, "created": events.Created, "changed": events.Changed,
			"unchanged": events.Unchanged, "removed": events.Removed, "restored": events.Restored,
			"trips_created": trips.Created, "trips_updated": trips.Updated, "trips_deleted": trips.Deleted, "trips_flagged": trips.Flagged,
		}
		var finished time.Time
		if err := tx.QueryRow(ctx, `INSERT INTO import_batches(id,source_kind,adapter_version,status,started_at,finished_at,counters)
			VALUES(gen_random_uuid(),'google_calendar','gcal-v1','complete',$1,clock_timestamp(),$2)
			RETURNING finished_at`, now, counters).Scan(&finished); err != nil {
			return err
		}
		result.Sync = SyncReceipt{StartedAt: now, FinishedAt: finished.UTC(), Window: window, Counters: events}
		result.Trips = trips
		return nil
	})
	if err != nil {
		return Result{}, err
	}
	return result, nil
}

// RecordFailure records a fetch failure without reconciling a partial calendar.
func RecordFailure(ctx context.Context, pool *pgxpool.Pool, started time.Time, code string) error {
	return pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `INSERT INTO import_batches(id,source_kind,adapter_version,status,started_at,finished_at,counters,error_code)
		VALUES(gen_random_uuid(),'google_calendar','gcal-v1','failed',$1,clock_timestamp(),'{}',$2)`, started, code)
		return err
	})
}
