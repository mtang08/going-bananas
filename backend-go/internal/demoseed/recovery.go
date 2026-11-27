package demoseed

import (
	"context"
	"crypto/sha256"
	"fmt"
	"path/filepath"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/rawobject"
)

type recoverySample struct {
	metric, unit, statistic, semantics string
	value                              int
}

func seedRecovery(ctx context.Context, tx pgx.Tx, root string, account uuid.UUID, today, now time.Time) error {
	for ago := 1; ago <= 42; ago++ {
		if ago == 4 || ago == 6 {
			continue
		}
		day := today.AddDate(0, 0, -ago).Format(time.DateOnly)
		for _, s := range []recoverySample{
			{"sleep", "s", "main_sleep_duration", "garmin_sleep_calendar_date", 25200 + (ago%3)*300},
			{"hrv", "ms", "last_night_average", "garmin_hrv_calendar_date", 60 + ago%3},
			{"resting_hr", "bpm", "daily_resting", "garmin_heart_rate_calendar_date", 52 + ago%2},
		} {
			if err := seedSample(ctx, tx, root, account, day, s, now); err != nil {
				return err
			}
		}
	}
	_, err := tx.Exec(ctx, `INSERT INTO coverage_intervals(id,dataset,start_date,end_date,observed_start,observed_end,status,completed_at,fully_enumerated)
SELECT gen_random_uuid(),dataset,$1::text::date,$2::text::date,$1::text::date,$2::text::date,'complete',$3,true
FROM unnest(ARRAY['activities','sleep','hrv','resting_hr']) AS metrics(dataset)
WHERE NOT EXISTS(SELECT 1 FROM coverage_intervals c WHERE c.dataset=metrics.dataset AND c.start_date=$1::text::date AND c.end_date=$2::text::date)`, today.AddDate(0, 0, -42).Format(time.DateOnly), today.AddDate(0, 0, -1).Format(time.DateOnly), now)
	return err
}
func seedSample(ctx context.Context, tx pgx.Tx, root string, account uuid.UUID, day string, s recoverySample, now time.Time) error {
	var exists bool
	err := tx.QueryRow(ctx, `SELECT EXISTS(SELECT FROM recovery_observations WHERE source_account_id=$1 AND metric=$2 AND source_date=$3::text::date AND statistic=$4)`, account, s.metric, day, s.statistic).Scan(&exists)
	if err != nil || exists {
		return err
	}
	// Python's fixture uses sorted keys and the default json.dumps separators.
	body := []byte(fmt.Sprintf(`{"date": %q, "metric": %q, "value": %d}`, day, s.metric, s.value))
	hash := fmt.Sprintf("%x", sha256.Sum256(body))
	path := filepath.Join("raw", hash[:2], hash+".json")
	if err := rawobject.Write(root, path, body); err != nil {
		return err
	}
	id := uuid.New()
	_, err = tx.Exec(ctx, `WITH inserted AS (
 INSERT INTO raw_objects(id,sha256,relative_path,byte_size,media_type) VALUES(gen_random_uuid(),$1,$2,$3,'application/json')
 ON CONFLICT(sha256) DO NOTHING RETURNING id
), raw AS (SELECT id FROM inserted UNION ALL SELECT id FROM raw_objects WHERE sha256=$1 LIMIT 1)
INSERT INTO source_records(id,source_account_id,raw_object_id,source_identity,payload_hash,fetched_at,parser_version,source_kind,fields)
SELECT $4,$5,raw.id,$6,$1,$7,'demo-seed-v1','demo_fixture',$8 FROM raw`, hash, path, len(body), id, account, "demo-recovery:"+day+":"+s.metric, now, map[string]any{"metric": s.metric, "source_date": day, "value": s.value})
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `INSERT INTO recovery_observations(id,source_account_id,source_record_id,metric,source_date,time_semantics,value,unit,statistic,source_revision)
VALUES(gen_random_uuid(),$1,$2,$3,$4::text::date,$5,$6,$7,$8,$9)`, account, id, s.metric, day, s.semantics, s.value, s.unit, s.statistic, hash)
	return err
}
