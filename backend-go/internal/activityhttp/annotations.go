package activityhttp

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"slices"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/httpinput"
	"github.com/mtang08/going-bananas/backend-go/internal/httpresponse"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
)

type annotation struct {
	version      int
	label, notes *string
	excluded     bool
}

func boolValue(v any) (bool, string) {
	switch x := v.(type) {
	case bool:
		return x, ""
	case string:
		switch strings.ToLower(x) {
		case "true", "t", "on", "yes", "y", "1":
			return true, ""
		case "false", "f", "off", "no", "n", "0":
			return false, ""
		}
		return false, "Input should be a valid boolean, unable to interpret input"
	case json.Number:
		n, err := x.Float64()
		if err == nil {
			if n == 0 || n == 1 {
				return n == 1, ""
			}
			if n == float64(int64(n)) {
				return false, "Input should be a valid boolean, unable to interpret input"
			}
		}
	}
	return false, "Input should be a valid boolean"
}

func bindAnnotation(r *http.Request) (*uuid.UUID, annotation, []api.ValidationField) {
	id, msg := httpinput.UUID(r.PathValue("activity_id"))
	data, _, fields := httpinput.Object(r.Body)
	if msg != "" && (len(fields) == 0 || fields[0].Message != "JSON decode error") {
		fields = append([]api.ValidationField{{Field: "path.activity_id", Message: msg}}, fields...)
	}
	var a annotation
	if data == nil {
		return id, a, fields
	}
	add := func(k, m string) {
		if m != "" {
			fields = append(fields, api.ValidationField{Field: "body." + k, Message: m})
		}
	}
	if v, ok := data["expected_version"]; ok {
		a.version, msg = httpinput.Integer(v, 0)
		add("expected_version", msg)
	} else {
		add("expected_version", "Field required")
	}
	if v := data["workout_label"]; v != nil {
		s, ok := v.(string)
		if !ok || !slices.Contains([]string{"easy", "quality", "long", "other"}, s) {
			add("workout_label", "Input should be 'easy', 'quality', 'long' or 'other'")
		} else {
			a.label = &s
		}
	}
	if v := data["notes"]; v != nil {
		s, ok := v.(string)
		if !ok {
			add("notes", "Input should be a valid string")
		} else if utf8.RuneCountInString(s) > 4000 {
			add("notes", "String should have at most 4000 characters")
		} else {
			a.notes = &s
		}
	}
	if v, ok := data["excluded"]; ok {
		a.excluded, msg = boolValue(v)
		add("excluded", msg)
	}
	return id, a, fields
}

func (h Handler) patchAnnotation(w http.ResponseWriter, r *http.Request) {
	id, a, fields := bindAnnotation(r)
	if len(fields) > 0 {
		httpresponse.Error(w, 422, "validation_error", "Invalid request fields", fields)
		return
	}
	ctx := r.Context()
	now := time.Now().UTC()
	if h.Now != nil {
		now = h.Now()
	}
	err := pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error { return saveAnnotation(ctx, tx, *id, a, now) })
	if err != nil {
		var p *problem
		if errors.As(err, &p) {
			httpresponse.Error(w, p.status, p.code, p.msg, nil)
		} else {
			httpresponse.Error(w, 500, "internal_error", "Internal server error", nil)
		}
		return
	}
	h.respond(h.detail, false)(w, r)
}

func saveAnnotation(ctx context.Context, tx pgx.Tx, id uuid.UUID, a annotation, now time.Time) error {
	q := db.New(tx)
	if err := q.LockGlobalWriter(ctx); err != nil {
		return err
	}
	var version int
	err := tx.QueryRow(ctx, `SELECT coalesce((SELECT max(version) FROM activity_annotations WHERE activity_id=a.id),0) FROM activities a WHERE a.id=$1`, id).Scan(&version)
	if errors.Is(err, pgx.ErrNoRows) {
		return &problem{404, "not_found", "Activity not found", nil}
	}
	if err != nil {
		return err
	}
	if version != a.version {
		return &problem{409, "version_conflict", "Annotation changed; reload activity", nil}
	}
	_, err = tx.Exec(ctx, `INSERT INTO activity_annotations(id,activity_id,version,workout_label,notes,excluded) VALUES(gen_random_uuid(),$1,$2,$3,$4,$5)`, id, version+1, a.label, a.notes, a.excluded)
	if err != nil {
		return err
	}
	if _, err = q.BumpDataRevision(ctx); err != nil {
		return err
	}
	return refresh.DerivedScopes(ctx, tx, []string{"activity:" + id.String()}, now)
}
