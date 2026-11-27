package snapshots

import (
	"maps"
	"slices"
	"sort"
	"strings"
	"time"
)

func safeRevision(v any) any {
	r := asObj(v)
	if r == nil {
		return nil
	}
	out := obj{}
	for _, k := range strings.Fields("local_date slot kind recipe_id custom placeholder locked intent planned_duration_s planned_distance_m structure strength_slot_id") {
		if x, ok := r[k]; ok {
			out[k] = x
		}
	}
	return out
}
func containsValue(v any, s string) bool { a, _ := v.([]any); return slices.Contains(a, any(s)) }
func (d displayData) prior() records {
	switch d.op {
	case blockReview:
		out := records{}
		uid := d.block()["block_uid"]
		for _, r := range d.rows("block_decisions") {
			if uid == nil || r["block_uid"] == uid {
				out = append(out, pick(r, "decision from_version to_version rationale confidence decided_at proposal_id block_uid"))
			}
		}
		sortKeys(out, "decided_at")
		return out
	case calibrate:
		return d.rows("anchors")
	}
	ps := d.rows("proposals")
	sort.SliceStable(ps, func(i, j int) bool { return str(ps[i]["submitted_at"]) > str(ps[j]["submitted_at"]) })
	if d.op == rolling || d.op == quality {
		chosen := records{}
		for _, rule := range []struct {
			op    string
			limit int
		}{{rolling, 2}, {exception, 3}} {
			count := 0
			for _, p := range ps {
				if p["operation"] == rule.op && slices.Contains([]string{"accepted", "partially_accepted", "rejected"}, str(p["status"])) {
					chosen = append(chosen, p)
					count++
					if count == rule.limit {
						break
					}
				}
			}
		}
		ps = chosen
	} else {
		ps = ps[:min(len(ps), 3)]
	}
	cs, patches := index(d.rows("completions"), "session_uid"), index(d.rows("exception_patches"), "proposal_id")
	out := records{}
	for _, p := range ps {
		view := pick(p, "proposal_id operation status submitted_at decided_at headline next_check")
		changes := records{}
		for _, c := range list(p["changes"]) {
			item := pick(c, "change_id op session_uid decision")
			item["before"], item["after"] = safeRevision(c["before"]), safeRevision(c["after"])
			if containsValue(c["material_flags"], "strength_omission") {
				item["material_flags"], item["reason"] = []string{"strength_omission"}, c["reason"]
			} else if c["decision"] == "accepted" && c["session_uid"] != nil {
				day := str(asObj(c["after"])["local_date"])
				if day == "" {
					day = str(asObj(c["before"])["local_date"])
				}
				if day != "" {
					reports := records{}
					for _, r := range inWindow(d.rows("checkins"), "local_date", day, offset(day, 3)) {
						reports = append(reports, project(list(r["symptoms"]), "site side severity timing")...)
					}
					item["outcome"] = obj{"session_date": day, "completion_status": cs[str(c["session_uid"])]["status"], "symptom_reports_after": reports}
				}
			}
			changes = append(changes, item)
		}
		view["changes"] = changes
		if p["operation"] == exception {
			view["patch_status"] = patches[str(p["proposal_id"])]["status"]
		}
		out = append(out, view)
	}
	return out
}

var recipeClass = map[string]string{"REC001": "easy", "REC002": "long", "REC003": "quality", "REC004": "quality", "REC005": "quality", "REC006": "quality", "REC007": "easy", "REC008": "quality", "REC009": "benchmark", "REC010": "cross"}
var recipeBounds = map[string][]float64{"REC001": {2, 4}, "REC002": {3, 5}, "REC003": {5, 7}, "REC004": {5, 7}, "REC005": {6, 8}, "REC006": {5, 7}, "REC007": {2, 4}, "REC008": {5, 7}}

