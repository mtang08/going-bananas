package refresh

import (
	"context"
	"fmt"
	"maps"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/recovery"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/spacing"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/trainingwindows"
)

type scope struct {
	dates, recovery map[string]bool
	plans, manual   []uuid.UUID
	strength        []string
	since           string
}

func (b *batch) dateRows(sql string, args ...any) ([]string, error) {
	rows, err := b.tx.Query(b.ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowTo[string])
}

func (b *batch) expand(input []string) (scope, error) {
	s := scope{dates: map[string]bool{}, recovery: map[string]bool{}}
	for _, raw := range input {
		kind, value, _ := strings.Cut(raw, ":")
		var days []string
		var err error
		switch kind {
		case "revision", "timezone":
			if raw != kind {
				return s, fmt.Errorf("invalid scope %q", raw)
			}
			if kind == "timezone" {
				b.broad = true
			}
		case "date", "since", "coverage_date", "recovery_dates":
			for _, d := range strings.Split(value, ",") {
				if _, err = time.Parse(time.DateOnly, d); err != nil {
					return s, err
				}
				switch kind {
				case "recovery_dates":
					s.recovery[d] = true
				case "since":
					if d != value {
						return s, fmt.Errorf("invalid scope %q", raw)
					}
					if s.since == "" || d < s.since {
						s.since = d
					}
				default:
					if d != value {
						return s, fmt.Errorf("invalid scope %q", raw)
					}
					s.dates[d] = true
					if kind == "coverage_date" {
						b.coverage = append(b.coverage, d)
					}
				}
			}
		case "plan", "manual_completion", "activity", "checkin", "strength":
			prefix := ""
			if kind == "strength" {
				prefix, value, _ = strings.Cut(value, ":")
				if prefix != "strong" && prefix != "manual" {
					return s, fmt.Errorf("invalid scope %q", raw)
				}
			}
			id, err := uuid.Parse(value)
			if err != nil {
				return s, err
			}
			switch kind {
			case "plan":
				s.plans = append(s.plans, id)
				days, err = b.dateRows(`SELECT local_date::text FROM calendar_session_revisions WHERE session_uid=$1 ORDER BY calendar_version_number DESC,revision DESC LIMIT 2`, id)
			case "manual_completion":
				s.manual = append(s.manual, id)
			case "activity":
				b.explicit = append(b.explicit, id)
				days, err = b.dateRows(`SELECT (start_at AT TIME ZONE $2)::date::text FROM activities WHERE id=$1`, id, b.zone.String())
			case "checkin":
				days, err = b.dateRows(`SELECT (observed_at AT TIME ZONE $2)::date::text FROM checkins_v2 WHERE id=$1`, id, b.zone.String())
				if err == nil && len(days) > 0 {
					s.recovery[days[0]] = true
					t, err := time.Parse(time.DateOnly, days[0])
					if err != nil {
						return s, err
					}
					days = append(days, t.AddDate(0, 0, -1).Format(time.DateOnly), t.AddDate(0, 0, -2).Format(time.DateOnly))
					linked, err := b.ids(`SELECT activity_id FROM checkins_v2 WHERE id=$1 AND activity_id IS NOT NULL`, id)
					if err != nil {
						return s, err
					}
					b.explicit = append(b.explicit, linked...)
				}
			case "strength":
				s.strength = append(s.strength, prefix+":"+id.String())
				if prefix == "strong" {
					days, err = b.dateRows(`SELECT local_date::text FROM strong_workouts WHERE id=$1`, id)
				} else {
					days, err = b.dateRows(`SELECT date::text FROM manual_sessions WHERE id=$1`, id)
				}
			}
			if err != nil {
				return s, err
			}
		default:
			return s, fmt.Errorf("invalid scope %q", raw)
		}
		if err != nil {
			return s, err
		}
		for _, d := range days {
			s.dates[d] = true
		}
	}
	if b.broad || s.since != "" {
		days, err := b.dateRows(`SELECT d::text FROM(SELECT (start_at AT TIME ZONE $1)::date AS d FROM activities UNION SELECT date FROM manual_sessions UNION SELECT local_date FROM strong_workouts UNION SELECT source_date FROM recovery_observations UNION SELECT local_date FROM calendar_session_revisions) s WHERE $2 OR d>=nullif($3,'')::date`, b.zone.String(), b.broad, s.since)
		if err != nil {
			return s, err
		}
		for _, d := range days {
			s.dates[d] = true
			if b.broad {
				s.recovery[d] = true
			}
		}
	}
	return s, nil
}

