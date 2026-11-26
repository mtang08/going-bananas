package trainingwindows

import (
	"context"
	"encoding/json"
	"fmt"
	"slices"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
)

var zones = []string{"easy", "moderate", "high"}
var seconds = []string{"easy_s", "moderate_s", "high_s", "valid_s", "unclassified_s", "unknown_s", "eligible_timer_s"}
var intensityConfig = object{"max_record_gap_s": 10, "zones": zones, "zone_rule": "lower_inclusive", "hr_valid_bpm": []int{30, 230}, "speed_valid_mps": []int{0, 10}, "coverage_good": 0.9, "coverage_limited": 0.7, "window_missing_anchor_reason": "all_present_outcomes.v1"}

func round(n float64, digits int) float64 {
	v, _ := strconv.ParseFloat(strconv.FormatFloat(n, 'f', digits, 64), 64)
	return v
}
func quality(valid, total float64) string {
	if total <= 0 {
		return ""
	}
	switch {
	case valid/total >= 0.9:
		return "good"
	case valid/total >= 0.7:
		return "limited"
	default:
		return "insufficient"
	}
}
func ratios(out object, counts map[string]float64) {
	valid, timer := counts["valid_s"], counts["eligible_timer_s"]
	if timer > 0 {
		out["coverage"] = round(valid/timer, 3)
	}
	for key, denom := range map[string]float64{"fraction_valid": valid, "fraction_timer": timer} {
		if denom <= 0 {
			continue
		}
		v := object{}
		for _, zone := range zones {
			v[zone] = round(counts[zone+"_s"]/denom, 3)
		}
		out[key] = v
	}
}

type modality struct {
	value           object
	status, quality string
	reasons         []string
}

func modalityTotal(name string, items []*dependency, complete bool) (modality, error) {
	m := modality{reasons: []string{}, value: object{"confidence": nil, "activities_total": len(items), "activities_counted": 0, "activities_without_result": 0, "coverage": nil, "fraction_valid": nil, "fraction_timer": nil}}
	counts := map[string]float64{}
	for _, s := range seconds {
		m.value[s] = nil
	}
	counted, without, anchorMissing := 0, 0, 0
	partial, notAssessable := false, false
	for _, item := range items {
		if item == nil {
			without++
			continue
		}
		v, _ := item.value[name].(map[string]any)
		if v == nil {
			continue
		}
		status, _ := v["status"].(string)
		if reasons, ok := v["reason_codes"].([]any); ok && slices.Contains(reasons, any("ANCHOR_MISSING")) {
			anchorMissing++
		}
		if status == "not_assessable" {
			notAssessable = true
		}
		if status != "partial" && status != "available" {
			continue
		}
		counted++
		partial = partial || status == "partial"
		for _, key := range seconds {
			n, ok := v[key].(json.Number)
			if !ok {
				return m, fmt.Errorf("missing %s in counted %s", key, name)
			}
			f, err := n.Float64()
			if err != nil {
				return m, err
			}
			counts[key] += f
		}
	}
	m.value["activities_counted"], m.value["activities_without_result"] = counted, without
	switch {
	case len(items) == 0 && complete:
		for _, s := range seconds {
			m.value[s] = 0.0
		}
		m.status = "available"
	case counted == 0:
		m.status = "missing"
		if notAssessable {
			m.status = "not_assessable"
		}
		if len(items) > 0 {
			m.reasons = append(m.reasons, "NO_ACTIVITY_COUNTED")
			if anchorMissing == len(items) {
				m.reasons = append(m.reasons, "ANCHOR_MISSING")
			}
		}
	default:
		for _, s := range seconds {
			m.value[s] = round(counts[s], 1)
		}
		ratios(m.value, counts)
		m.quality = quality(counts["valid_s"], counts["eligible_timer_s"])
		if counted < len(items) {
			m.reasons = append(m.reasons, "ACTIVITIES_NOT_COUNTED")
		}
		if partial {
			m.reasons = append(m.reasons, "PARTIAL_ACTIVITY_COVERAGE")
		}
		m.status = "available"
		if len(m.reasons) > 0 || !complete {
			m.status = "partial"
		}
	}
	if !complete {
		m.reasons = append(m.reasons, "SYNC_COVERAGE_INCOMPLETE")
	}
	m.value["status"] = m.status
	m.value["reason_codes"] = m.reasons
	return m, nil
}

