package exceptions

import (
	"fmt"
	"maps"
	"slices"
	"sort"
	"strings"
	"time"
)

func endTime(r RpeRun) time.Time {
	if r.EndAt != nil {
		return *r.EndAt
	}
	return r.StartAt
}
func latest(t time.Time, p *time.Time) time.Time {
	if p != nil && p.After(t) {
		return *p
	}
	return t
}
func sessionEv(s SessionFact, why *string) item {
	return evidence("session", &s.SessionUID, latest(s.PlannedAt, s.CompletionUpdatedAt), map[string]any{"local_date": s.LocalDate, "kind": s.Kind, "class": s.SessionClass, "recipe_id": s.RecipeID, "completion_status": s.CompletionStatus, "modification_reason": s.ModificationReason, "reason": why})
}

type aboveRun struct {
	run     RpeRun
	session SessionFact
	tags    []string
}

func (a aboveRun) ev() item {
	return evidence("rpe", &a.run.ActivityID, latest(endTime(a.run), a.run.RPEAt), map[string]any{"rpe": a.run.RPE, "rpe_source": a.run.RPESource, "session_uid": a.session.SessionUID, "class": a.session.SessionClass, "expected_rpe": a.session.ExpectedRPE, "local_date": a.run.LocalDate, "context_tags": a.tags})
}

type failedRun struct {
	session SessionFact
	why     string
}

func hard(cls string) bool { return cls == "quality" || cls == "benchmark" || cls == "long" }
func isEasy(a aboveRun) bool {
	return a.session.SessionClass == "easy" || a.session.SessionClass == "long"
}

func aboveRuns(in DetectionInputs) []aboveRun {
	byID := map[string]SessionFact{}
	for _, s := range in.Sessions {
		byID[s.SessionUID] = s
	}
	var out []aboveRun
	for _, r := range in.Runs {
		s, ok := byID[val(r.SessionUID)]
		if !ok || s.ExpectedRPE == nil || len(*s.ExpectedRPE) != 2 || r.RPE == nil || !recent(in.Today, r.LocalDate, 14) {
			continue
		}
		if s.SessionClass != "easy" && s.SessionClass != "long" && s.SessionClass != "quality" {
			continue
		}
		if *r.RPE < (*s.ExpectedRPE)[1]+2 {
			continue
		}
		tags := map[string]bool{}
		for _, c := range in.Checkins {
			if c.ObservedAt.Sub(endTime(r)).Abs() <= 12*time.Hour {
				for _, t := range c.ContextTags {
					tags[t] = true
				}
			}
		}
		values := slices.AppendSeq([]string{}, maps.Keys(tags))
		slices.Sort(values)
		out = append(out, aboveRun{r, s, values})
	}
	return out
}
func failedRuns(in DetectionInputs) []failedRun {
	var out []failedRun
	for _, s := range in.Sessions {
		if s.Certainty != "committed" || (s.SessionClass != "quality" && s.SessionClass != "benchmark") || !recent(in.Today, s.LocalDate, 14) {
			continue
		}
		why := ""
		switch {
		case val(s.CompletionStatus) == "partial":
			why = "partial"
		case val(s.CompletionStatus) == "completed_modified" && (val(s.ModificationReason) == "fatigue" || val(s.ModificationReason) == "symptom_onset"):
			why = "modified"
		case val(in.PlannedActual[s.SessionUID].TargetCoverage) == "not_met":
			why = "target"
		}
		if why != "" {
			out = append(out, failedRun{s, why})
		}
	}
	return out
}

