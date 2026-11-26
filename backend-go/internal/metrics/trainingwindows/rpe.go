package trainingwindows

import (
	"context"
	"errors"
	"fmt"
	"math"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
)

var rpeConfig = object{"rpe_precedence": []string{"manual", "garmin_fit"}, "rpe_range": []int{0, 10}, "duration_fields": object{"run": "activities.timer_s", "strong": "strong_workouts.duration_s", "manual": "manual_sessions.duration_s"}, "load_formula": "rpe_x_duration_min", "window_days": []int{7, 14, 28, 56, 84}, "strength_sources": []string{"strong", "manual"}}

type rpeFact struct {
	key, day, kind       string
	excluded             bool
	duration, rpe, other *float64
	source               string
	delay                *int
	refs                 object
	start, end           *time.Time
}

func finite(f *float64) bool { return f != nil && !math.IsNaN(*f) && !math.IsInf(*f, 0) }

func readRPE(ctx context.Context, tx pgx.Tx, id uuid.UUID, field string, f *rpeFact) error {
	rows, err := tx.Query(ctx, `SELECT id,source,rpe::float8,collection_delay_s,to_char(collected_at,'YYYY-MM-DD"T"HH24:MI:SS')||CASE WHEN extract(microseconds FROM collected_at)::integer%1000000<>0 THEN to_char(collected_at,'.US') ELSE '' END||to_char(collected_at,'TZH:TZM') FROM session_rpe WHERE `+field+`=$1 ORDER BY source,id`, id)
	if err != nil {
		return err
	}
	defer rows.Close()
	ids := []uuid.UUID{}
	refs := []object{}
	for rows.Next() {
		var rowID uuid.UUID
		var source, at string
		var value float64
		var delay *int
		if err := rows.Scan(&rowID, &source, &value, &delay, &at); err != nil {
			return err
		}
		ids = append(ids, rowID)
		refs = append(refs, object{"id": rowID, "source": source, "rpe": value, "collection_delay_s": delay, "collected_at": at})
		if source == "manual" {
			if f.source == "garmin_fit" {
				f.other = f.rpe
			}
			f.rpe = &value
			f.source = source
			f.delay = delay
		} else if source == "garmin_fit" && f.kind == "run" {
			f.rpe = &value
			f.source = source
			f.delay = delay
		}
	}
	f.refs["session_rpe_ids"], f.refs["session_rpe"] = ids, refs
	return rows.Err()
}

func rpeRuns(ctx context.Context, tx pgx.Tx, runs []*metrics.Run) ([]rpeFact, error) {
	facts := make([]rpeFact, 0, len(runs))
	for _, r := range runs {
		f := rpeFact{key: r.ID.String(), kind: "run", day: r.Day, duration: r.Timer, start: &r.Start, end: r.End, refs: object{"activity": object{"id": r.ID, "source_revision": r.SourceRevision, "source_refs": r.Refs}, "fit": r.FIT, "plan": nil, "completion_association_hash": nil}}
		if err := readRPE(ctx, tx, r.ID, "activity_id", &f); err != nil {
			return nil, err
		}
		facts = append(facts, f)
	}
	return facts, nil
}

