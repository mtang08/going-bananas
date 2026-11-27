package planning

import (
	"context"
	"encoding/json"
	"reflect"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
	"github.com/mtang08/going-bananas/backend-go/internal/returnplan"
)

type ProfileData struct {
	Version           int                        `json:"version"`
	Timezone          string                     `json:"timezone"`
	Anchor            *string                    `json:"cycle_anchor"`
	AnchorConfirmed   bool                       `json:"anchor_confirmed"`
	StrengthConfirmed bool                       `json:"strength_days_confirmed"`
	StrengthDays      []int                      `json:"scheduled_strength_days"`
	Schedule          string                     `json:"strength_schedule_mode"`
	WeekStart         *string                    `json:"strength_week_a_start"`
	StrengthA         []int                      `json:"strength_week_a_days"`
	StrengthB         []int                      `json:"strength_week_b_days"`
	MobilityA         []int                      `json:"mobility_week_a_days"`
	MobilityB         []int                      `json:"mobility_week_b_days"`
	MobilityOptional  []int                      `json:"mobility_optional_days"`
	Facts             map[string]json.RawMessage `json:"facts"`
	Preferences       json.RawMessage            `json:"preferences"`
	Unknowns          []string                   `json:"unknowns"`
}

func readForWrite(ctx context.Context, tx pgx.Tx, expected int) (ProfileData, error) {
	var p ProfileData
	raw, err := Profile(ctx, tx)
	if err != nil {
		return p, err
	}
	if err = json.Unmarshal(raw, &p); err != nil {
		return p, err
	}
	if expected != p.Version {
		return p, &Problem{409, "version_conflict", "Profile changed; reload /api/v1/profile"}
	}
	return p, nil
}
func appendProfile(ctx context.Context, tx pgx.Tx, p ProfileData, old ProfileData, now time.Time) error {
	p.Version = old.Version + 1
	raw, err := json.Marshal(p)
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `INSERT INTO profile_versions SELECT (jsonb_populate_record(NULL::profile_versions,$1::jsonb || jsonb_build_object('id',gen_random_uuid(),'effective_at',$2::timestamptz,'recorded_at',clock_timestamp()))).*`, raw, now)
	if err != nil {
		return err
	}
	if old.Version == 0 || old.Timezone != p.Timezone {
		return refresh.Source(ctx, tx, []string{"timezone"}, now, refresh.Runs)
	}
	return nil
}
func SaveProfile(ctx context.Context, tx pgx.Tx, p ProfileData, expected int, now time.Time) (json.RawMessage, error) {
	old, err := readForWrite(ctx, tx, expected)
	if err != nil {
		return nil, err
	}
	if err = appendProfile(ctx, tx, p, old, now); err != nil {
		return nil, err
	}
	return Profile(ctx, tx)
}
func Interruption(ctx context.Context, tx pgx.Tx, expected int, value json.RawMessage, now time.Time) (map[string]any, bool, error) {
	p, err := readForWrite(ctx, tx, expected)
	if err != nil {
		return nil, false, err
	}
	key := "running_interruption"
	old, exists := p.Facts[key]
	var a, b any
	if exists {
		if err = json.Unmarshal(old, &a); err != nil {
			return nil, false, err
		}
	}
	if err = json.Unmarshal(value, &b); err != nil {
		return nil, false, err
	}
	changed := !reflect.DeepEqual(a, b) || (b == nil && exists)
	if changed {
		if b == nil {
			delete(p.Facts, key)
		} else {
			p.Facts[key] = value
		}
		if err = appendProfile(ctx, tx, p, p, now); err != nil {
			return nil, false, err
		}
	}
	loc, err := time.LoadLocation(p.Timezone)
	if err != nil {
		return nil, false, err
	}
	data, err := returnplan.Read(ctx, tx, now.In(loc).Format(time.DateOnly))
	return data, changed, err
}
