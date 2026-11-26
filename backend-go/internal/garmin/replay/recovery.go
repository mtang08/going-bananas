package replay

import (
	"context"
	"errors"
	"slices"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
)

type metricDefinition struct{ field, unit, statistic, semantics string }

var recoveryMetrics = map[string]metricDefinition{
	"sleep":      {"sleepTimeSeconds", "s", "main_sleep_duration", "garmin_sleep_calendar_date"},
	"hrv":        {"lastNightAvg", "ms", "last_night_average", "garmin_hrv_calendar_date"},
	"resting_hr": {"restingHeartRate", "bpm", "daily_resting", "garmin_heart_rate_calendar_date"},
}

func recoveryOwner(row garmin.Record) (string, bool) {
	v, present := row["userProfilePK"]
	if !present {
		v = row["userProfilePk"]
	}
	return stringID(v)
}

func recoveryDay(v any) (time.Time, bool) {
	s, ok := v.(string)
	if !ok {
		return time.Time{}, false
	}
	for _, layout := range []string{time.DateOnly, "20060102"} {
		if t, err := time.Parse(layout, s); err == nil && t.Year() > 0 {
			return t, true
		}
	}
	return time.Time{}, false
}

func recoveryJobPage(ctx context.Context, tx pgx.Tx, root, dataset string, records []garmin.Record, at time.Time) (JobPage, error) {
	def, ok := recoveryMetrics[dataset]
	if !ok {
		return JobPage{}, errors.New("unsupported_dataset")
	}
	owner := ""
	for _, r := range records {
		id, known := recoveryOwner(r)
		if !known {
			continue
		}
		if owner != "" && id != owner {
			return JobPage{}, errors.New("mixed_source_account")
		}
		owner = id
	}
	batch := uuid.New()
	if _, err := tx.Exec(ctx, `INSERT INTO import_batches(id,source_kind,status,adapter_version,counters) VALUES($1,'garmin_api','running','garmin-personal-v1','{}')`, batch); err != nil {
		return JobPage{}, err
	}
	counts := Counts{}
	result := JobPage{}
	account := uuid.Nil
	for _, r := range records {
		counts.Seen++
		day, validDay := recoveryDay(r["calendarDate"])
		if validDay {
			result.observe(day)
		}
		if !validDay || owner == "" {
			counts.Rejected++
			continue
		}
		value := r[def.field]
		if value != nil {
			if _, err := nonnegative(value, "invalid_recovery_value"); err != nil {
				counts.Rejected++
				continue
			}
		}
		raw, err := canonicaljson.Coaching(map[string]any(r))
		if err != nil {
			counts.Rejected++
			continue
		}
		if account == uuid.Nil {
			account, err = accountID(ctx, tx, "garmin-owner:"+owner)
			if err != nil {
				return JobPage{}, err
			}
		}
		obj, err := retain(root, "json", raw)
		if err != nil {
			return JobPage{}, err
		}
		rawID, err := obj.persist(ctx, tx)
		if err != nil {
			return JobPage{}, err
		}
		d := day.Format(time.DateOnly)
		identity := dataset + ":" + d + ":" + def.statistic
		fields := map[string]any{"metric": dataset, "source_date": d, "value": value, "unit": def.unit, "statistic": def.statistic, "source_field": def.field}
		var reject *string
		if _, known := recoveryOwner(r); !known {
			code := "missing_recovery_owner"
			reject = &code
		}
		tag, err := tx.Exec(ctx, `INSERT INTO source_records(id,source_account_id,import_batch_id,raw_object_id,source_identity,payload_hash,fetched_at,parser_version,source_kind,fields,rejected_reason)
			VALUES(gen_random_uuid(),$1,$2,$3,$4,$5,$6,'garmin-personal-v1','garmin_api',$7,$8)
			ON CONFLICT(source_account_id,source_identity,payload_hash) DO NOTHING`, account, batch, rawID, identity, obj.Hash, at, fields, reject)
		if err != nil {
			return JobPage{}, err
		}
		counts.NewRevisions += int(tag.RowsAffected())
		if reject != nil {
			counts.Rejected++
			continue
		}
		tag, err = tx.Exec(ctx, `INSERT INTO recovery_observations(id,source_account_id,source_record_id,metric,source_date,time_semantics,value,unit,statistic,source_revision)
			SELECT gen_random_uuid(),source_account_id,id,$3,$4::date,$5,(fields->>'value')::float8,$6,$7,payload_hash FROM source_records
			WHERE source_account_id=$1 AND source_identity=$2 AND rejected_reason IS NULL AND fields->>'value' IS NOT NULL
			ORDER BY source_modified_at DESC NULLS LAST,(source_kind='garmin_api') DESC,CASE WHEN source_kind='garmin_api' THEN fetched_at END DESC NULLS LAST,payload_hash DESC LIMIT 1
			ON CONFLICT(source_account_id,metric,source_date,statistic) DO UPDATE SET source_record_id=EXCLUDED.source_record_id,value=EXCLUDED.value,source_revision=EXCLUDED.source_revision
			WHERE (recovery_observations.source_record_id,recovery_observations.value) IS DISTINCT FROM (EXCLUDED.source_record_id,EXCLUDED.value)`, account, identity, dataset, day, def.semantics, def.unit, def.statistic)
		if err != nil {
			return JobPage{}, err
		}
		if tag.RowsAffected() > 0 {
			counts.Changed++
			result.AffectedDates = append(result.AffectedDates, d)
		}
	}
	if counts.Changed > 0 {
		if _, err := db.New(tx).BumpDataRevision(ctx); err != nil {
			return JobPage{}, err
		}
	}
	slices.Sort(result.AffectedDates)
	result.AffectedDates = slices.Compact(result.AffectedDates)
	result.Counters = counts.providerCounts()
	_, err := tx.Exec(ctx, `UPDATE import_batches SET status='complete',finished_at=$2,counters=$3 WHERE id=$1`, batch, at, result.Counters)
	return result, err
}