func rpeStrength(ctx context.Context, tx pgx.Tx, start, end time.Time, includeUnresolved bool) ([]rpeFact, error) {
	rows, err := tx.Query(ctx, `SELECT w.id,w.local_date::text,w.local_start,w.duration_s,w.payload_hash,w.source_record_id,s.payload_hash,s.parser_version,w.raw_object_id,r.sha256,w.resolution_state
 FROM strong_workouts w LEFT JOIN source_records s ON s.id=w.source_record_id LEFT JOIN raw_objects r ON r.id=w.raw_object_id WHERE (w.resolution_state='resolved' OR $3)
 AND w.local_date>=$1::text::date AND w.local_date<$2::text::date ORDER BY w.local_date,w.id`, start.Format(time.DateOnly), end.Format(time.DateOnly), includeUnresolved)
	if err != nil {
		return nil, err
	}
	facts, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (rpeFact, error) {
		var f rpeFact
		var id, source, raw uuid.UUID
		var stamp, payload, state string
		var sHash, parser, rHash *string
		err := row.Scan(&id, &f.day, &stamp, &f.duration, &payload, &source, &sHash, &parser, &raw, &rHash, &state)
		if err != nil {
			return f, err
		}
		f.excluded = state != "resolved"
		f.key = "strong:" + id.String()
		f.kind = "strength"
		f.refs = object{"strong_workout_id": id, "payload_hash": payload, "source_record_id": source, "source_payload_hash": sHash, "source_parser_version": parser, "raw_object_id": raw, "raw_sha256": rHash}
		if f.excluded {
			f.refs["excluded"] = true
		}
		for _, layout := range []string{"2006-01-02 15:04:05", "2006-01-02T15:04:05"} {
			t, err := time.ParseInLocation(layout, stamp, start.Location())
			if err == nil {
				f.start = &t
				break
			}
		}
		if f.start == nil {
			return f, fmt.Errorf("invalid Strong timestamp")
		}
		if f.duration != nil {
			t := f.start.Add(time.Duration(math.RoundToEven(*f.duration*1e6)) * time.Microsecond)
			f.end = &t
		}
		return f, nil
	})
	if err != nil {
		return nil, err
	}
	rows, err = tx.Query(ctx, `SELECT id,date::text,version,CASE WHEN time IS NOT NULL THEN to_char(time,'HH24:MI:SS')||CASE WHEN extract(microseconds FROM time)::integer%1000000<>0 THEN to_char(time,'.US') ELSE '' END END,duration_s
 FROM manual_sessions WHERE kind='strength' AND linked_activity_id IS NULL AND date>=$1::text::date AND date<$2::text::date ORDER BY date,id`, start.Format(time.DateOnly), end.Format(time.DateOnly))
	if err != nil {
		return nil, err
	}
	manual, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (rpeFact, error) {
		var f rpeFact
		var id uuid.UUID
		var version int
		var clock *string
		if err := row.Scan(&id, &f.day, &version, &clock, &f.duration); err != nil {
			return f, err
		}
		f.key = "manual:" + id.String()
		f.kind = "strength"
		hash, err := metrics.Digest(object{"date": f.day, "time": clock, "duration_s": f.duration, "kind": f.kind, "version": version, "linked_activity_id": nil})
		if err != nil {
			return f, err
		}
		f.refs = object{"manual_session_id": id, "version": version, "source_revision": hash}
		if clock != nil {
			t, err := time.ParseInLocation("2006-01-02T15:04:05", f.day+"T"+*clock, start.Location())
			if err != nil {
				return f, err
			}
			f.start = &t
			if f.duration != nil {
				e := t.Add(time.Duration(math.RoundToEven(*f.duration*1e6)) * time.Microsecond)
				f.end = &e
			}
		} else {
			t, err := time.ParseInLocation(time.DateOnly, f.day, start.Location())
			if err != nil {
				return f, err
			}
			f.start = &t
			e := t.AddDate(0, 0, 1)
			f.end = &e
		}
		return f, nil
	})
	if err != nil {
		return nil, err
	}
	strongN := len(facts)
	facts = append(facts, manual...)
	for i := range facts {
		field := "strong_workout_id"
		if i >= strongN {
			field = "manual_session_id"
		}
		if err := readRPE(ctx, tx, uuid.MustParse(facts[i].key[7:]), field, &facts[i]); err != nil {
			return nil, err
		}
	}
	return facts, nil
}

func rpeWindow(facts []rpeFact, coverage bool) (object, string, string, []string, []string) {
	total, known, load := 0.0, 0.0, 0.0
	rpeCount, loads, durations := 0, 0, 0
	strong := map[string]bool{}
	overlap := false
	for _, f := range facts {
		if finite(f.duration) && *f.duration >= 0 {
			durations++
			total += *f.duration
		}
		if finite(f.rpe) && *f.rpe >= 0 && *f.rpe <= 10 {
			rpeCount++
			if finite(f.duration) && *f.duration >= 0 {
				loads++
				known += *f.duration
				load += *f.duration * *f.rpe / 60
			}
		}
		if len(f.key) > 7 {
			switch f.key[:7] {
			case "strong:":
				strong[f.day] = true
			case "manual:":
				overlap = overlap || strong[f.day]
			}
		}
	}
	n := len(facts)
	v := object{"load_au": nil, "sessions_total": n, "sessions_with_rpe": rpeCount, "sessions_without_load": n - loads, "sessions_missing_duration": n - durations, "duration_total_s": nil, "duration_with_rpe_s": nil, "coverage_duration": nil, "coverage_sessions": nil}
	if loads > 0 || n == 0 && coverage {
		v["load_au"] = round(load, 1)
	}
	if durations > 0 || n == 0 && coverage {
		v["duration_total_s"] = round(total, 1)
		v["duration_with_rpe_s"] = round(known, 1)
	}
	q := ""
	if n > 0 {
		v["coverage_sessions"] = round(float64(rpeCount)/float64(n), 3)
		q = quality(float64(rpeCount), float64(n))
	}
	if total > 0 && durations == n {
		v["coverage_duration"] = round(known/total, 3)
		q = quality(known, total)
	}
	reasons, flags := []string{}, []string{}
	if loads < n {
		reasons = append(reasons, "SESSIONS_WITHOUT_LOAD")
		if q == "good" {
			q = "limited"
		}
	}
	if !coverage {
		reasons = append(reasons, "SYNC_COVERAGE_INCOMPLETE")
	}
	if overlap {
		flags = append(flags, "STRENGTH_SOURCE_OVERLAP")
	}
	status := "available"
	if len(reasons) > 0 {
		status = "missing"
		if n > 0 {
			status = "partial"
		}
	}
	return v, status, q, reasons, flags
}