func trainingRules(in DetectionInputs) []Candidate {
	above, failed := aboveRuns(in), failedRuns(in)
	var out []Candidate
	add := func(code, sev, key string, items []item, summary string) {
		out = append(out, candidate(code, "training_response", sev, key, items, summary))
	}
	repeats := [2][]item{}
	quality := [2][]item{}
	for _, a := range above {
		r, s := a.run, a.session
		bounds := *s.ExpectedRPE
		text := fmt.Sprintf("%s run felt RPE %g (expected %g–%g).", capText(s.SessionClass), *r.RPE, bounds[0], bounds[1])
		if len(a.tags) > 0 {
			labels := make([]string, len(a.tags))
			for i, t := range a.tags {
				labels[i] = strings.ReplaceAll(t, "_", " ")
			}
			text += " " + capText(strings.Join(labels, ", ")) + " reported."
		}
		add("RPE_ABOVE_INTENT", "observe", "activity:"+r.ActivityID, []item{a.ev()}, text)
		if isEasy(a) {
			bucket := daysAgo(in.Today, r.LocalDate) / 7
			repeats[bucket] = append(repeats[bucket], a.ev())
		}
	}
	if n := len(repeats[0]); n >= 2 {
		add("RPE_ABOVE_INTENT_REPEATED", "caution", "rpe_easy_long", slices.Clone(repeats[0]), fmt.Sprintf("%d easy or long runs felt harder than intended in the last 7 days.", n))
	}
	failedItems := []item{}
	for _, f := range failed {
		s := f.session
		why := f.why
		label := why
		switch why {
		case "modified":
			label = "modified for " + strings.ReplaceAll(val(s.ModificationReason), "_", " ")
		case "target":
			label = "target not met"
		}
		ev := sessionEv(s, &why)
		failedItems = append(failedItems, ev)
		add("SESSION_FAILED", "observe", "session:"+s.SessionUID, []item{ev}, fmt.Sprintf("%s session on %s was not completed as planned (%s).", capText(s.SessionClass), dayLabel(s.LocalDate), label))
		bucket := daysAgo(in.Today, s.LocalDate) / 7
		quality[bucket] = append(quality[bucket], ev)
	}
	if n := len(failedItems); n >= 2 {
		add("SESSION_FAILED_REPEATED", "caution", "quality_failed", failedItems, fmt.Sprintf("%d quality sessions were not completed as planned in the last 14 days.", n))
	}
	if (len(repeats[0]) >= 2 || len(quality[0]) >= 2) && (len(repeats[1]) >= 2 || len(quality[1]) >= 2) {
		items := []item{}
		for _, group := range [][]item{repeats[0], quality[0], repeats[1], quality[1]} {
			if len(group) >= 2 {
				items = append(items, group...)
			}
		}
		add("RESPONSE_MULTIWEEK", "escalate", "training_response", items, "Training response flags repeated in both of the last two 7-day periods.")
	}
	if converging := signals(in, above); converging != nil {
		out = append(out, *converging)
	}
	return append(out, calendarRules(in)...)
}

func signals(in DetectionInputs, above []aboveRun) *Candidate {
	var groups [6][]item
	for _, c := range in.Checkins {
		if !recent(in.Today, c.LocalDate, 4) {
			continue
		}
		ev := checkEvidence(c)
		if val(c.Fatigue) >= 7 {
			groups[0] = append(groups[0], ev)
		}
		if slices.Contains(c.ContextTags, "poor_sleep") {
			groups[2] = append(groups[2], ev)
		}
		if slices.Contains(c.ContextTags, "travel") {
			groups[3] = append(groups[3], ev)
		}
		if val(c.Illness) == "possible" {
			groups[5] = append(groups[5], ev)
		}
	}
	for _, a := range above {
		if recent(in.Today, a.run.LocalDate, 4) {
			groups[1] = append(groups[1], a.ev())
		}
	}
	if len(groups[0])+len(groups[1]) == 0 {
		return nil
	}
	for _, date := range in.RecoveryAdverseDates {
		if recent(in.Today, date, 4) {
			groups[4] = append(groups[4], evidence("recovery_night", nil, local(in, date, 0, 0), map[string]any{"local_date": date}))
		}
	}
	if len(groups[4]) < 2 {
		groups[4] = nil
	}
	labels := []string{"high fatigue", "run harder than intended", "poor sleep", "travel", "recovery markers off", "possible illness"}
	var present []string
	var items []item
	seen := map[[3]string]bool{}
	for i, group := range groups {
		if len(group) == 0 {
			continue
		}
		present = append(present, labels[i])
		for _, ev := range group {
			key := [3]string{ev.wire.Type, val(ev.wire.ID), ev.wire.At}
			if !seen[key] {
				items = append(items, ev)
				seen[key] = true
			}
		}
	}
	if len(present) < 2 {
		return nil
	}
	c := candidate("SIGNALS_CONVERGING", "accumulated_fatigue", "caution", "converging", items, "Signals converging in the last 4 days: "+strings.Join(present, ", ")+".")
	return &c
}