func RefreshIntensity(ctx context.Context, tx pgx.Tx, asOf, now time.Time) error {
	end := dayStart(asOf).AddDate(0, 0, 1)
	runs, err := runsBetween(ctx, tx, end.AddDate(0, 0, -84), end)
	if err != nil {
		return err
	}
	results, err := resultsFor(ctx, tx, "intensity_time_distribution", runs)
	if err != nil {
		return err
	}
	for _, width := range widths["intensity_time_distribution"] {
		start := end.AddDate(0, 0, -width)
		complete, err := covered(ctx, tx, start, end)
		if err != nil {
			return err
		}
		ids := []string{}
		sources := []object{}
		items := []*dependency{}
		anchorKeys, hashes := map[string]bool{}, map[string]bool{}
		deps := map[string]object{}
		for _, r := range runs {
			if r.Day < start.Format(time.DateOnly) {
				continue
			}
			id := r.ID.String()
			ids = append(ids, id)
			sources = append(sources, r.Refs)
			d, ok := results[id]
			if !ok {
				items = append(items, nil)
				continue
			}
			items = append(items, &d)
			deps[id] = object{"id": d.id, "dependency_hash": d.hash}
			for _, k := range d.anchors {
				anchorKeys[k] = true
			}
			if d.anchorHash != nil && *d.anchorHash != "" {
				hashes[*d.anchorHash] = true
			}
		}
		sorted := slices.Clone(ids)
		slices.Sort(sorted)
		dependencies := []object{}
		for _, id := range sorted {
			if d, ok := deps[id]; ok {
				dependencies = append(dependencies, d)
			}
		}
		hash, err := metrics.Digest(object{"start": start.Format(time.DateOnly), "end": end.Format(time.DateOnly), "coverage_complete": complete})
		if err != nil {
			return err
		}
		refs := object{"activity_ids": ids, "sources": sources, "dependencies": dependencies, "input_hash": hash}
		value := object{"anchor_set_hashes": keys(hashes)}
		reasons := map[string]bool{}
		statuses := []string{}
		q := ""
		for _, name := range []string{"hr", "speed"} {
			m, err := modalityTotal(name, items, complete)
			if err != nil {
				return err
			}
			statuses = append(statuses, m.status)
			value[name] = m.value
			for _, r := range m.reasons {
				reasons[r] = true
			}
			if m.quality != "" && (q == "" || slices.Index([]string{"insufficient", "limited", "good"}, m.quality) < slices.Index([]string{"insufficient", "limited", "good"}, q)) {
				q = m.quality
			}
		}
		status := "missing"
		switch {
		case statuses[0] == "available" && statuses[1] == "available":
			status = "available"
		case slices.Contains(statuses, "partial") || slices.Contains(statuses, "available"):
			status = "partial"
		case slices.Contains(statuses, "not_assessable"):
			status = "not_assessable"
		}
		key := fmt.Sprintf("w%d:%s", width, asOf.Format(time.DateOnly))
		_, err = metrics.StoreResult(ctx, tx, metrics.Result{MetricID: "intensity_time_distribution", MethodVersion: "v1", SubjectType: "window", SubjectKey: key, WindowLabel: key, WindowStart: &start, WindowEnd: &end, Config: intensityConfig, SourceRefs: refs, Timezone: asOf.Location().String(), Status: status, QualityStatus: q, ReasonCodes: keys(reasons), Value: value, Unit: "s", AnchorKeys: keys(anchorKeys)}, now)
		if err != nil {
			return err
		}
	}
	return nil
}