func RefreshRPE(ctx context.Context, tx pgx.Tx, asOf, now time.Time) error {
	end := dayStart(asOf).AddDate(0, 0, 1)
	earliest := end.AddDate(0, 0, -84)
	runs, err := runsBetween(ctx, tx, earliest, end)
	if err != nil {
		return err
	}
	runFacts, err := rpeRuns(ctx, tx, runs)
	if err != nil {
		return err
	}
	strength, err := rpeStrength(ctx, tx, earliest, end, false)
	if err != nil {
		return err
	}
	for _, width := range widths["session_rpe_load"] {
		start := end.AddDate(0, 0, -width)
		for _, kind := range []string{"run", "strength"} {
			complete := false
			all := strength
			if kind == "run" {
				all = runFacts
				complete, err = covered(ctx, tx, start, end)
				if err != nil {
					return err
				}
			}
			selected := []rpeFact{}
			keys := []string{}
			sources := []object{}
			for _, f := range all {
				if f.day < start.Format(time.DateOnly) {
					continue
				}
				selected = append(selected, f)
				keys = append(keys, f.key)
				sources = append(sources, f.refs)
			}
			refs := object{"sources": sources, "coverage_complete": complete}
			hash, err := metrics.Digest(refs)
			if err != nil {
				return err
			}
			refs["input_hash"] = hash
			refs["subject_keys"] = keys
			value, status, q, reasons, flags := rpeWindow(selected, complete)
			key := fmt.Sprintf("w%d:%s:%s", width, asOf.Format(time.DateOnly), kind)
			_, err = metrics.StoreResult(ctx, tx, metrics.Result{MetricID: "session_rpe_load", MethodVersion: "v1", SubjectType: "window", SubjectKey: key, WindowLabel: key, WindowStart: &start, WindowEnd: &end, Config: rpeConfig, SourceRefs: refs, Timezone: asOf.Location().String(), Status: status, QualityStatus: q, ReasonCodes: reasons, QualityFlags: flags, Value: value, Unit: "AU"}, now)
			if err != nil {
				return err
			}
		}
	}
	return nil
}

func rpeResult(f rpeFact, zone string) metrics.Result {
	var duration, durationMin, load any
	var source any
	if f.source != "" {
		source = f.source
	}
	validDuration := finite(f.duration) && *f.duration >= 0
	if validDuration {
		duration = round(*f.duration, 1)
		durationMin = round(*f.duration/60, 1)
	}
	reasons, flags := []string{}, []string{}
	status, q := "available", "good"
	switch {
	case f.rpe != nil && (!finite(f.rpe) || *f.rpe < 0 || *f.rpe > 10):
		status = "invalid"
		reasons = append(reasons, "RPE_OUT_OF_RANGE")
	default:
		if f.rpe == nil {
			reasons = append(reasons, "RPE_MISSING")
		}
		if !validDuration {
			reasons = append(reasons, "DURATION_MISSING")
		}
		if len(reasons) > 0 {
			status = "missing"
		} else {
			load = round(*f.rpe**f.duration/60, 1)
		}
	}
	if f.rpe != nil && f.other != nil && *f.rpe != *f.other {
		flags = append(flags, "RPE_SOURCE_CONFLICT")
		q = "limited"
	}
	if status != "available" {
		q = ""
	}
	var value any = object{"kind": f.kind, "duration_s": duration, "duration_min": durationMin, "rpe": f.rpe, "rpe_source": source, "other_source_rpe": f.other, "collection_delay_s": f.delay, "load_au": load}
	if f.excluded {
		status = "not_applicable"
		q = ""
		reasons = []string{"ACTIVITY_EXCLUDED"}
		flags = []string{}
		value = nil
	}
	return metrics.Result{MetricID: "session_rpe_load", MethodVersion: "v1", SubjectType: "activity", SubjectKey: f.key, WindowLabel: f.day, WindowStart: f.start, WindowEnd: f.end, Config: rpeConfig, SourceRefs: f.refs, Timezone: zone, Status: status, QualityStatus: q, ReasonCodes: reasons, QualityFlags: flags, Value: value, Unit: "AU"}
}
func persistRPE(ctx context.Context, tx pgx.Tx, f rpeFact, zone string, now time.Time) error {
	_, err := metrics.StoreResult(ctx, tx, rpeResult(f, zone), now)
	return err
}

