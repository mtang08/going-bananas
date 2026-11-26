// Package exceptions evaluates observations from the caller's PostgreSQL transaction.
package exceptions

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/athletefacts"
	"github.com/mtang08/going-bananas/backend-go/internal/blockbenchmark"
)

//go:embed inputs.sql
var observationsSQL string

func LoadInputs(ctx context.Context, tx pgx.Tx, now time.Time) (DetectionInputs, error) {
	in := DetectionInputs{Now: now.UTC()}
	err := tx.QueryRow(ctx, observationsSQL, now).Scan(&in.Today, &in.TZ, &in.Checkins, &in.Runs, &in.Sessions,
		&in.PlannedActual, &in.RecoveryAdverseDates, &in.Events)
	if err != nil {
		return DetectionInputs{}, err
	}
	for i := range in.Checkins {
		c := &in.Checkins[i]
		c.ObservedAt = c.ObservedAt.UTC()
		c.RecordedAt = c.RecordedAt.UTC()
	}
	for i := range in.Runs {
		r := &in.Runs[i]
		r.StartAt = r.StartAt.UTC()
		utcInstant(r.EndAt)
		utcInstant(r.RPEAt)
	}
	for i := range in.Sessions {
		s := &in.Sessions[i]
		s.PlannedAt = s.PlannedAt.UTC()
		utcInstant(s.CompletionUpdatedAt)
		s.SessionClass, s.ExpectedRPE = sessionEffort(*s)
	}
	for i := range in.Events {
		utcInstant(in.Events[i].RunEndAt)
	}
	in.BlockBenchmark, err = readBenchmark(ctx, tx, in.Today)
	if err != nil {
		return DetectionInputs{}, err
	}
	in.ClinicianRestriction, in.ClinicianRestrictionAt, err = restrictionHistory(ctx, tx)
	return in, err
}

func utcInstant(t *time.Time) {
	if t != nil {
		*t = t.UTC()
	}
}

var recipes = map[string]string{"REC001": "easy", "REC002": "long", "REC003": "quality", "REC004": "quality", "REC005": "quality", "REC006": "quality", "REC007": "easy", "REC008": "quality", "REC009": "benchmark", "REC010": "cross"}

func sessionEffort(s SessionFact) (string, *[]float64) {
	class := "unknown"
	if slices.Contains([]string{"cross", "strength", "mobility", "rehab", "rest"}, s.Kind) {
		class = s.Kind
	}
	if s.Kind == "run" {
		if s.RecipeID != nil {
			if c, ok := recipes[*s.RecipeID]; ok {
				class = c
			}
		} else {
			class = intentClass(s.Intent)
		}
	}
	bounds := map[string][]float64{"easy": {2, 4}, "long": {3, 5}, "quality": {5, 8}}[class]
	if s.RecipeID != nil {
		switch *s.RecipeID {
		case "REC001", "REC007":
			bounds = []float64{2, 4}
		case "REC002":
			bounds = []float64{3, 5}
		case "REC003", "REC004", "REC006", "REC008":
			bounds = []float64{5, 7}
		case "REC005":
			bounds = []float64{6, 8}
		default:
			bounds = nil
		}
	}
	if bounds == nil {
		return class, nil
	}
	return class, &bounds
}

func intentClass(intent string) string {
	intent = strings.ToLower(intent)
	for _, rule := range []struct {
		class string
		terms []string
	}{
		{"benchmark", []string{"race", "benchmark", "time trial"}}, {"long", []string{"long"}},
		{"quality", []string{"interval", "tempo", "threshold", "quality", "hill", "vo2", "fartlek"}},
		{"easy", []string{"easy", "recovery", "shakeout"}},
	} {
		for _, term := range rule.terms {
			if strings.Contains(intent, term) {
				return rule.class
			}
		}
	}
	return "unknown"
}

func restrictionHistory(ctx context.Context, tx pgx.Tx) (*string, *time.Time, error) {
	rows, err := tx.Query(ctx, `SELECT CASE WHEN jsonb_typeof(facts->'clinical_restriction')='string' THEN facts->>'clinical_restriction' END,
        CASE WHEN jsonb_typeof(facts->'clinician_restriction')='string' THEN facts->>'clinician_restriction' END,
        facts->'clinical_restriction_active',recorded_at FROM profile_versions ORDER BY version DESC`)
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()
	var restriction *string
	var since *time.Time
	for rows.Next() {
		var current, legacy *string
		var flag json.RawMessage
		var at time.Time
		if err := rows.Scan(&current, &legacy, &flag, &at); err != nil {
			return nil, nil, err
		}
		value := athletefacts.ClinicalRestriction(current, legacy, flag)
		if value == nil || (restriction != nil && *restriction != *value) {
			break
		}
		at = at.UTC()
		restriction, since = value, &at
	}
	return restriction, since, rows.Err()
}

func readBenchmark(ctx context.Context, tx pgx.Tx, today string) (*BlockBenchmarkFact, error) {
	var b BlockBenchmarkFact
	err := tx.QueryRow(ctx, `WITH `+blockbenchmark.Selection+`
        SELECT s.block_uid::text,s.version,s.created_at,s.benchmark->>'planned_date',s.review_date::text,s.kind,
        s.event_id::text,CASE WHEN s.kind IS NULL THEN 'not_set' WHEN m.id IS NOT NULL THEN 'completed'
            WHEN $1::date<=s.review_date+2 THEN 'pending' ELSE 'missed' END,
        m.id::text,((m.start_at AT TIME ZONE zone.name)::date)::text,coalesce(m.end_at,m.start_at),
        s.benchmark->>'protocol',m.method,round(m.distance_m)::bigint,coalesce(m.result_override,round(m.timer_s)::bigint),
        coalesce((SELECT rpe FROM session_rpe WHERE activity_id=m.id AND source IN ('manual','garmin_fit')
            ORDER BY (source='manual') DESC,collected_at DESC,id DESC LIMIT 1),m.workout_rpe)
        FROM spec s CROSS JOIN zone LEFT JOIN matched m ON true`, today).Scan(&b.BlockUID, &b.Version, &b.VersionCreatedAt, &b.PlannedDate,
		&b.ReviewDate, &b.Kind, &b.EventID, &b.Status, &b.ActivityID, &b.LocalDate, &b.EvidenceAt, &b.Protocol, &b.MatchMethod,
		&b.DistanceM, &b.ResultS, &b.RPE)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	b.VersionCreatedAt = b.VersionCreatedAt.UTC()
	utcInstant(b.EvidenceAt)
	return &b, nil
}