func class(s obj) (string, []float64) {
	kind := str(s["kind"])
	if kind != "run" {
		if slices.Contains([]string{"cross", "strength", "mobility", "rehab", "rest"}, kind) {
			return kind, nil
		}
		return "unknown", nil
	}
	if s["recipe_id"] != nil {
		r := str(s["recipe_id"])
		if c := recipeClass[r]; c != "" {
			return c, recipeBounds[r]
		}
		return "unknown", nil
	}
	text := strings.ToLower(str(s["intent"]))
	for _, rule := range []struct {
		words, cls string
		bounds     []float64
	}{{"race|benchmark|time trial", "benchmark", nil}, {"long", "long", []float64{3, 5}}, {"interval|tempo|threshold|quality|hill|vo2|fartlek", "quality", []float64{5, 8}}, {"easy|recovery|shakeout", "easy", []float64{2, 4}}} {
		for _, word := range strings.Split(rule.words, "|") {
			if strings.Contains(text, word) {
				return rule.cls, rule.bounds
			}
		}
	}
	return "unknown", nil
}
func (d displayData) rpeRows() records {
	byA, ss := index(d.rows("completions"), "activity_id"), index(d.rows("sessions"), "session_uid")
	out := records{}
	for _, r := range inWindow(d.rows("runs"), "local_date", offset(d.day, -13), d.day) {
		s := ss[str(byA[str(r["activity_id"])]["session_uid"])]
		v := pick(r, "activity_id local_date rpe rpe_source")
		v["class"], v["expected_rpe"], v["mismatch"] = nil, nil, nil
		if s != nil {
			cls, b := class(s)
			v["class"], v["expected_rpe"] = cls, b
			if len(b) == 2 && r["rpe"] != nil {
				n := number(r["rpe"])
				if n >= b[1]+2 {
					v["mismatch"] = "above"
				} else if cls == "quality" && n <= b[0]-2 {
					v["mismatch"] = "below"
				}
			}
		}
		out = append(out, v)
	}
	sortKeys(out, "local_date", "activity_id")
	slices.Reverse(out)
	return out
}
func liveFinding(f obj) bool                { return f["status"] == "open" || f["status"] == "addressed" }
func livePatch(p obj) bool                  { return p["status"] == "open" || p["status"] == "escalated" }
func newest(rs records, key string) records { sortKeys(rs, key, "id"); slices.Reverse(rs); return rs }
func (d displayData) exceptions() obj {
	fs, ps, up := records{}, records{}, records{}
	for _, f := range d.rows("exception_findings") {
		if liveFinding(f) {
			v := maps.Clone(f)
			ev, _ := f["evidence"].([]any)
			v["evidence"] = append([]any{}, ev[:min(len(ev), 5)]...)
			fs = append(fs, v)
		}
	}
	for _, p := range d.rows("exception_patches") {
		if livePatch(p) {
			ps = append(ps, p)
		}
	}
	for _, s := range chronologicalSessions(inWindow(d.rows("sessions"), "local_date", d.day, offset(d.day, 6))) {
		v := pick(s, "session_uid local_date kind certainty")
		v["class"], v["expected_rpe"] = class(s)
		up = append(up, v)
	}
	rpe := d.rpeRows()
	return obj{"rule_version": "exceptions.v1", "review_recommended": d.rows("review_recommended"), "open_findings": newest(fs, "first_seen_at")[:min(len(fs), 20)], "open_patches": newest(ps, "created_at")[:min(len(ps), 5)], "upcoming": up, "recent_rpe": rpe[:min(len(rpe), 14)]}
}

func (d displayData) exceptionSummary() obj {
	start := offset(d.day, -13)
	since := d.now.AddDate(0, 0, -14)
	var review time.Time
	for _, p := range d.rows("proposals") {
		if (p["operation"] == rolling || p["operation"] == blockReview) && (p["status"] == "accepted" || p["status"] == "partially_accepted") {
			t, _ := time.Parse(time.RFC3339Nano, str(p["decided_at"]))
			if t.After(review) {
				review = t
			}
		}
	}
	var reviewDay any
	if !review.IsZero() {
		reviewDay = review.In(d.zone).Format(time.DateOnly)
	}
	fs, ps := records{}, records{}
	escalations := 0
	for _, f := range d.rows("exception_findings") {
		t, _ := time.Parse(time.RFC3339Nano, str(f["first_seen_at"]))
		if liveFinding(f) || !t.Before(since) {
			fs = append(fs, pick(f, "id rule_code category severity status first_seen_at summary is_new_since_last_review"))
		}
		if liveFinding(f) && f["severity"] == "escalate" {
			escalations++
		}
	}
	for _, p := range d.rows("exception_patches") {
		if livePatch(p) || str(p["window_end"]) >= start {
			v := pick(p, "id category severity window_start window_end status reassess_on")
			ids, _ := p["session_uids"].([]any)
			v["changes_count"] = len(ids)
			ps = append(ps, v)
			if len(ps) == 10 {
				break
			}
		}
	}
	mismatch := map[string]int{"easy_above": 0, "long_above": 0, "quality_above": 0, "quality_below": 0}
	for _, r := range d.rpeRows() {
		k := str(r["class"]) + "_" + str(r["mismatch"])
		if _, ok := mismatch[k]; ok {
			mismatch[k]++
		}
	}
	bySite := map[string]map[string]bool{}
	for _, r := range inWindow(d.rows("checkins"), "local_date", start, d.day) {
		for _, s := range list(r["symptoms"]) {
			side := "None"
			if s["side"] != nil {
				side = str(s["side"])
			}
			k := strings.ToLower(strings.TrimSpace(str(s["site"]))) + "|" + side
			if bySite[k] == nil {
				bySite[k] = map[string]bool{}
			}
			bySite[k][str(r["local_date"])] = true
		}
	}
	sites := records{}
	for k, ds := range bySite {
		if len(ds) >= 2 {
			sites = append(sites, obj{"site_key": k, "distinct_days_14": len(ds)})
		}
	}
	sort.Slice(sites, func(i, j int) bool {
		a, b := sites[i], sites[j]
		if a["distinct_days_14"] != b["distinct_days_14"] {
			return number(a["distinct_days_14"]) > number(b["distinct_days_14"])
		}
		return str(a["site_key"]) < str(b["site_key"])
	})
	return obj{"window_start": start, "window_end": d.day, "since_last_review": reviewDay, "findings": newest(fs, "first_seen_at")[:min(len(fs), 30)], "patches": ps, "rpe_mismatch": mismatch, "recurring_symptom_sites": sites, "open_escalations": escalations}
}

func (d displayData) addSections(out obj) error {
	if d.op != race {
		out["prior_decisions"] = d.prior()
	}
	if d.op == blockReview {
		out["block"] = obj{"active": d.block(), "history": out["prior_decisions"]}
	}
	if d.op == exception || d.op == postEvent {
		out["exceptions"] = d.exceptions()
	}
	if d.op == rolling || d.op == blockReview {
		out["exception_summary"] = d.exceptionSummary()
	}
	return d.addAdvanced(out)
}
