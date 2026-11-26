// Package rematch reconciles stored calendar completions in the caller's transaction.
package rematch

import (
	"context"
	_ "embed"
	"encoding/json"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/calendarstructure"
	"github.com/mtang08/going-bananas/backend-go/internal/matching"
)

//go:embed inputs.sql
var readInputs string

// Dates receives athlete-local YYYY-MM-DD dates. The caller holds the global writer lock.
func Dates(ctx context.Context, tx pgx.Tx, days []string, now time.Time) ([]uuid.UUID, error) {
	if len(days) == 0 {
		return nil, nil
	}
	var raw []byte
	if err := tx.QueryRow(ctx, readInputs, days).Scan(&raw); err != nil {
		return nil, err
	}
	var facts struct {
		matching.Input
		Planned []struct {
			matching.Plan
			Structure json.RawMessage
		} `json:"planned"`
	}
	if err := json.Unmarshal(raw, &facts); err != nil {
		return nil, err
	}
	input := facts.Input
	for _, stored := range facts.Planned {
		steps, _ := calendarstructure.Expand(stored.Structure)
		work := slices.ContainsFunc(steps, func(s calendarstructure.Step) bool { return s.Type == "work" })
		stored.Plan.HasWorkSteps = &work
		input.Planned = append(input.Planned, stored.Plan)
	}
	result := matching.PlanMatches(input)
	return persist(ctx, tx, result, input.Completions, now)
}

func persist(ctx context.Context, tx pgx.Tx, result matching.Result, old []matching.Completion, now time.Time) ([]uuid.UUID, error) {
	remove := map[string]bool{}
	for _, uid := range result.DeleteAutoSessionUIDs {
		remove[uid] = true
	}
	extras := map[string]bool{}
	for _, key := range result.DeleteExtraSubjectKeys {
		extras[key] = true
	}
	affected := map[string]bool{}
	existing := map[string]matching.Completion{}
	for _, row := range old {
		if (remove[row.SessionUID] && row.MatchMethod == "auto_same_day") || (extras[row.SubjectKey] && row.Status == "extra") {
			if _, err := tx.Exec(ctx, "DELETE FROM session_completions WHERE session_uid=$1", row.SessionUID); err != nil {
				return nil, err
			}
			affected[row.SessionUID] = true
		} else {
			existing[row.SessionUID] = row
		}
	}
	for _, items := range []struct {
		links  []matching.Link
		status string
	}{{result.Links, "unknown"}, {result.Extras, "extra"}} {
		for _, link := range items.links {
			row, exists := existing[link.SessionUID]
			if exists && (row.Status == "skipped" || row.MatchMethod == "explicit" || row.MatchMethod == "confirmed_move" || (row.MatchMethod == "user_marked" && row.Status != "completed_as_planned") || (row.SubjectKey == link.SubjectKey && row.MatchMethod == link.MatchMethod)) {
				continue
			}
			var activity, strong, manual *string
			prefix, key, typed := strings.Cut(link.SubjectKey, ":")
			switch {
			case !typed:
				activity = &prefix
			case prefix == "manual":
				manual = &key
			case prefix == "strong":
				strong = &key
			}
			_, err := tx.Exec(ctx, `INSERT INTO session_completions(id,session_uid,activity_id,strong_workout_id,manual_session_id,status,match_method,updated_at)
     VALUES(gen_random_uuid(),$1,$2,$3,$4,$5,$6,$7)
     ON CONFLICT(session_uid) DO UPDATE SET activity_id=excluded.activity_id,strong_workout_id=excluded.strong_workout_id,
       manual_session_id=excluded.manual_session_id,status=excluded.status,match_method=excluded.match_method,updated_at=excluded.updated_at,
       version=session_completions.version+1,input_version=session_completions.input_version+1`, link.SessionUID, activity, strong, manual, items.status, link.MatchMethod, now)
			if err != nil {
				return nil, err
			}
			affected[link.SessionUID] = true
		}
	}
	ids := make([]uuid.UUID, 0, len(affected))
	for key := range affected {
		ids = append(ids, uuid.MustParse(key))
	}
	slices.SortFunc(ids, func(a, b uuid.UUID) int { return strings.Compare(a.String(), b.String()) })
	return ids, nil
}
