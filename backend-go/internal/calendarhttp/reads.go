package calendarhttp

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"math"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/athleteprofile"
	"github.com/mtang08/going-bananas/backend-go/internal/calendar"
	"github.com/mtang08/going-bananas/backend-go/internal/coachdashboard"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drafts"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drilldowns"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/httpinput"
	"github.com/mtang08/going-bananas/backend-go/internal/httpresponse"
)

//go:embed view.sql
var calendarViewSQL string

type viewQuery struct {
	start, end string
	version    *int
	from, to   int
}

func parseView(path string, query url.Values) (viewQuery, []field) {
	var q viewQuery
	var issues []field
	keys := []string{"start", "end", "version"}
	switch path {
	case "week":
		keys = []string{"start", "version"}
	case "diff":
		keys = []string{"from", "to"}
	}
	for _, key := range keys {
		values := query[key]
		if len(values) == 0 {
			if path == "diff" {
				issues = append(issues, field{"query." + key, "Field required"})
			}
			continue
		}
		value := values[len(values)-1]
		var message string
		switch key {
		case "start":
			q.start, message = httpinput.Date(value)
		case "end":
			q.end, message = httpinput.Date(value)
		default:
			var n int
			n, message = httpinput.Integer(value, math.MinInt)
			switch key {
			case "from":
				q.from = n
			case "to":
				q.to = n
			default:
				q.version = &n
			}
		}
		if message != "" {
			issues = append(issues, field{"query." + key, message})
		}
	}
	return q, issues
}

func (h Handler) read(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.Path, "/api/v1/calendar")
	path = strings.TrimPrefix(path, "/")
	q, issues := parseView(path, r.URL.Query())
	if len(issues) > 0 {
		fail(w, 422, "validation_error", "Invalid request fields", issues)
		return
	}
	ctx := r.Context()
	var data any
	var revision int32
	err := pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{AccessMode: pgx.ReadOnly, IsoLevel: pgx.RepeatableRead}, func(tx pgx.Tx) error {
		var err error
		if path == "diff" {
			if q.from < 0 || q.to < 0 || q.from > math.MaxInt32 || q.to > math.MaxInt32 {
				return versionMissing()
			}
			data, err = drilldowns.CalendarDiff(ctx, tx, q.from, q.to)
		} else {
			now := time.Now()
			if h.Now != nil {
				now = h.Now()
			}
			data, err = readView(ctx, tx, q, path == "week", now)
		}
		if err != nil {
			return err
		}
		revision, err = db.New(tx).DataRevision(ctx)
		return err
	})
	if err != nil {
		var missing *coachdashboard.ToolFailure
		if errors.As(err, &missing) && missing.Code == "calendar_version_not_found" {
			err = versionMissing()
		}
		domainError(w, err)
		return
	}
	httpresponse.Success(w, h.Mode, int(revision), data)
}

func versionMissing() error {
	return &calendar.Problem{Code: "calendar_version_not_found", Message: "Calendar version not found"}
}

type calendarView struct {
	Today           string                       `json:"today"`
	Timezone        string                       `json:"timezone"`
	Start           string                       `json:"start"`
	End             string                       `json:"end"`
	Version         int                          `json:"version"`
	Head            int                          `json:"head"`
	LastPlannedDate *string                      `json:"last_planned_date"`
	Sessions        []map[string]json.RawMessage `json:"sessions"`
	Completions     []map[string]json.RawMessage `json:"completions"`
	RecordedRuns    []json.RawMessage            `json:"recorded_runs"`
	Versions        []map[string]json.RawMessage `json:"versions"`
	Undo            *calendar.UndoPreview        `json:"undo"`
}

func readView(ctx context.Context, tx pgx.Tx, q viewQuery, week bool, now time.Time) (calendarView, error) {
	var v calendarView
	err := tx.QueryRow(ctx, `SELECT coalesce((SELECT calendar_head_version FROM app_state WHERE id=1),0),
 coalesce((SELECT timezone FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York')`).Scan(&v.Head, &v.Timezone)
	if err != nil {
		return v, err
	}
	loc, err := time.LoadLocation(v.Timezone)
	if err != nil {
		return v, err
	}
	today := now.In(loc)
	v.Today = today.Format(time.DateOnly)
	v.Start, v.End = q.start, q.end
	if week {
		start := today.AddDate(0, 0, -(int(today.Weekday())+6)%7)
		if v.Start != "" {
			start, _ = time.Parse(time.DateOnly, v.Start)
		}
		if start.Weekday() != time.Monday {
			return v, &calendar.Problem{Code: "invalid_week_start", Message: "Week start must be a Monday"}
		}
		v.Start = start.Format(time.DateOnly)
		v.End = start.AddDate(0, 0, 6).Format(time.DateOnly)
	} else {
		if v.Start == "" {
			v.Start = today.AddDate(0, 0, -7).Format(time.DateOnly)
		}
		if v.End == "" {
			v.End = today.AddDate(0, 0, 13).Format(time.DateOnly)
		}
	}
	if v.Start > v.End {
		return v, &calendar.Problem{Code: "invalid_date_window", Message: "Start must be on or before end"}
	}
	v.Version = v.Head
	if q.version != nil {
		v.Version = *q.version
	}
	if v.Version < 0 || v.Version > v.Head {
		return v, versionMissing()
	}
	if v.Version != 0 {
		var exists bool
		if err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT FROM calendar_versions WHERE number=$1)", v.Version).Scan(&exists); err != nil {
			return v, err
		}
		if !exists {
			return v, versionMissing()
		}
	}
	if err := tx.QueryRow(ctx, calendarViewSQL, v.Version, v.Head, v.Start, v.End, v.Today, v.Timezone).Scan(&v.LastPlannedDate, &v.Sessions, &v.Completions, &v.RecordedRuns, &v.Versions); err != nil {
		return v, err
	}
	if v.Version == v.Head {
		p, err := athleteprofile.LoadProfile(ctx, tx, v.Today)
		if err != nil {
			return v, err
		}
		if p.RunningRestriction != nil {
			if err := v.annotate(p.RunningRestriction); err != nil {
				return v, err
			}
		}
	}
	if err := normalizeTimes(v.Completions, "updated_at"); err != nil {
		return v, err
	}
	if err := normalizeTimes(v.Versions, "created_at"); err != nil {
		return v, err
	}
	v.Undo, err = calendar.PreviewUndo(ctx, tx, v.Head, v.Today)
	return v, err
}

func (v calendarView) annotate(limit *athleteprofile.RunningRestriction) error {
	for _, s := range v.Sessions {
		var day string
		if err := json.Unmarshal(s["local_date"], &day); err != nil {
			return err
		}
		if day < v.Today {
			continue
		}
		raw, err := json.Marshal(s)
		if err != nil {
			return err
		}
		conflict, err := drafts.CalendarConflict(limit, raw)
		if err != nil {
			return err
		}
		if conflict != "" {
			s["running_restriction_conflict"], err = json.Marshal(conflict)
			if err != nil {
				return err
			}
		}
	}
	return nil
}

func normalizeTimes(rows []map[string]json.RawMessage, key string) error {
	for _, row := range rows {
		var at time.Time
		if err := json.Unmarshal(row[key], &at); err != nil {
			return err
		}
		encoded, err := json.Marshal(api.Timestamp(at))
		if err != nil {
			return err
		}
		row[key] = encoded
	}
	return nil
}
