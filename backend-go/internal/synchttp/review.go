package synchttp

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/fit"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/replay"
)

var notPending = issue(404, "treadmill_review_not_found", "This treadmill run is no longer pending.")
var reload = issue(409, "treadmill_review_reload_required", "Reload the treadmill review before saving.")
var unavailable = issue(502, "treadmill_review_unavailable", "Could not load this treadmill run from Garmin. Try again.")

type entry struct {
	Scope string `json:"account_scope"`
	Day   string `json:"local_date"`
	Extra bool
}
type lap struct {
	Index     int      `json:"lap_index"`
	Timer     *float64 `json:"timer_s"`
	Intensity *string  `json:"intensity"`
	Pace      *float64 `json:"recorded_pace_seconds_per_mile"`
}
type preview struct {
	ID        string   `json:"id"`
	Token     string   `json:"preview_token"`
	Day       string   `json:"local_date"`
	Title     *string  `json:"title"`
	Distance  *float64 `json:"distance_m"`
	Timer     *float64 `json:"timer_s"`
	Intervals []lap    `json:"intervals"`
	entry     entry
	row       garmin.Record
	archive   []byte
}

func (h *Handler) cache(p preview) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.previews = append(h.previews, p)
	if len(h.previews) > 4 {
		h.previews = slices.Delete(h.previews, 0, 1)
	}
}
func pending(ctx context.Context, tx pgx.Tx, id string, lock bool) (entry, error) {
	sql := `SELECT p->>'account_scope',p->>'local_date',(p-'account_scope'-'local_date')<>'{}'::jsonb FROM sync_jobs CROSS JOIN LATERAL (SELECT checkpoint->'pending_treadmill'->$1::text AS p) entry WHERE dataset='activities' AND (checkpoint->'pending_treadmill') ? $1 ORDER BY created_at,id`
	if lock {
		sql += " FOR UPDATE"
	}
	rows, err := tx.Query(ctx, sql, id)
	if err != nil {
		return entry{}, err
	}
	items, err := pgx.CollectRows(rows, pgx.RowToStructByPos[entry])
	if err != nil {
		return entry{}, err
	}
	if len(items) == 0 {
		return entry{}, notPending
	}
	return items[len(items)-1], nil
}
func (h *Handler) review(w http.ResponseWriter, r *http.Request) {
	if h.Mode != "real" {
		failure(w, realOnly)
		return
	}
	id := r.PathValue("remote_id")
	ctx := r.Context()
	var e entry
	var zone string
	err := pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{AccessMode: pgx.ReadOnly}, func(tx pgx.Tx) error {
		var err error
		e, err = pending(ctx, tx, id, false)
		if err == nil {
			zone, err = db.New(tx).CalendarTimezone(ctx)
		}
		return err
	})
	if err != nil {
		failure(w, err)
		return
	}
	p, err := h.fetch(ctx, id, e, zone)
	if err != nil {
		failure(w, err)
		return
	}
	h.cache(p)
	h.respond(w, r, 200, false, func(context.Context, pgx.Tx) (any, error) { return p, nil })
}
func (h *Handler) fetch(ctx context.Context, id string, e entry, zone string) (preview, error) {
	p := preview{ID: id, Token: strings.ReplaceAll(uuid.NewString(), "-", ""), entry: e, Intervals: []lap{}}
	day, err := time.Parse(time.DateOnly, e.Day)
	if err != nil {
		return p, unavailable
	}
	loc, err := time.LoadLocation(zone)
	if err != nil {
		return p, unavailable
	}
	src, err := h.OpenSource(ctx)
	if err != nil {
		return p, unavailable
	}
	for page, err := range src.Pages(ctx, day.AddDate(0, 0, -1), day.AddDate(0, 0, 1), 50, 200) {
		if err != nil {
			return p, unavailable
		}
		for _, row := range page.Records {
			if replay.ActivityID(row) == id {
				p.row = row
				break
			}
		}
		if p.row != nil {
			break
		}
	}
	if p.row == nil {
		return p, issue(502, "treadmill_summary_unavailable", "Garmin did not return this treadmill run. Try again.")
	}
	if p.row["ownerId"] == nil || "garmin-owner:"+fmt.Sprint(p.row["ownerId"]) != e.Scope {
		return p, unavailable
	}
	n, err := replay.Normalize(p.row, loc)
	if err != nil {
		return p, unavailable
	}
	if n.Fields["subtype"] != "treadmill_running" {
		return p, issue(409, "treadmill_summary_changed", "Garmin no longer lists this activity as a treadmill run.")
	}
	p.Day = n.Fields["local_date"].(string)
	if distance, ok := n.Fields["distance_m"].(float64); ok {
		p.Distance = &distance
	}
	if s, ok := p.row["activityName"].(string); ok {
		p.Title = &s
	}
	p.archive, err = src.DownloadActivity(ctx, id)
	if err != nil {
		var remote *garmin.RemoteError
		if errors.As(err, &remote) && remote.StatusCode == 404 {
			p.archive = nil
			return p, nil
		}
		return p, unavailable
	}
	if len(p.archive) > 50<<20 {
		return p, unavailable
	}
	d, err := fit.DecodeZIP(p.archive)
	if err != nil {
		return p, nil
	}
	start, _ := time.Parse(time.RFC3339Nano, n.Fields["start_at"].(string))
	if !start.Equal(d.Session.StartAt) || !slices.Contains([]string{"running", "trail_running", "treadmill_running"}, d.Session.Sport) {
		return p, nil
	}
	p.Timer = d.Session.TimerS
	for _, l := range d.Laps {
		item := lap{Index: l.LapIndex, Timer: l.TimerS, Intensity: l.Intensity}
		if l.AvgSpeedMPS != nil && *l.AvgSpeedMPS > 0 {
			pace := 1609.344 / *l.AvgSpeedMPS
			item.Pace = &pace
		}
		p.Intervals = append(p.Intervals, item)
	}
	slices.SortFunc(p.Intervals, func(a, b lap) int { return a.Index - b.Index })
	return p, nil
}
func (h *Handler) confirm(w http.ResponseWriter, r *http.Request) {
	token, paces, err := confirmation(r)
	if err != nil {
		failure(w, err)
		return
	}
	if h.Mode != "real" {
		failure(w, realOnly)
		return
	}
	id := r.PathValue("remote_id")
	h.mu.Lock()
	var saved *preview
	for _, p := range h.previews {
		if p.ID == id && p.Token == token {
			saved = &p
			break
		}
	}
	h.mu.Unlock()
	if saved == nil {
		failure(w, reload)
		return
	}
	ok := h.respond(w, r, 200, true, func(ctx context.Context, tx pgx.Tx) (any, error) {
		if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
			return nil, err
		}
		e, err := pending(ctx, tx, id, true)
		if err != nil {
			return nil, err
		}
		if e.Extra || e.Scope != saved.entry.Scope || e.Day != saved.entry.Day {
			return nil, reload
		}
		for k := range paces {
			if !slices.ContainsFunc(saved.Intervals, func(l lap) bool { return l.Index == k }) {
				return nil, issue(422, "treadmill_lap_invalid", "One or more pace entries do not match the reviewed intervals.")
			}
		}
		uid, err := replay.SaveTreadmill(ctx, tx, h.PrivateDir, e.Scope, id, saved.row, saved.archive, paces, h.Now(), h.Refresh)
		if err != nil {
			switch err.Error() {
			case "treadmill_fit_changed":
				return nil, issue(409, err.Error(), reload.msg)
			case "treadmill_import_failed":
				return nil, issue(409, err.Error(), "The reviewed treadmill run could not be saved.")
			}
			return nil, err
		}
		return map[string]uuid.UUID{"activity_id": uid}, nil
	})
	if ok {
		h.mu.Lock()
		h.previews = slices.DeleteFunc(h.previews, func(p preview) bool { return p.Token == token })
		h.mu.Unlock()
	}
}
