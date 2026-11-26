// Package intensity computes athlete-anchor-specific HR and speed zone distributions.
package intensity

import (
	"context"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/recording"
	"math"
	"slices"
	"strconv"
	"time"
)

const ID = "intensity_time_distribution"
const Version = "v1"

type obj = map[string]any

var Config = obj{"max_record_gap_s": 10, "zones": []string{"easy", "moderate", "high"}, "zone_rule": "lower_inclusive", "hr_valid_bpm": []int{30, 230}, "speed_valid_mps": []int{0, 10}, "coverage_good": 0.9, "coverage_limited": 0.7, "window_missing_anchor_reason": "all_present_outcomes.v1"}

type anchor struct {
	key, kind, review, confidence, hash string
	low                                 float64
}

func loadAnchors(ctx context.Context, tx pgx.Tx, day string) (map[string]anchor, error) {
	rows, err := tx.Query(ctx, `WITH active AS(SELECT * FROM intensity_anchors WHERE valid_from<=$1::text::date AND status IN ('active','expired'))
 SELECT DISTINCT ON(a.kind) a.kind,a.anchor_key,a.review_after::text,a.confidence,a.value_low,
   to_jsonb(a)-'id'-'status'||jsonb_build_object('calibrated_at',to_char(a.calibrated_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')),
   a.value_high
 FROM active a WHERE NOT EXISTS(SELECT FROM active b WHERE b.supersedes_key=a.anchor_key)
 ORDER BY a.kind,a.valid_from DESC,a.calibrated_at DESC,a.anchor_key DESC`, day)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[string]anchor{}
	for rows.Next() {
		var a anchor
		var raw []byte
		var high *float64
		if err = rows.Scan(&a.kind, &a.key, &a.review, &a.confidence, &a.low, &raw, &high); err != nil {
			return nil, err
		}
		v, err := metrics.JSONValue(raw)
		if err != nil {
			return nil, err
		}
		fields := v.(map[string]any)
		fields["value_low"] = a.low
		fields["value_high"] = high
		a.hash, err = metrics.Digest(fields)
		if err != nil {
			return nil, err
		}
		out[a.kind] = a
	}
	return out, rows.Err()
}
func round(v float64, d int) float64 {
	x, _ := strconv.ParseFloat(strconv.FormatFloat(v, 'f', d, 64), 64)
	return x
}

type modality struct {
	v              obj
	quality        string
	flags, reasons []string
	used           []anchor
}

