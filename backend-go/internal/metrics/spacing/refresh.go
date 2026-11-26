package spacing

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
)

var config = object{"quality_recipes": qualityRecipes, "long_recipe": "REC002", "lower_body_cost": []string{"moderate", "high"}, "range_rule": "interval_subtraction.v1"}

func location(ctx context.Context, tx pgx.Tx) (*time.Location, int, error) {
	var name string
	var head int
	err := tx.QueryRow(ctx, `SELECT coalesce((SELECT timezone FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York'),coalesce((SELECT calendar_head_version FROM app_state WHERE id=1),0)`).Scan(&name, &head)
	if err != nil {
		return nil, 0, err
	}
	zone, err := time.LoadLocation(name)
	return zone, head, err
}

func persist(ctx context.Context, tx pgx.Tx, in inputs, days []string, now time.Time) error {
	cfg, err := metrics.Digest(config)
	if err != nil {
		return err
	}
	dep, err := metrics.Digest(object{"source_refs": in.refs, "config_hash": cfg, "anchor_set_hash": nil, "timezone": in.zone.String(), "calculator_dependency_hash": ""})
	if err != nil {
		return err
	}
	raw, err := canonicaljson.Metric(in.refs)
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `INSERT INTO metric_configs(id,metric_id,method_version,config,config_hash) VALUES(gen_random_uuid(),'hard_session_spacing','v1',$1,$2) ON CONFLICT(metric_id,method_version,config_hash) DO NOTHING`, config, cfg)
	if err != nil {
		return err
	}
	for _, day := range days {
		t, err := time.ParseInLocation(time.DateOnly, day, in.zone)
		if err != nil {
			return err
		}
		key := "w14:" + day
		_, err = tx.Exec(ctx, `UPDATE metric_results SET is_current=false WHERE metric_id='hard_session_spacing' AND method_version='v1' AND subject_key=$1 AND is_current AND (config_hash<>$2 OR coalesce(anchor_set_hash,'')<>'' OR dependency_hash<>$3)`, key, cfg, dep)
		if err != nil {
			return err
		}
		tag, err := tx.Exec(ctx, `UPDATE metric_results SET is_current=true WHERE metric_id='hard_session_spacing' AND method_version='v1' AND subject_key=$1 AND config_hash=$2 AND coalesce(anchor_set_hash,'')='' AND dependency_hash=$3`, key, cfg, dep)
		if err != nil {
			return err
		}
		if tag.RowsAffected() > 0 {
			continue
		}
		_, err = tx.Exec(ctx, `INSERT INTO metric_results(id,metric_id,method_version,subject_type,subject_key,window_label,window_start,window_end,status,value,reason_codes,quality_flags,source_refs,config_hash,calculated_at,dependency_hash,timezone,is_current)
 VALUES(gen_random_uuid(),'hard_session_spacing','v1','window',$1,$1,$2,$3,'available',$4,'{}','{}',$5::jsonb,$6,$7,$8,$9,true)`, key, t.AddDate(0, 0, -7), t.AddDate(0, 0, 7), outcome(in.entries, t), raw, cfg, now, dep, in.zone.String())
		if err != nil {
			return err
		}
	}
	return nil
}

// RefreshDates calculates hard-session spacing for local ISO date keys on the caller's transaction.
func RefreshDates(ctx context.Context, tx pgx.Tx, days []string, now time.Time) error {
	if len(days) == 0 {
		return nil
	}
	zone, head, err := location(ctx, tx)
	if err != nil {
		return err
	}
	plans, err := readPlans(ctx, tx, head)
	if err != nil {
		return err
	}
	in, err := loadInputs(ctx, tx, zone, head, plans)
	if err != nil {
		return err
	}
	return persist(ctx, tx, in, days, now)
}

// RefreshCompletions recalculates existing spacing windows and local today when a hard plan or association changes.
func RefreshCompletions(ctx context.Context, tx pgx.Tx, uids []uuid.UUID, associationsChanged bool, now time.Time) ([]string, error) {
	if len(uids) == 0 {
		return nil, nil
	}
	zone, head, err := location(ctx, tx)
	if err != nil {
		return nil, err
	}
	plans, err := readPlans(ctx, tx, head)
	if err != nil {
		return nil, err
	}
	if !associationsChanged && !slices.ContainsFunc(plans, func(p plan) bool { return len(p.classes) > 0 && slices.Contains(uids, p.uid) }) {
		return nil, nil
	}
	rows, err := tx.Query(ctx, `SELECT subject_key FROM metric_results WHERE is_current AND metric_id='hard_session_spacing' AND method_version='v1' AND subject_type='window'`)
	if err != nil {
		return nil, err
	}
	keys, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, err
	}
	days := []string{now.In(zone).Format(time.DateOnly)}
	for _, key := range keys {
		day, ok := strings.CutPrefix(key, "w14:")
		if !ok {
			return nil, fmt.Errorf("invalid spacing subject %q", key)
		}
		days = append(days, day)
	}
	slices.Sort(days)
	days = slices.Compact(days)
	in, err := loadInputs(ctx, tx, zone, head, plans)
	if err != nil {
		return nil, err
	}
	if err := persist(ctx, tx, in, days, now); err != nil {
		return nil, err
	}
	return days, nil
}
