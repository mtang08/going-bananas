// Package returnplan reads the accepted-calendar preview for a running interruption.
package returnplan

import (
	"context"
	"encoding/json"
	"errors"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/athleteprofile"
)

type object = map[string]any

type episode struct{ Reason, Start, Return, Review string }

func parseEpisode(raw json.RawMessage) (*episode, error) {
	if len(raw) == 0 || string(raw) == "null" {
		return nil, nil
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return nil, err
	}
	e := episode{}
	for key, v := range fields {
		if key == "reason" {
			if err := json.Unmarshal(v, &e.Reason); err != nil {
				return nil, err
			}
			continue
		}
		var dest *string
		switch key {
		case "starts_on":
			dest = &e.Start
		case "return_on":
			dest = &e.Return
		case "review_on":
			dest = &e.Review
		default:
			return nil, errors.New("invalid interruption field")
		}
		if string(v) == "null" {
			continue
		}
		day, err := athleteprofile.FactDate(v)
		if err != nil {
			return nil, err
		}
		*dest = day
	}
	if !slices.Contains([]string{"schedule", "travel", "illness", "other"}, e.Reason) || e.Start == "" || (e.Return == "") == (e.Review == "") || (e.Return != "" && e.Return <= e.Start) || (e.Review != "" && e.Review < e.Start) {
		return nil, errors.New("invalid recorded running interruption")
	}
	return &e, nil
}

func optionalDay(s string) any {
	if s == "" {
		return nil
	}
	return s
}
func (e episode) phase(day string) string {
	switch {
	case day < e.Start:
		return "planned"
	case e.Return != "" && day >= e.Return:
		return "returning"
	case e.Review != "" && day >= e.Review:
		return "review_due"
	default:
		return "paused"
	}
}

type run struct {
	UID                 string
	Day                 string
	Intent              string
	Recipe              *string
	Duration, Distance  *int
	Custom, Placeholder bool
	Brief, Structure    json.RawMessage
}

func (r run) view() object {
	return object{"session_uid": r.UID, "local_date": r.Day, "intent": r.Intent, "recipe_id": r.Recipe, "planned_duration_s": r.Duration, "planned_distance_m": r.Distance}
}

func reviewable(ctx context.Context, tx pgx.Tx, start, end string) ([]run, error) {
	rows, err := tx.Query(ctx, `WITH head AS (SELECT calendar_head_version AS n FROM app_state WHERE id=1),
		latest AS (SELECT DISTINCT ON (session_uid) r.* FROM calendar_session_revisions r,head
		WHERE head.n>0 AND calendar_version_number<=head.n ORDER BY session_uid,calendar_version_number DESC,revision DESC)
		SELECT session_uid::text,local_date::text,intent,recipe_id,planned_duration_s,planned_distance_m,
		custom,placeholder,brief,structure FROM latest r WHERE NOT deleted AND NOT locked AND kind='run' AND local_date BETWEEN $1::date AND $2::date
		AND NOT EXISTS (SELECT FROM session_completions c WHERE c.session_uid=r.session_uid AND (status<>'unknown'
		OR activity_id IS NOT NULL OR strong_workout_id IS NOT NULL OR manual_session_id IS NOT NULL))
		ORDER BY local_date,slot,session_uid`, start, end)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowToStructByPos[run])
}

func affected(rows []run, ep episode, day string) ([]object, int) {
	past, future := []run{}, []run{}
	for _, r := range rows {
		if r.Day < ep.Start || (ep.Return != "" && r.Day >= ep.Return) {
			continue
		}
		if r.Day < day {
			past = append(past, r)
		} else {
			future = append(future, r)
		}
	}
	count := len(past) + len(future)
	future = future[:min(8, len(future))]
	past = past[max(0, len(past)-(8-len(future))):]
	out := []object{}
	for _, r := range append(past, future...) {
		out = append(out, r.view())
	}
	return out, count - len(out)
}

