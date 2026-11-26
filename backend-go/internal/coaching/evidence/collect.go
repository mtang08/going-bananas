package evidence

import (
	"context"
	"crypto/sha256"
	_ "embed"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
)

// The Python metric modules select these active config hashes in code, even
// on an empty database. The Python reference comparison checks this manifest.
//
//go:embed metric_identities.json
var metricIdentities []byte

type Inputs struct {
	Sources                   coaching.SourceVersions `json:"source_versions"`
	ConfirmedStrengthSessions []map[string]any        `json:"confirmed_strength_sessions"`
	SafetyGuard               map[string]any          `json:"safety_guard"`
}

func Collect(ctx context.Context, tx pgx.Tx, operation, asOf string, now time.Time) (coaching.SourceVersions, error) {
	inputs, err := CollectInputs(ctx, tx, operation, asOf, now)
	return inputs.Sources, err
}

func CollectInputs(ctx context.Context, tx pgx.Tx, operation, asOf string, now time.Time) (Inputs, error) {
	day, err := time.Parse(time.DateOnly, asOf)
	if err != nil {
		return Inputs{}, err
	}
	var identities []map[string]string
	if err := json.Unmarshal(metricIdentities, &identities); err != nil {
		return Inputs{}, err
	}
	s := coaching.SourceVersions{"operation": operation, "as_of": asOf, "metric_identities": identities, "profile": nil, "block": nil}
	for _, p := range projections {
		items, err := readRows(ctx, tx, p.query)
		if err != nil {
			return Inputs{}, fmt.Errorf("read %s: %w", p.key, err)
		}
		if !p.optional || len(items) != 0 {
			s[p.key] = items
		}
	}
	var calendar, routine int
	if err := tx.QueryRow(ctx, `select coalesce((select calendar_head_version from app_state where id=1),0),coalesce((select max(version) from strength_routine_slots),0)`).Scan(&calendar, &routine); err != nil {
		return Inputs{}, err
	}
	s["calendar"], s["routine"] = calendar, routine
	block, err := readRows(ctx, tx, `select id,version,status from (
		select distinct on (block_uid) id,version,status,created_at,block_uid from block_versions order by block_uid,version desc
	) b where status in ('active','consolidating') order by created_at desc,version desc,id desc limit 1`)
	if err != nil {
		return Inputs{}, err
	}
	if len(block) != 0 {
		s["block"] = block[0]
	}
	delayed, err := readRows(ctx, tx, `select id,activity_id,opens_at,closes_at,
		case when status='open' and closes_at <= $1 then 'expired' else status end as status
		from prompts where kind='delayed_symptom' and opens_at between $2 and $1 order by id`, now, now.Add(-120*24*time.Hour))
	if err != nil {
		return Inputs{}, err
	}
	s["delayed_response_prompts"] = delayed
	completions, err := completionHashes(ctx, tx)
	if err != nil {
		return Inputs{}, err
	}
	s["completions"] = completions
	profiles, err := readRows(ctx, tx, `select version,timezone,facts,preferences,unknowns,cycle_anchor,anchor_confirmed,
		strength_days_confirmed,scheduled_strength_days,strength_schedule_mode,strength_week_a_start,strength_week_a_days,
		strength_week_b_days,mobility_week_a_days,mobility_week_b_days,mobility_optional_days,
		(effective_at at time zone timezone)::date as effective_day from profile_versions order by version desc limit 1`)
	if err != nil {
		return Inputs{}, err
	}
	var profile row
	if len(profiles) > 0 {
		profile = profiles[0]
		data, err := profileSources(profile)
		if err != nil {
			return Inputs{}, err
		}
		s["profile"] = data
	}
	guard, err := safetyGuard(ctx, tx, profile, now)
	if err != nil {
		return Inputs{}, err
	}
	schedule, err := strengthSchedule(ctx, tx, day, profile)
	if err != nil {
		return Inputs{}, err
	}
	omissions, err := acceptedOmissions(ctx, tx, day, schedule)
	if err != nil {
		return Inputs{}, err
	}
	if len(omissions) != 0 {
		for _, omission := range omissions {
			if omission["strength_slot_id"] == nil || omission["strength_slot_id"] == "" {
				delete(omission, "strength_slot_id")
			}
		}
		s["accepted_strength_omissions"] = omissions
	}
	return Inputs{Sources: s, ConfirmedStrengthSessions: schedule, SafetyGuard: guard}, nil
}

func completionHashes(ctx context.Context, tx pgx.Tx) ([]string, error) {
	rows, err := tx.Query(ctx, `select session_uid,activity_id,strong_workout_id,manual_session_id,match_method,modification_reason,reason_note,input_version from session_completions order by id`)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (string, error) {
		var c metrics.CompletionAssociation
		if err := r.Scan(&c.SessionUID, &c.ActivityID, &c.StrongWorkoutID, &c.ManualSessionID, &c.MatchMethod, &c.ModificationReason, &c.ReasonNote, &c.InputVersion); err != nil {
			return "", err
		}
		return c.Hash()
	})
}

func profileSources(p row) (row, error) {
	recurrence := row{}
	for _, key := range []string{"cycle_anchor", "anchor_confirmed", "scheduled_strength_days", "strength_schedule_mode", "strength_week_a_start", "strength_week_a_days", "strength_week_b_days", "mobility_week_a_days", "mobility_week_b_days", "mobility_optional_days"} {
		recurrence[key] = p[key]
	}
	fields := row{"version": p["version"], "timezone": p["timezone"], "recurrence": recurrence}
	for _, key := range []string{"facts", "preferences", "unknowns"} {
		value := p[key]
		if !boolValue(value) {
			if key == "unknowns" {
				value = []any{}
			} else {
				value = row{}
			}
		}
		b, err := canonicaljson.Coaching(value)
		if err != nil {
			return nil, err
		}
		fields[key+"_hash"] = fmt.Sprintf("%x", sha256.Sum256(b))
	}
	return fields, nil
}

func safetyGuard(ctx context.Context, tx pgx.Tx, p row, now time.Time) (row, error) {
	var gait, illness bool
	var severity *float64
	err := tx.QueryRow(ctx, `with recent as (select id,gait_change,illness from checkins_v2 where observed_at between $1 and $2)
	select exists(select from recent where gait_change='yes'),exists(select from recent where illness='present'),
	(select max(severity)::double precision from symptom_reports where checkin_id in(select id from recent))`, now.Add(-72*time.Hour), now).Scan(&gait, &illness, &severity)
	if err != nil {
		return nil, err
	}
	facts, _ := p["facts"].(map[string]any)
	restricted := boolValue(facts["clinical_restriction_active"])
	for _, key := range []string{"clinical_restriction", "clinician_restriction"} {
		text, _ := facts[key].(string)
		switch strings.ToLower(strings.TrimSpace(text)) {
		case "", "none", "unknown":
		default:
			restricted = true
		}
	}
	var maxSeverity any
	if severity != nil {
		maxSeverity = *severity
	}
	return row{"window_hours": 72, "gait_change_yes": gait, "illness_present": illness, "max_symptom_severity": maxSeverity, "clinical_restriction_active": restricted}, nil
}

func boolValue(value any) bool {
	switch v := value.(type) {
	case nil:
		return false
	case bool:
		return v
	case string:
		return len(v) > 0
	case json.Number:
		n, _ := v.Float64()
		return n != 0
	case []any:
		return len(v) > 0
	case map[string]any:
		return len(v) > 0
	default:
		return true
	}
}
