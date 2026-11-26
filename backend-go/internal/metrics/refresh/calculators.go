package refresh

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/activitycalc"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/aerobic"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/assessment"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/intensity"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/intervals"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/recovery"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/spacing"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/trainingwindows"
)

func configs() map[string]map[string]any {
	all := trainingwindows.Configs()
	all[aerobic.ID] = aerobic.Config
	all[intervals.ID] = intervals.Config
	all[intensity.ID] = intensity.Config
	all[recovery.MetricID] = recovery.Config
	all["planned_actual_session"] = assessment.Config
	all["hard_session_spacing"] = spacing.Config
	return all
}
func version(metric string) string {
	if metric == intervals.ID || metric == "planned_actual_session" {
		return "v2"
	}
	return "v1"
}

func ensureConfigs(ctx context.Context, tx pgx.Tx) error {
	cfgs := configs()
	for id, cfg := range cfgs {
		hash, err := metrics.Digest(cfg)
		if err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `INSERT INTO metric_configs(id,metric_id,method_version,config,config_hash) VALUES(gen_random_uuid(),$1,$2,$3,$4) ON CONFLICT(metric_id,method_version,config_hash) DO NOTHING`, id, version(id), cfg, hash)
		if err != nil {
			return err
		}
	}
	return nil
}

// Runs refreshes all six registered per-recording calculators.
func Runs(ctx context.Context, tx pgx.Tx, id uuid.UUID, zone string, now time.Time) error {
	if err := trainingwindows.RefreshRun(ctx, tx, id, zone, now); err != nil {
		return err
	}
	var eligibleSport bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS(SELECT FROM activities WHERE id=$1 AND sport IN ('running','trail_running','treadmill_running'))`, id).Scan(&eligibleSport); err != nil {
		return err
	}
	if !eligibleSport {
		_, err := tx.Exec(ctx, `UPDATE metric_results SET is_current=false WHERE subject_key=$1 AND is_current AND ((metric_id IN ('aerobic_efficiency','intensity_time_distribution') AND method_version='v1') OR(metric_id='work_interval_execution' AND method_version='v2'))`, id.String())
		return err
	}
	return activitycalc.Refresh(ctx, tx, id, now)
}

// AssessCompletion refreshes linked activity metrics, then calculates the derived completion status on the caller's transaction.
func AssessCompletion(now time.Time) calendarAssessor {
	return func(ctx context.Context, tx pgx.Tx, id uuid.UUID) error {
		b, err := newBatch(ctx, tx, now, Runs)
		if err != nil {
			return err
		}
		return b.assess([]uuid.UUID{id})
	}
}

type calendarAssessor = func(context.Context, pgx.Tx, uuid.UUID) error

// ReadResult returns a current row for the registered config, or calculates a transient dashboard result using read-only queries.
func ReadResult(ctx context.Context, tx pgx.Tx, metric, key string, now time.Time) (map[string]any, error) {
	cfg, ok := configs()[metric]
	if !ok {
		return nil, fmt.Errorf("unknown metric %q", metric)
	}
	hash, err := metrics.Digest(cfg)
	if err != nil {
		return nil, err
	}
	var raw []byte
	err = tx.QueryRow(ctx, `SELECT to_jsonb(m) FROM metric_results m WHERE metric_id=$1 AND method_version=$2 AND subject_key=$3 AND is_current AND config_hash=$4`, metric, version(metric), key, hash).Scan(&raw)
	if err == nil {
		var row map[string]any
		err = json.Unmarshal(raw, &row)
		return row, err
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return nil, err
	}
	var r *metrics.Result
	if metric == recovery.MetricID {
		r, err = recovery.Calculate(ctx, tx, key)
	} else if metric == "session_rpe_load" && (strings.HasPrefix(key, "strong:") || strings.HasPrefix(key, "manual:")) {
		z, e := db.New(tx).CalendarTimezone(ctx)
		if e != nil {
			return nil, e
		}
		loc, e := time.LoadLocation(z)
		if e != nil {
			return nil, e
		}
		r, err = trainingwindows.CalculateStrength(ctx, tx, key, loc)
	} else {
		id, parseErr := uuid.Parse(key)
		if parseErr != nil {
			return nil, parseErr
		}
		switch metric {
		case intervals.ID:
			r, err = intervals.Calculate(ctx, tx, id)
		case intensity.ID:
			r, err = intensity.Calculate(ctx, tx, id)
		case aerobic.ID:
			r, err = aerobic.Calculate(ctx, tx, id)
		default:
			zone, e := db.New(tx).CalendarTimezone(ctx)
			if e != nil {
				return nil, e
			}
			r, err = trainingwindows.CalculateActivity(ctx, tx, metric, id, zone)
		}
	}
	if err != nil || r == nil {
		return nil, err
	}
	preview, err := metrics.Preview(*r, now)
	if err != nil {
		return nil, err
	}
	raw, err = json.Marshal(preview)
	if err != nil {
		return nil, err
	}
	var row map[string]any
	err = json.Unmarshal(raw, &row)
	return row, err
}