func recorded(ctx context.Context, tx pgx.Tx, ep episode, day, zone string) (object, error) {
	if ep.Return == "" || day < ep.Return {
		return nil, nil
	}
	var id, date string
	err := tx.QueryRow(ctx, `SELECT a.id::text,((a.start_at AT TIME ZONE $3)::date)::text FROM activities a
		WHERE a.resolution_state='resolved' AND a.sport IN ('running','trail_running','treadmill_running')
		AND a.start_at >= (($1::date-1)::timestamp AT TIME ZONE $3)
		AND (a.start_at AT TIME ZONE $3)::date >= $1::date
		AND ($2::date >= date '9999-12-30' OR (a.start_at AT TIME ZONE $3)::date <= $2::date)
		AND (SELECT excluded FROM activity_annotations WHERE activity_id=a.id ORDER BY version DESC LIMIT 1) IS NOT TRUE
		ORDER BY a.start_at,a.id LIMIT 1`, ep.Return, day, zone).Scan(&id, &date)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return object{"activity_id": id, "local_date": date}, nil
}

func Read(ctx context.Context, tx pgx.Tx, asOf string) (map[string]any, error) {
	if _, err := time.Parse(time.DateOnly, asOf); err != nil {
		return nil, err
	}
	var version int
	var raw json.RawMessage
	var zone string
	err := tx.QueryRow(ctx, `SELECT coalesce(p.version,0),p.facts->'running_interruption',coalesce(nullif(p.timezone,''),'America/New_York')
		FROM (VALUES(1)) seed(n) LEFT JOIN (SELECT version,facts,timezone FROM profile_versions ORDER BY version DESC LIMIT 1) p ON true`).Scan(&version, &raw, &zone)
	if err != nil {
		return nil, err
	}
	view := object{"today": asOf, "profile_version": version, "interruption": nil, "phase": nil, "affected_runs": []object{}, "affected_runs_omitted": 0, "first_run": nil, "recorded_return": nil, "review_reason": nil}
	ep, err := parseEpisode(raw)
	if err != nil || ep == nil {
		return view, err
	}
	view["interruption"] = object{"starts_on": ep.Start, "reason": ep.Reason, "return_on": optionalDay(ep.Return), "review_on": optionalDay(ep.Review)}
	view["phase"] = ep.phase(asOf)
	start := max(asOf, ep.Start, ep.Return)
	date, _ := time.Parse(time.DateOnly, start)
	end := "9999-12-31"
	if d := date.AddDate(0, 0, 27); d.Year() <= 9999 {
		end = d.Format(time.DateOnly)
	}
	rows, err := reviewable(ctx, tx, ep.Start, end)
	if err != nil {
		return nil, err
	}
	view["affected_runs"], view["affected_runs_omitted"] = affected(rows, *ep, asOf)
	actual, err := recorded(ctx, tx, *ep, asOf, zone)
	if err != nil {
		return nil, err
	}
	if actual != nil {
		view["recorded_return"] = actual
		view["review_reason"] = "Review your response to the recorded return run and end the interruption when appropriate."
		return view, nil
	}
	if ep.Return == "" {
		view["review_reason"] = "Confirm the first available day before reviewing a return run. The review date keeps the pause in place."
		return view, nil
	}
	profile, err := athleteprofile.LoadProfile(ctx, tx, asOf)
	if err != nil {
		return nil, err
	}
	if profile.ClinicalRestriction != nil {
		view["review_reason"] = "Review the existing running restriction before choosing a return run."
		return view, nil
	}
	trips, err := confirmedTrips(ctx, tx, start, end)
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	notes := []string{}
	for _, r := range rows {
		if r.Day < start {
			continue
		}
		block := blocker(r, profile.RunningRestriction, trips)
		if block == "" {
			view["first_run"] = r.view()
			break
		}
		if !seen[block] {
			seen[block] = true
			notes = append(notes, strings.ReplaceAll(block, "{day}", r.Day))
		}
	}
	if len(notes) > 0 {
		view["review_reason"] = strings.Join(notes, " ")
	} else if view["first_run"] == nil {
		view["review_reason"] = "There are no uncompleted, unlocked accepted runs to review in the next four weeks."
	}
	return view, nil
}
