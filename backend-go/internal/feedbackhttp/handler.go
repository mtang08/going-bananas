// Package feedbackhttp serves open prompts, prompt dismissal and manual session RPE.
package feedbackhttp

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/httpinput"
	"github.com/mtang08/going-bananas/backend-go/internal/httpresponse"
)

type Handler struct {
	Pool *pgxpool.Pool
	Mode string
	Now  func() time.Time
}

func (h Handler) now() time.Time {
	if h.Now != nil {
		return h.Now().UTC()
	}
	return time.Now().UTC()
}

func (h Handler) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/prompts", h.list)
	mux.HandleFunc("POST /api/v1/prompts/{prompt_id}/dismiss", h.dismiss)
	mux.HandleFunc("PUT /api/v1/activities/{activity_id}/rpe", h.rpe)
	mux.HandleFunc("PUT /api/v1/strength/history/{workout_id}/rpe", h.rpe)
}

type problem struct {
	status        int
	code, message string
}

func (p *problem) Error() string { return p.message }
func (h Handler) respond(w http.ResponseWriter, r int, value any, err error) {
	if err == nil {
		httpresponse.Success(w, h.Mode, r, value)
		return
	}
	var p *problem
	if errors.As(err, &p) {
		httpresponse.Error(w, p.status, p.code, p.message, nil)
	} else {
		httpresponse.Error(w, 500, "internal_error", "Internal server error", nil)
	}
}

type prompt struct {
	ID         uuid.UUID      `json:"id"`
	Kind       string         `json:"kind"`
	ActivityID *uuid.UUID     `json:"activity_id"`
	SessionUID *uuid.UUID     `json:"session_uid"`
	OpensAt    api.Timestamp  `json:"opens_at"`
	ClosesAt   *api.Timestamp `json:"closes_at"`
	Status     string         `json:"status"`
}

const promptColumns = `id,kind,activity_id,session_uid,to_jsonb(opens_at)#>>'{}',to_jsonb(closes_at)#>>'{}',status`

func stamp(s string) (api.Timestamp, error) {
	t, err := time.Parse(time.RFC3339Nano, s)
	return api.Timestamp(t), err
}
func scanPrompt(row pgx.Row) (prompt, error) {
	var p prompt
	var open string
	var close *string
	err := row.Scan(&p.ID, &p.Kind, &p.ActivityID, &p.SessionUID, &open, &close, &p.Status)
	if err != nil {
		return p, err
	}
	p.OpensAt, err = stamp(open)
	if err != nil {
		return p, err
	}
	if close != nil {
		v, err := stamp(*close)
		if err != nil {
			return p, err
		}
		p.ClosesAt = &v
	}
	return p, nil
}

func (h Handler) list(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	var revision int
	var items []prompt
	err := pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly}, func(tx pgx.Tx) error {
		rows, err := tx.Query(ctx, `SELECT `+promptColumns+` FROM prompts WHERE status='open' AND opens_at<=$1 AND(closes_at IS NULL OR closes_at>$1) ORDER BY opens_at DESC,id DESC`, h.now())
		if err != nil {
			return err
		}
		items, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (prompt, error) { return scanPrompt(row) })
		if err != nil {
			return err
		}
		return tx.QueryRow(ctx, "SELECT data_revision FROM app_state WHERE id=1").Scan(&revision)
	})
	if items == nil {
		items = []prompt{}
	}
	h.respond(w, revision, map[string]any{"items": items}, err)
}

func (h Handler) dismiss(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	id, msg := httpinput.UUID(r.PathValue("prompt_id"))
	if msg != "" {
		httpresponse.Error(w, 422, "validation_error", "Invalid request fields", []api.ValidationField{{Field: "path.prompt_id", Message: msg}})
		return
	}
	var data prompt
	var revision int
	err := pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
			return err
		}
		p, err := scanPrompt(tx.QueryRow(ctx, "SELECT "+promptColumns+" FROM prompts WHERE id=$1 FOR UPDATE", id))
		if errors.Is(err, pgx.ErrNoRows) {
			return &problem{404, "prompt_not_found", "Prompt not found"}
		}
		if err != nil {
			return err
		}
		switch p.Status {
		case "answered":
			return &problem{409, "prompt_already_answered", "Answered prompt cannot be dismissed"}
		case "open", "expired":
			if _, err := tx.Exec(ctx, "UPDATE prompts SET status='dismissed' WHERE id=$1", id); err != nil {
				return err
			}
			p.Status = "dismissed"
		}
		data = p
		return tx.QueryRow(ctx, "SELECT data_revision FROM app_state WHERE id=1").Scan(&revision)
	})
	h.respond(w, revision, data, err)
}

func revision(ctx context.Context, pool *pgxpool.Pool) (int, error) {
	var n int
	err := pool.QueryRow(ctx, "SELECT data_revision FROM app_state WHERE id=1").Scan(&n)
	return n, err
}
