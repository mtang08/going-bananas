package feedbackhttp

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/exceptions"
	"github.com/mtang08/going-bananas/backend-go/internal/httpinput"
	"github.com/mtang08/going-bananas/backend-go/internal/httpresponse"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
)

var decimalPattern = regexp.MustCompile(`^[+-]?(?:([0-9]+)(?:\.([0-9]*))?|\.([0-9]+))(?:[eE]([+-]?[0-9]+))?$`)

func measurement(value any) (float64, string) {
	const numeric = "Value error, measurement must be numeric"
	const bounds = "Value error, measurement must be 0–10 with at most one decimal place"
	var s string
	switch v := value.(type) {
	case string:
		s = strings.ReplaceAll(strings.TrimSpace(v), "_", "")
	case json.Number:
		s = v.String()
		if strings.ContainsAny(s, ".eE") {
			f, _ := v.Float64()
			s = strconv.FormatFloat(f, 'g', -1, 64)
		}
	default:
		return 0, numeric
	}
	parts := decimalPattern.FindStringSubmatch(s)
	if parts == nil {
		switch strings.TrimLeft(strings.ToLower(s), "+-") {
		case "inf", "infinity", "nan", "snan":
			return 0, bounds
		}
		return 0, numeric
	}
	scale := len(parts[2]) + len(parts[3])
	exp := 0
	if parts[4] != "" {
		var err error
		exp, err = strconv.Atoi(parts[4])
		if err != nil {
			return 0, bounds
		}
	}
	f, err := strconv.ParseFloat(s, 64)
	if err != nil || f < 0 || f > 10 || exp < scale-1 {
		return 0, bounds
	}
	return f, ""
}

type entry struct {
	ActivityID      *uuid.UUID    `json:"activity_id"`
	StrongWorkoutID *uuid.UUID    `json:"strong_workout_id"`
	ManualSessionID *uuid.UUID    `json:"manual_session_id"`
	RPE             float64       `json:"rpe"`
	Source          string        `json:"source"`
	CollectedAt     api.Timestamp `json:"collected_at"`
	Delay           *int          `json:"collection_delay_s"`
}

func (h Handler) rpe(w http.ResponseWriter, r *http.Request) {
	pathKey := "activity_id"
	if r.PathValue(pathKey) == "" {
		pathKey = "workout_id"
	}
	id, msg := httpinput.UUID(r.PathValue(pathKey))
	values, order, fields := httpinput.Object(r.Body)
	if msg != "" && (len(fields) == 0 || fields[0].Message != "JSON decode error") {
		fields = append([]api.ValidationField{{Field: "path." + pathKey, Message: msg}}, fields...)
	}
	var value float64
	if values != nil {
		v, ok := values["rpe"]
		if !ok {
			fields = append(fields, api.ValidationField{Field: "body.rpe", Message: "Field required"})
		} else {
			f, m := measurement(v)
			value = f
			if m != "" {
				fields = append(fields, api.ValidationField{Field: "body.rpe", Message: m})
			}
		}
		for _, key := range order {
			if key != "rpe" {
				fields = append(fields, api.ValidationField{Field: "body." + key, Message: "Extra inputs are not permitted"})
			}
		}
	}
	if len(fields) > 0 {
		httpresponse.Error(w, 422, "validation_error", "Invalid request fields", fields)
		return
	}
	ctx := r.Context()
	var out entry
	now := h.now()
	activity := pathKey == "activity_id"
	err := pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
			return err
		}
		var err error
		out, err = saveRPE(ctx, tx, *id, activity, value, now)
		return err
	})
	if err == nil && activity {
		err = pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error { _, err := exceptions.Detect(ctx, tx, h.now()); return err })
	}
	var rev int
	if err == nil {
		rev, err = revision(ctx, h.Pool)
	}
	h.respond(w, rev, out, err)
}

func subjectEnd(ctx context.Context, tx pgx.Tx, id uuid.UUID, activity bool) (*time.Time, error) {
	var end *time.Time
	var err error
	if activity {
		var sport string
		err = tx.QueryRow(ctx, `SELECT sport,coalesce(end_at,start_at+elapsed_s*interval '1 second') FROM activities WHERE id=$1`, id).Scan(&sport, &end)
		if err == nil && sport != "running" && sport != "trail_running" && sport != "treadmill_running" {
			return nil, &problem{422, "rpe_subject_not_run", "Activity is not a run"}
		}
	} else {
		var local, zone string
		var duration *float64
		err = tx.QueryRow(ctx, `SELECT local_start,duration_s,coalesce((SELECT timezone FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York') FROM strong_workouts WHERE id=$1`, id).Scan(&local, &duration, &zone)
		if err == nil && duration != nil {
			loc, e := time.LoadLocation(zone)
			if e != nil {
				return nil, e
			}
			for _, layout := range []string{"2006-01-02T15:04:05", "2006-01-02 15:04:05"} {
				t, e := time.ParseInLocation(layout, local, loc)
				if e == nil {
					v := t.Add(time.Duration(math.RoundToEven(*duration*1e6)) * time.Microsecond)
					end = &v
					break
				}
			}
		}
	}
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, &problem{404, "rpe_subject_not_found", "RPE subject not found"}
	}
	return end, err
}

func saveRPE(ctx context.Context, tx pgx.Tx, id uuid.UUID, activity bool, value float64, now time.Time) (entry, error) {
	out := entry{RPE: value, Source: "manual"}
	end, err := subjectEnd(ctx, tx, id, activity)
	if err != nil {
		return out, err
	}
	column, scope := "strong_workout_id", "strength:strong:"+id.String()
	out.StrongWorkoutID = &id
	if activity {
		column, scope = "activity_id", "activity:"+id.String()
		out.StrongWorkoutID = nil
		out.ActivityID = &id
	}
	if end != nil && !now.Before(*end) {
		v := int(now.Sub(*end).Seconds())
		out.Delay = &v
	}
	tag, err := tx.Exec(ctx, `INSERT INTO session_rpe(id,`+column+`,rpe,source,collected_at,collection_delay_s) VALUES(gen_random_uuid(),$1,$2,'manual',$3,$4)
 ON CONFLICT(`+column+`,source) DO UPDATE SET rpe=EXCLUDED.rpe,collected_at=EXCLUDED.collected_at,collection_delay_s=EXCLUDED.collection_delay_s WHERE session_rpe.rpe<>EXCLUDED.rpe`, id, value, now, out.Delay)
	if err != nil {
		return out, err
	}
	if tag.RowsAffected() > 0 {
		out.CollectedAt = api.Timestamp(now)
		if _, err := db.New(tx).BumpDataRevision(ctx); err != nil {
			return out, err
		}
		return out, refresh.DerivedScopes(ctx, tx, []string{scope}, now)
	}
	var at string
	err = tx.QueryRow(ctx, "SELECT to_jsonb(collected_at)#>>'{}',collection_delay_s FROM session_rpe WHERE "+column+"=$1 AND source='manual'", id).Scan(&at, &out.Delay)
	if err == nil {
		out.CollectedAt, err = stamp(at)
	}
	return out, err
}