func (m *modality) stop(status string, reasons ...string) {
	m.v["status"] = status
	m.v["reason_codes"] = reasons
	m.reasons = reasons
}
func outcome(kind string, s *recording.Stream, anchors map[string]anchor, day string, sessionTimer *float64) (modality, error) {
	m := modality{v: obj{"confidence": nil}}
	for _, k := range []string{"easy_s", "moderate_s", "high_s", "valid_s", "unclassified_s", "unknown_s", "eligible_timer_s", "coverage", "fraction_valid", "fraction_timer"} {
		m.v[k] = nil
	}
	if s == nil {
		m.stop("missing", "NO_STREAM")
		return m, nil
	}
	for _, flag := range []string{"TIMER_EVENTS_MISSING", "TIMER_EVENTS_AMBIGUOUS", "TIMER_MISMATCH"} {
		if slices.Contains(s.Flags, flag) {
			m.flags = append(m.flags, flag)
		}
	}
	if len(m.flags) > 0 && !slices.Contains(m.flags, "TIMER_MISMATCH") {
		m.stop("not_assessable", m.flags...)
		return m, nil
	}
	a, b := anchors[kind+"_aerobic_upper"], anchors[kind+"_threshold_lower"]
	series := s.HR
	if kind == "speed" {
		series = s.Speed
	}
	if len(m.flags) == 0 {
		if a.key == "" || b.key == "" || a.confidence == "insufficient" || b.confidence == "insufficient" {
			m.stop("not_assessable", "ANCHOR_MISSING")
			return m, nil
		}
		m.used = []anchor{a, b}
		if a.low >= b.low {
			m.stop("invalid", "ANCHOR_CONFIG_ERROR")
			return m, nil
		}
		rank := []string{"low", "moderate", "high"}
		c := rank[min(slices.Index(rank, a.confidence), slices.Index(rank, b.confidence))]
		m.v["confidence"] = c
		if c == "low" {
			m.flags = append(m.flags, "LOW_CONFIDENCE_ANCHOR")
		}
		if day > a.review || day > b.review {
			m.flags = append(m.flags, "ANCHOR_REVIEW_DUE")
		}
		if !slices.ContainsFunc(series, func(v *float64) bool { return v != nil }) {
			reason := "HR_NOT_RECORDED"
			if kind == "speed" {
				reason = "SPEED_NOT_RECORDED"
			}
			m.stop("missing", reason)
			return m, nil
		}
	}
	spans, err := recording.Union(s.Timer)
	if err != nil {
		return m, err
	}
	pieces, err := recording.Integrate(s.Times, spans)
	if err != nil {
		return m, err
	}
	var total, valid float64
	zones := [3]float64{}
	for _, p := range pieces {
		total += p.Seconds
		if p.Index < 0 || p.Index >= len(series) || series[p.Index] == nil {
			continue
		}
		v := *series[p.Index]
		if math.IsNaN(v) || (kind == "hr" && (v < 30 || v > 230)) || (kind == "speed" && (v < 0 || v > 10)) {
			continue
		}
		i := 0
		if v >= b.low {
			i = 2
		} else if v >= a.low {
			i = 1
		}
		zones[i] += p.Seconds
		valid += p.Seconds
	}
	if slices.Contains(m.flags, "TIMER_MISMATCH") {
		m.v["timer_diagnostics"] = obj{"eligible_timer_s": round(total, 1), "session_timer_s": sessionTimer}
		m.stop("not_assessable", m.flags...)
		return m, nil
	}
	if total == 0 {
		m.stop("missing", "NO_TIMER_ON_DATA")
		return m, nil
	}
	if sessionTimer != nil && math.Abs(total-*sessionTimer) > max(1, .01*(*sessionTimer)) {
		m.flags = append(m.flags, "TIMER_MISMATCH")
		m.v["timer_diagnostics"] = obj{"eligible_timer_s": round(total, 1), "session_timer_s": sessionTimer}
		m.stop("not_assessable", "TIMER_MISMATCH")
		return m, nil
	}
	m.v["eligible_timer_s"] = round(total, 1)
	m.v["valid_s"] = round(valid, 1)
	m.v["unclassified_s"] = 0.
	m.v["unknown_s"] = round(total-valid, 1)
	m.v["coverage"] = round(valid/total, 3)
	fractionTimer, fractionValid := obj{}, obj{}
	for i, z := range []string{"easy", "moderate", "high"} {
		m.v[z+"_s"] = round(zones[i], 1)
		fractionTimer[z] = round(zones[i]/total, 3)
		if valid != 0 {
			fractionValid[z] = round(zones[i]/valid, 3)
		}
	}
	m.v["fraction_timer"] = fractionTimer
	if valid != 0 {
		m.v["fraction_valid"] = fractionValid
	}
	m.quality = "good"
	m.stop("available")
	m.v["reason_codes"] = []string{}
	if valid/total < .9 {
		m.quality = "limited"
		if valid/total < .7 {
			m.quality = "insufficient"
		}
		m.stop("partial", "LOW_COVERAGE")
	}
	return m, nil
}
func Calculate(ctx context.Context, tx pgx.Tx, id uuid.UUID) (*metrics.Result, error) {
	zone, err := db.New(tx).CalendarTimezone(ctx)
	if err != nil {
		return nil, err
	}
	run, err := metrics.LoadRun(ctx, tx, id, zone)
	if err != nil || run == nil {
		return nil, err
	}
	if !slices.Contains([]string{"running", "trail_running", "treadmill_running"}, run.Sport) {
		return nil, nil
	}
	refs := obj{"activity": obj{"id": id, "source_revision": run.SourceRevision, "source_refs": run.Refs}, "fit": run.FIT, "plan": nil, "completion_association_hash": nil, "activity_ids": []string{id.String()}}
	result := metrics.Result{MetricID: ID, MethodVersion: Version, SubjectType: "activity", SubjectKey: id.String(), Timezone: zone, Unit: "s", Config: Config, SourceRefs: refs}
	if !run.Eligible {
		result.Status = "not_applicable"
		result.ReasonCodes = []string{"ACTIVITY_EXCLUDED"}
		return &result, nil
	}
	stream, err := recording.LoadStream(ctx, tx, id)
	if err != nil {
		return nil, err
	}
	anchors, err := loadAnchors(ctx, tx, run.Day)
	if err != nil {
		return nil, err
	}
	value := obj{"session_timer_s": run.Timer}
	result.Value = value
	var statuses []string
	var used [][3]string
	keys := []string{}
	qrank := []string{"insufficient", "limited", "good"}
	for _, k := range []string{"hr", "speed"} {
		m, err := outcome(k, stream, anchors, run.Day, run.Timer)
		if err != nil {
			return nil, err
		}
		value[k] = m.v
		statuses = append(statuses, m.v["status"].(string))
		result.ReasonCodes = append(result.ReasonCodes, m.reasons...)
		result.QualityFlags = append(result.QualityFlags, m.flags...)
		if m.quality != "" && (result.QualityStatus == "" || slices.Index(qrank, m.quality) < slices.Index(qrank, result.QualityStatus)) {
			result.QualityStatus = m.quality
		}
		for _, a := range m.used {
			used = append(used, [3]string{a.kind, a.key, a.hash})
			keys = append(keys, a.key)
		}
	}
	result.Status = "missing"
	switch {
	case statuses[0] == "available" && statuses[1] == "available":
		result.Status = "available"
	case slices.Contains(statuses, "available") || slices.Contains(statuses, "partial"):
		result.Status = "partial"
	case slices.Contains(statuses, "not_assessable"):
		result.Status = "not_assessable"
	case slices.Contains(statuses, "invalid"):
		result.Status = "invalid"
	}
	slices.Sort(keys)
	result.AnchorKeys = keys
	refs["anchor_keys"] = keys
	if len(used) > 0 {
		hash, err := metrics.Digest(used)
		if err != nil {
			return nil, err
		}
		result.AnchorSetHash = &hash
	}
	slices.Sort(result.ReasonCodes)
	result.ReasonCodes = slices.Compact(result.ReasonCodes)
	slices.Sort(result.QualityFlags)
	result.QualityFlags = slices.Compact(result.QualityFlags)
	return &result, nil
}

func Refresh(ctx context.Context, tx pgx.Tx, id uuid.UUID, now time.Time) (uuid.UUID, error) {
	r, err := Calculate(ctx, tx, id)
	if err != nil || r == nil {
		return uuid.Nil, err
	}
	return metrics.StoreResult(ctx, tx, *r, now)
}