func (b *batch) recoveryDates(source map[string]bool) error {
	if len(source) == 0 {
		return nil
	}
	days := slices.Sorted(maps.Keys(source))
	today := b.now.In(b.zone).Format(time.DateOnly)
	keys, err := b.dateRows(`WITH changed AS(SELECT d::date AS d FROM unnest($1::text[]) d),
 existing AS(SELECT subject_key AS k FROM metric_results WHERE metric_id='recovery_multisignal_summary' AND method_version='v1' AND is_current AND subject_type IN('night','window')),
 nights AS(SELECT 'night:'||to_char(d+n,'YYYY-MM-DD') AS k FROM changed CROSS JOIN generate_series(0,60)n WHERE d+n<=$2::text::date
 UNION SELECT k FROM existing JOIN changed ON split_part(k,':',2)::date BETWEEN d AND d+60 WHERE starts_with(k,'night:')),
 summaries AS(SELECT 'w7:'||$2 AS k FROM changed WHERE $2::text::date BETWEEN d AND d+66 UNION SELECT k FROM existing JOIN changed ON split_part(k,':',2)::date BETWEEN d AND d+66 WHERE starts_with(k,'w7:'))
 SELECT k FROM nights UNION SELECT k FROM summaries ORDER BY k`, days, today)
	if err != nil {
		return err
	}
	done := map[string]bool{}
	for _, day := range b.full {
		t, err := time.Parse(time.DateOnly, day)
		if err != nil {
			return err
		}
		done["w7:"+day] = true
		for n := 0; n < 7; n++ {
			done["night:"+t.AddDate(0, 0, -n).Format(time.DateOnly)] = true
		}
	}
	for _, k := range keys {
		if !done[k] {
			if _, err := recovery.Refresh(b.ctx, b.tx, k, b.now); err != nil {
				return err
			}
		}
	}
	return nil
}

// ScopeMetrics applies already-rematched provider, check-in and calendar scopes on the writer's transaction.
func ScopeMetrics(ctx context.Context, tx pgx.Tx, scopes []string, matched []uuid.UUID, now time.Time, includeTrainingToday bool, runs RunMetrics) error {
	b, err := newBatch(ctx, tx, now, runs)
	if err != nil {
		return err
	}
	s, err := b.expand(scopes)
	if err != nil {
		return err
	}
	return b.apply(s, matched, includeTrainingToday)
}
func (b *batch) apply(s scope, matched []uuid.UUID, includeTrainingToday bool) error {
	ctx, tx, now := b.ctx, b.tx, b.now
	other := b.broad || s.since != "" || len(s.dates)+len(s.plans)+len(b.explicit)+len(s.strength) > 0
	if !other && len(s.recovery) == 0 && len(s.manual) > 0 && len(matched) == 0 {
		if err := b.assess(s.manual); err != nil {
			return err
		}
		_, err := spacing.RefreshCompletions(ctx, tx, s.manual, false, now)
		return err
	}
	if !other && len(s.manual) == 0 && len(s.recovery) > 0 {
		if err := b.assess(matched); err != nil {
			return err
		}
		if includeTrainingToday {
			day := b.now.In(b.zone)
			day = time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, b.zone)
			if err := b.windows(day); err != nil {
				return err
			}
			b.full = append(b.full, day.Format(time.DateOnly))
		}
		return b.recoveryDates(s.recovery)
	}
	if !other && len(s.manual)+len(s.recovery)+len(matched) == 0 && !includeTrainingToday {
		return nil
	}
	for _, id := range s.manual {
		days, err := b.dateRows(`SELECT local_date::text FROM calendar_session_revisions WHERE session_uid=$1 ORDER BY calendar_version_number DESC,revision DESC LIMIT 2`, id)
		if err != nil {
			return err
		}
		for _, d := range days {
			s.dates[d] = true
		}
	}
	for _, key := range s.strength {
		linked, err := b.ids(`SELECT session_uid FROM session_completions WHERE 'strong:'||strong_workout_id::text=$1 OR 'manual:'||manual_session_id::text=$1`, key)
		if err != nil {
			return err
		}
		s.plans = append(s.plans, linked...)
		if err := trainingwindows.RefreshStrengthKey(ctx, tx, key, b.zone, now); err != nil {
			return err
		}
	}
	if err := b.related(slices.Sorted(maps.Keys(s.dates)), s.since, append(s.plans, s.manual...), matched); err != nil {
		return err
	}
	if _, err := spacing.RefreshCompletions(ctx, tx, s.manual, len(matched) > 0, now); err != nil {
		return err
	}
	return b.recoveryDates(s.recovery)
}