func RefreshStrength(ctx context.Context, tx pgx.Tx, first, endExclusive time.Time, now time.Time) error {
	facts, err := rpeStrength(ctx, tx, first, endExclusive, true)
	if err != nil {
		return err
	}
	for _, f := range facts {
		if err := persistRPE(ctx, tx, f, first.Location().String(), now); err != nil {
			return err
		}
	}
	_, err = tx.Exec(ctx, `UPDATE metric_results m SET is_current=false FROM manual_sessions s
 WHERE m.metric_id='session_rpe_load' AND method_version='v1' AND is_current AND m.subject_key='manual:'||s.id::text
 AND s.date>=$1::text::date AND s.date<$2::text::date AND(s.kind<>'strength' OR s.linked_activity_id IS NOT NULL)`, first.Format(time.DateOnly), endExclusive.Format(time.DateOnly))
	return err
}

func RefreshRunRPE(ctx context.Context, tx pgx.Tx, id uuid.UUID, zone string, now time.Time) error {
	run, err := metrics.LoadRun(ctx, tx, id, zone)
	if err != nil {
		return err
	}
	if run == nil || !isRunning(run.Sport) {
		_, err := tx.Exec(ctx, `UPDATE metric_results SET is_current=false WHERE metric_id='session_rpe_load' AND method_version='v1' AND subject_key=$1 AND is_current`, id.String())
		return err
	}
	facts, err := rpeRuns(ctx, tx, []*metrics.Run{run})
	if err != nil {
		return err
	}
	f := facts[0]
	f.excluded = !run.Eligible
	f.refs["activity_id"] = id
	return persistRPE(ctx, tx, f, zone, now)
}
func isRunning(sport string) bool {
	return sport == "running" || sport == "trail_running" || sport == "treadmill_running"
}

func CalculateStrength(ctx context.Context, tx pgx.Tx, key string, zone *time.Location) (*metrics.Result, error) {
	prefix, id, ok := strings.Cut(key, ":")
	if !ok || prefix != "strong" && prefix != "manual" {
		return nil, fmt.Errorf("invalid strength subject")
	}
	uid, err := uuid.Parse(id)
	if err != nil {
		return nil, err
	}
	sql := `SELECT local_date::text FROM strong_workouts WHERE id=$1`
	if prefix == "manual" {
		sql = `SELECT date::text FROM manual_sessions WHERE id=$1`
	}
	var day string
	err = tx.QueryRow(ctx, sql, uid).Scan(&day)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, err
	}
	if err == nil {
		start, err := time.ParseInLocation(time.DateOnly, day, zone)
		if err != nil {
			return nil, err
		}
		facts, err := rpeStrength(ctx, tx, start, start.AddDate(0, 0, 1), true)
		if err != nil {
			return nil, err
		}
		for _, f := range facts {
			if f.key == key {
				r := rpeResult(f, zone.String())
				return &r, nil
			}
		}
	}
	return nil, nil
}
func RefreshStrengthKey(ctx context.Context, tx pgx.Tx, key string, zone *time.Location, now time.Time) error {
	r, err := CalculateStrength(ctx, tx, key, zone)
	if err != nil {
		return err
	}
	if r != nil {
		_, err = metrics.StoreResult(ctx, tx, *r, now)
		return err
	}
	_, err = tx.Exec(ctx, `UPDATE metric_results SET is_current=false WHERE metric_id='session_rpe_load' AND method_version='v1' AND subject_key=$1 AND is_current`, key)
	return err
}
