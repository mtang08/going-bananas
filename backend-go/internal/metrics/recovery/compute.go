package recovery

import (
	"context"
	"errors"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

const MetricID = "recovery_multisignal_summary"
const MethodVersion = "v1"

type result struct {
	Outcome                       outcome
	SubjectType, SubjectKey, Zone string
	Start, End                    time.Time
	Refs                          map[string]any
}

func compute(ctx context.Context, tx pgx.Tx, key string) (result, error) {
	prefix, daystr, ok := strings.Cut(key, ":")
	day, err := time.Parse(time.DateOnly, daystr)
	if !ok || err != nil || (prefix != "w7" && prefix != "night") {
		return result{}, errors.New("invalid_subject_key")
	}
	zone, err := db.New(tx).CalendarTimezone(ctx)
	if err != nil {
		return result{}, err
	}
	loc, err := time.LoadLocation(zone)
	if err != nil {
		return result{}, err
	}
	first := day
	kind := "night"
	if prefix == "w7" {
		first = day.AddDate(0, 0, -6)
		kind = "window"
	}
	baseline := first.AddDate(0, 0, -60)
	obs, err := loadObservations(ctx, tx, baseline, day)
	if err != nil {
		return result{}, err
	}
	start := time.Date(first.Year(), first.Month(), first.Day(), 0, 0, 0, 0, loc)
	end := time.Date(day.Year(), day.Month(), day.Day()+1, 0, 0, 0, 0, loc)
	checks, err := loadCheckins(ctx, tx, start, end)
	if err != nil {
		return result{}, err
	}
	nights := []outcome{}
	for d := first; !d.After(day); d = d.AddDate(0, 0, 1) {
		nights = append(nights, night(d, obs, checks))
	}
	out := nights[0]
	if prefix == "w7" {
		out = week(nights)
	}
	references := make([]map[string]any, len(obs))
	for i, o := range obs {
		references[i] = o.refs
	}
	checkrefs := make([]map[string]any, len(checks))
	for i, c := range checks {
		checkrefs[i] = c.refs
	}
	return result{Outcome: out, SubjectType: kind, SubjectKey: key, Zone: zone, Start: start.UTC(), End: end.UTC(), Refs: map[string]any{"recovery": references, "checkins": checkrefs, "sources": map[string]any{"window_start": first.Format(time.DateOnly), "as_of": daystr, "baseline_start": baseline.Format(time.DateOnly)}}}, nil
}

func loadObservations(ctx context.Context, tx pgx.Tx, first, last time.Time) ([]observation, error) {
	rows, err := tx.Query(ctx, `SELECT o.source_date,o.metric,o.value,o.source_account_id::text,coalesce(s.source_kind,'unknown'),o.statistic,o.time_semantics,
     coalesce(nullif(s.fields->>'device_generation',''),'unknown'),o.id::text,o.source_revision,s.id::text,s.payload_hash,r.sha256,s.rejected_reason
   FROM recovery_observations o LEFT JOIN source_records s ON s.id=o.source_record_id LEFT JOIN raw_objects r ON r.id=s.raw_object_id
   WHERE o.source_date BETWEEN $1::date AND $2::date AND o.metric IN ('sleep','hrv','resting_hr') ORDER BY s.fetched_at,o.id`, first.Format(time.DateOnly), last.Format(time.DateOnly))
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (observation, error) {
		var o observation
		var account, source, statistic, definition, device, id string
		var rev string
		var sid, payload, sha, rejected *string
		err := row.Scan(&o.day, &o.metric, &o.value, &account, &source, &statistic, &definition, &device, &id, &rev, &sid, &payload, &sha, &rejected)
		if err != nil {
			return o, err
		}
		partition, err := canonicaljson.Metric(map[string]any{"source_account_id": account, "source_kind": source, "statistic": statistic, "definition": definition, "device_generation": device})
		o.partition = string(partition)
		o.resolved = sid != nil && rejected == nil
		o.refs = map[string]any{"id": id, "source_revision": rev, "source_record_id": sid, "payload_hash": payload, "raw_sha256": sha, "partition": o.partition, "value": o.value, "source_date": o.day.Format(time.DateOnly), "source_rejected_reason": rejected}
		return o, err
	})
}
func loadCheckins(ctx context.Context, tx pgx.Tx, start, end time.Time) ([]checkin, error) {
	rows, err := tx.Query(ctx, `SELECT id::text,version,fatigue::float8,illness,observed_at,current_setting('TimeZone') FROM checkins_v2 WHERE observed_at>=$1 AND observed_at<$2 ORDER BY observed_at,id`, start, end)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (checkin, error) {
		var c checkin
		var id, dbZone string
		var version int
		var stamp time.Time
		if err := row.Scan(&id, &version, &c.fatigue, &c.illness, &stamp, &dbZone); err != nil {
			return c, err
		}
		loc, err := time.LoadLocation(dbZone)
		if err != nil {
			return c, err
		}
		stamp = stamp.In(loc)
		layout := "2006-01-02T15:04:05-07:00"
		if stamp.Nanosecond() != 0 {
			layout = "2006-01-02T15:04:05.000000-07:00"
		}
		c.day = stamp.In(start.Location()).Format(time.DateOnly)
		c.refs = map[string]any{"id": id, "version": version, "fatigue": c.fatigue, "illness": c.illness, "observed_at": stamp.Format(layout)}
		return c, nil
	})
}
