package synchttp

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/httpinput"
	"github.com/mtang08/going-bananas/backend-go/internal/providerjobs"
	"github.com/mtang08/going-bananas/backend-go/internal/pydantic"
)

type jobView struct {
	ID         uuid.UUID       `json:"id"`
	Dataset    string          `json:"dataset"`
	Status     string          `json:"status"`
	Start      *string         `json:"start_date"`
	End        *string         `json:"end_date"`
	Checkpoint json.RawMessage `json:"checkpoint"`
	Counters   json.RawMessage `json:"counters"`
	Next       *string         `json:"next_attempt_at"`
	Error      *string         `json:"error_code"`
}

const jobsSQL = `SELECT id,dataset,status,start_date::text,end_date::text,checkpoint-'pending_treadmill'-'pending_coverage_id',counters,to_jsonb(next_attempt_at)#>>'{}',error_code FROM sync_jobs`

type stateView struct {
	Dataset     string  `json:"dataset"`
	Status      string  `json:"status"`
	Reason      *string `json:"reason"`
	Attempt     *string `json:"last_attempt_at"`
	Success     *string `json:"last_success_at"`
	Observation *string `json:"newest_observation_at"`
	Start       *string `json:"requested_start"`
	End         *string `json:"requested_end"`
	Enumerated  bool    `json:"fully_enumerated"`
}

func stamp(p *string) *string {
	if p == nil {
		return nil
	}
	t, err := time.Parse(time.RFC3339Nano, *p)
	if err != nil {
		return p
	}
	layout := "2006-01-02T15:04:05-07:00"
	if t.Nanosecond() != 0 {
		layout = "2006-01-02T15:04:05.000000-07:00"
	}
	s := t.Format(layout)
	return &s
}
func list[T any](ctx context.Context, tx pgx.Tx, sql string, args ...any) ([]T, error) {
	rows, err := tx.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowToStructByPos[T])
}
func oneJob(ctx context.Context, tx pgx.Tx, id uuid.UUID) (jobView, error) {
	rows, err := list[jobView](ctx, tx, jobsSQL+" WHERE id=$1", id)
	if err != nil {
		return jobView{}, err
	}
	if len(rows) == 0 {
		return jobView{}, issue(404, "job_not_found", "Sync job not found")
	}
	rows[0].Next = stamp(rows[0].Next)
	return rows[0], nil
}
func (h *Handler) job(w http.ResponseWriter, r *http.Request) {
	id, msg := pydantic.UUID(r.PathValue("job_id"))
	if msg != "" {
		failure(w, invalid([]field{{"path.job_id", msg}}))
		return
	}
	h.respond(w, r, 200, false, func(ctx context.Context, tx pgx.Tx) (any, error) { return oneJob(ctx, tx, id) })
}

type pendingView struct {
	ID   string `json:"id"`
	Date string `json:"local_date"`
}

func (h *Handler) status(w http.ResponseWriter, r *http.Request) {
	h.respond(w, r, 200, false, func(ctx context.Context, tx pgx.Tx) (any, error) {
		states, err := list[stateView](ctx, tx, `SELECT dataset,status,reason,to_jsonb(last_attempt_at)#>>'{}',to_jsonb(last_success_at)#>>'{}',to_jsonb(newest_observation_at)#>>'{}',requested_start::text,requested_end::text,fully_enumerated FROM sync_state ORDER BY dataset`)
		if err != nil {
			return nil, err
		}
		for i := range states {
			s := &states[i]
			s.Attempt = stamp(s.Attempt)
			s.Success = stamp(s.Success)
			s.Observation = stamp(s.Observation)
		}
		jobs, err := list[jobView](ctx, tx, jobsSQL+" WHERE status IN ('queued','running','retry_wait') ORDER BY created_at")
		if err != nil {
			return nil, err
		}
		for i := range jobs {
			jobs[i].Next = stamp(jobs[i].Next)
		}
		pending, err := list[pendingView](ctx, tx, `SELECT id,day FROM (SELECT DISTINCT ON (p.key) p.key id,p.value->>'local_date' AS day FROM sync_jobs j CROSS JOIN LATERAL jsonb_each(j.checkpoint->'pending_treadmill') p WHERE dataset='activities' ORDER BY p.key,j.created_at DESC,j.id DESC) latest ORDER BY day DESC,id DESC`)
		return map[string]any{"datasets": states, "active_jobs": jobs, "pending_treadmill_runs": pending}, err
	})
}
func (h *Handler) enqueue(w http.ResponseWriter, r *http.Request) {
	body, err := object(r)
	if err != nil {
		failure(w, err)
		return
	}
	var dates [2]*time.Time
	var fields []field
	for i, k := range []string{"start_date", "end_date"} {
		if body[k] == nil {
			continue
		}
		s, msg := httpinput.Date(body[k])
		if msg != "" {
			fields = append(fields, field{"body." + k, msg})
			continue
		}
		t, _ := time.Parse(time.DateOnly, s)
		dates[i] = &t
	}
	if len(fields) == 0 && dates[0] != nil && dates[1] != nil && (dates[0].After(*dates[1]) || dates[1].After(dates[0].AddDate(0, 0, 366))) {
		fields = append(fields, field{"body", "Value error, invalid_sync_range"})
	}
	if len(fields) > 0 {
		failure(w, invalid(fields))
		return
	}
	if h.Mode != "real" {
		failure(w, realOnly)
		return
	}
	h.respond(w, r, 202, true, func(ctx context.Context, tx pgx.Tx) (any, error) {
		var end time.Time
		if dates[1] == nil {
			name, err := db.New(tx).CalendarTimezone(ctx)
			if err != nil {
				return nil, err
			}
			zone, err := time.LoadLocation(name)
			if err != nil {
				return nil, err
			}
			end = h.Now().In(zone)
		} else {
			end = *dates[1]
		}
		jobs, err := providerjobs.EnqueueRequested(ctx, tx, dates[0], end)
		if errors.Is(err, providerjobs.ErrInvalidRange) {
			return nil, issue(422, "invalid_sync_range", "Sync dates must be in order and at most 366 days apart.")
		}
		if err != nil {
			return nil, err
		}
		views := make([]jobView, 0, len(jobs))
		for _, job := range jobs {
			v, err := oneJob(ctx, tx, job.ID)
			if err != nil {
				return nil, err
			}
			views = append(views, v)
		}
		return map[string]any{"jobs": views}, nil
	})
}
