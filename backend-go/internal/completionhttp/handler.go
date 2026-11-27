// Package completionhttp registers completion writes on the application's guarded local mux.
package completionhttp

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/calendar"
	"github.com/mtang08/going-bananas/backend-go/internal/exceptions"
	"github.com/mtang08/going-bananas/backend-go/internal/httpinput"
	"github.com/mtang08/going-bananas/backend-go/internal/httpresponse"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
)

type Handler struct {
	Pool *pgxpool.Pool
	Mode string
	Now  func() time.Time
}

func (h Handler) Register(mux *http.ServeMux) {
	mux.HandleFunc("PUT /api/v1/calendar/completions/{session_uid}", h.put)
}

func (h Handler) now() time.Time {
	if h.Now != nil {
		return h.Now().UTC()
	}
	return time.Now().UTC()
}

func (h Handler) put(w http.ResponseWriter, r *http.Request) {
	id, idMessage := httpinput.UUID(r.PathValue("session_uid"))
	in, fields := bind(r.Body)
	if idMessage != "" && (len(fields) == 0 || fields[0].Message != "JSON decode error") {
		fields = append([]api.ValidationField{{Field: "path.session_uid", Message: idMessage}}, fields...)
	}
	if len(fields) > 0 {
		httpresponse.Error(w, 422, "validation_error", "Invalid request fields", fields)
		return
	}
	count := 0
	for _, v := range []*uuid.UUID{in.link.ActivityID, in.link.StrongWorkoutID, in.link.ManualSessionID} {
		if v != nil {
			count++
		}
	}
	if count > 1 {
		httpresponse.Error(w, 422, "invalid_completion", "At most one subject is allowed", nil)
		return
	}
	if count == 1 && in.hasStatus {
		httpresponse.Error(w, 422, "invalid_completion", "Linked completion status is assessed", nil)
		return
	}
	ctx := r.Context()
	now := h.now()
	var change calendar.CompletionChange
	err := pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		after := calendar.DerivedRefresh(now, refresh.CompletionMetrics(now, nil))
		var err error
		if count == 1 {
			change, err = calendar.SaveRecordingLink(ctx, tx, *id, in.link, now, refresh.AssessCompletion(now), after)
		} else {
			change, err = calendar.SaveSelfReport(ctx, tx, *id, calendar.SelfReport{ExpectedVersion: in.link.ExpectedVersion, Status: in.status, ModificationReason: in.link.ModificationReason, ReasonNote: in.link.ReasonNote}, now, after)
		}
		return err
	})
	if err != nil {
		var p *calendar.Problem
		if errors.As(err, &p) {
			status := 422
			switch p.Code {
			case "version_conflict", "already_linked", "subject_already_linked":
				status = 409
			case "completion_subject_not_found":
				status = 404
			}
			httpresponse.Error(w, status, p.Code, p.Message, nil)
			return
		}
		httpresponse.Error(w, 500, "internal_error", "Internal server error", nil)
		return
	}
	// FastAPI commits the source change before running the detector in its own transaction.
	err = pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error { _, err := exceptions.Detect(ctx, tx, h.now()); return err })
	if err != nil {
		httpresponse.Error(w, 500, "internal_error", "Internal server error", nil)
		return
	}
	data, revision, err := h.read(ctx, *id, change.After != nil)
	if err != nil {
		httpresponse.Error(w, 500, "internal_error", "Internal server error", nil)
		return
	}
	httpresponse.Success(w, h.Mode, revision, data)
}

func (h Handler) read(ctx context.Context, id uuid.UUID, present bool) (json.RawMessage, int, error) {
	var revision int
	var raw json.RawMessage
	err := pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly}, func(tx pgx.Tx) error {
		if err := tx.QueryRow(ctx, "SELECT data_revision FROM app_state WHERE id=1").Scan(&revision); err != nil || !present {
			return err
		}
		return tx.QueryRow(ctx, `SELECT jsonb_build_object('id',c.id,'session_uid',c.session_uid,'activity_id',c.activity_id,
 'strong_workout_id',c.strong_workout_id,'manual_session_id',c.manual_session_id,'status',c.status,'match_method',c.match_method,
 'modification_reason',c.modification_reason,'reason_note',c.reason_note,'version',c.version,'input_version',c.input_version,'local_date',coalesce((a.start_at AT TIME ZONE coalesce((SELECT timezone FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York'))::date,s.local_date,m.date,CASE WHEN NOT p.deleted THEN p.local_date END),'updated_at',
 to_char(c.updated_at,'YYYY-MM-DD"T"HH24:MI:SS')||CASE WHEN extract(microseconds FROM c.updated_at)::integer%1000000<>0 THEN to_char(c.updated_at,'.US') ELSE '' END||CASE WHEN extract(timezone FROM c.updated_at)=0 THEN 'Z' ELSE to_char(c.updated_at,'TZH:TZM') END) FROM session_completions c
 LEFT JOIN activities a ON a.id=c.activity_id LEFT JOIN strong_workouts s ON s.id=c.strong_workout_id LEFT JOIN manual_sessions m ON m.id=c.manual_session_id
 LEFT JOIN LATERAL(SELECT local_date,deleted FROM calendar_session_revisions WHERE session_uid=c.session_uid AND calendar_version_number<=(SELECT calendar_head_version FROM app_state WHERE id=1) ORDER BY calendar_version_number DESC,revision DESC LIMIT 1)p ON true WHERE c.session_uid=$1`, id).Scan(&raw)
	})
	return raw, revision, err
}