func calendarRules(in DetectionInputs) []Candidate {
	var out []Candidate
	var eligible []SessionFact
	var misses []item
	for _, s := range in.Sessions {
		age := daysAgo(in.Today, s.LocalDate)
		status := val(s.CompletionStatus)
		if age >= 1 && age <= 7 && s.Certainty == "committed" && (status == "skipped" || status == "unknown" || s.CompletionStatus == nil && slices.Contains(in.PlannedActual[s.SessionUID].ReasonCodes, "NO_ACTIVITY_FOUND")) {
			ev := sessionEv(s, nil)
			if hard(s.SessionClass) {
				out = append(out, candidate("KEY_SESSION_MISSED", "calendar_disruption", "observe", "session:"+s.SessionUID, []item{ev}, fmt.Sprintf("%s session on %s was missed.", capText(s.SessionClass), dayLabel(s.LocalDate))))
			}
			if s.Kind == "run" {
				misses = append(misses, ev)
			}
		}
		if hard(s.SessionClass) && age >= -6 && age <= 1 && ((age != 1 && status != "skipped") || (age == 1 && (status == "completed_as_planned" || status == "completed_modified" || status == "partial"))) {
			eligible = append(eligible, s)
		}
	}
	if len(misses) >= 2 {
		out = append(out, candidate("RUNS_MISSED_REPEATED", "calendar_disruption", "caution", "runs_missed", misses, fmt.Sprintf("%d planned runs were missed in the last 7 days.", len(misses))))
	}
	for i, a := range eligible {
		for _, b := range eligible[i+1:] {
			if daysAgo(b.LocalDate, a.LocalDate) > 1 {
				break
			}
			lo, hi := min(a.SessionUID, b.SessionUID), max(a.SessionUID, b.SessionUID)
			out = append(out, candidate("HARD_SPACING_TIGHT", "calendar_disruption", "caution", "spacing:"+lo+":"+hi, []item{sessionEv(a, nil), sessionEv(b, nil)}, fmt.Sprintf("Hard sessions on %s and %s are within one day of each other.", dayLabel(a.LocalDate), dayLabel(b.LocalDate))))
		}
	}
	return out
}

func eventRules(in DetectionInputs) []Candidate {
	var out []Candidate
	b := in.BlockBenchmark
	excluded := ""
	if b != nil {
		excluded = val(b.EventID)
		if b.Status == "completed" && b.EvidenceAt != nil && b.LocalDate != nil {
			summary := "Block benchmark completed on " + dayLabel(*b.LocalDate) + "."
			if n := val(b.ResultS); n != 0 {
				clock := fmt.Sprintf("%d:%02d", n/60, n%60)
				if n >= 3600 {
					clock = fmt.Sprintf("%d:%02d:%02d", n/3600, n%3600/60, n%60)
				}
				summary += " Time " + clock + "."
			}
			ev := evidence("activity", b.ActivityID, *b.EvidenceAt, map[string]any{"block_uid": b.BlockUID, "version": b.Version, "match_method": b.MatchMethod, "event_id": b.EventID, "local_date": b.LocalDate, "distance_m": b.DistanceM, "result_s": b.ResultS, "rpe": b.RPE})
			out = append(out, candidate("BLOCK_BENCHMARK_COMPLETED", "post_event", "observe", fmt.Sprintf("block_benchmark_done:%s:%d", b.BlockUID, b.Version), []item{ev}, summary))
		}
		if b.Status == "missed" && b.PlannedDate != nil {
			at := local(in, dateTime(b.ReviewDate).AddDate(0, 0, 3).Format(time.DateOnly), 0, 0)
			ev := evidence("block", &b.BlockUID, at, map[string]any{"version": b.Version, "status": b.Status, "kind": b.Kind, "planned_date": b.PlannedDate, "protocol": b.Protocol, "review_date": b.ReviewDate})
			out = append(out, candidate("BLOCK_BENCHMARK_MISSED", "calendar_disruption", "caution", fmt.Sprintf("block_benchmark_missed:%s:%d", b.BlockUID, b.Version), []item{ev}, "Block benchmark planned for "+dayLabel(*b.PlannedDate)+" was not completed."))
		}
	}
	events := slices.Clone(in.Events)
	sort.SliceStable(events, func(i, j int) bool {
		if events[i].EventDate != events[j].EventDate {
			return events[i].EventDate < events[j].EventDate
		}
		return events[i].ID < events[j].ID
	})
	for _, e := range events {
		age := daysAgo(in.Today, e.EventDate)
		if age < 1 || age > 7 || excluded == e.ID || (e.Purpose != "pr" && e.Purpose != "benchmark") || e.Status == "cancelled" || (!e.HasRunOnDate && e.Status != "completed") {
			continue
		}
		at := local(in, e.EventDate, 23, 59)
		if e.RunEndAt != nil {
			at = *e.RunEndAt
		}
		ev := evidence("event", &e.ID, at, map[string]any{"name": e.Name, "event_date": e.EventDate, "purpose": e.Purpose, "status": e.Status, "run_on_date": e.HasRunOnDate})
		out = append(out, candidate("POST_EVENT_REVIEW_DUE", "post_event", "observe", "event:"+e.ID, []item{ev}, "Race review due for "+e.Name+" on "+dayLabel(e.EventDate)+"."))
	}
	return out
}
