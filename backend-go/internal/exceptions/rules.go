package exceptions

import (
	"cmp"
	"fmt"
	"slices"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

var ruleOrder = []string{"SYM_NEW_SITE", "SYM_WORSENING", "SYM_PERSISTING", "SYM_RECURRENT", "SYM_MULTIWEEK", "GAIT_CHANGE", "GAIT_PERSISTING", "ILLNESS_POSSIBLE", "ILLNESS_PRESENT", "ILLNESS_PROLONGED", "CLINICIAN_RESTRICTION", "RPE_ABOVE_INTENT", "RPE_ABOVE_INTENT_REPEATED", "SESSION_FAILED", "SESSION_FAILED_REPEATED", "RESPONSE_MULTIWEEK", "FATIGUE_HIGH", "FATIGUE_PERSISTING", "SIGNALS_CONVERGING", "FATIGUE_PROLONGED", "KEY_SESSION_MISSED", "RUNS_MISSED_REPEATED", "HARD_SPACING_TIGHT", "TRAVEL_REPORTED", "BLOCK_BENCHMARK_COMPLETED", "BLOCK_BENCHMARK_MISSED", "POST_EVENT_REVIEW_DUE"}

func Candidates(in DetectionInputs) []Candidate {
	in.Checkins = slices.Clone(in.Checkins)
	slices.SortStableFunc(in.Checkins, func(a, b CheckinFact) int {
		if n := a.ObservedAt.Compare(b.ObservedAt); n != 0 {
			return n
		}
		if n := a.RecordedAt.Compare(b.RecordedAt); n != 0 {
			return n
		}
		return cmp.Compare(a.ID, b.ID)
	})
	in.Sessions = slices.Clone(in.Sessions)
	slices.SortStableFunc(in.Sessions, func(a, b SessionFact) int {
		if n := cmp.Compare(a.LocalDate, b.LocalDate); n != 0 {
			return n
		}
		return cmp.Compare(a.SessionUID, b.SessionUID)
	})
	result := symptomRules(in)
	result = append(result, checkinRules(in)...)
	result = append(result, trainingRules(in)...)
	result = append(result, eventRules(in)...)
	slices.SortStableFunc(result, func(a, b Candidate) int {
		return cmp.Compare(slices.Index(ruleOrder, a.Code), slices.Index(ruleOrder, b.Code))
	})
	return result
}
func dateTime(s string) time.Time { t, _ := time.Parse(time.DateOnly, s); return t }
func daysAgo(today, day string) int {
	return int(dateTime(today).Sub(dateTime(day)) / (24 * time.Hour))
}
func recent(today, day string, n int) bool { age := daysAgo(today, day); return age >= 0 && age < n }
func dayLabel(s string) string             { return dateTime(s).Format("Mon Jan 2") }
func capText(s string) string {
	if s == "" {
		return ""
	}
	r, n := utf8.DecodeRuneInString(s)
	return string(unicode.ToUpper(r)) + s[n:]
}
func val[T any](p *T) T {
	if p != nil {
		return *p
	}
	var zero T
	return zero
}
func local(in DetectionInputs, date string, h, m int) time.Time {
	t := dateTime(date)
	zone, _ := time.LoadLocation(in.TZ)
	return time.Date(t.Year(), t.Month(), t.Day(), h, m, 0, 0, zone).UTC()
}
func checkEvidence(c CheckinFact) item {
	tags := c.ContextTags
	if tags == nil {
		tags = []string{}
	}
	return evidence("checkin", &c.ID, c.ObservedAt, map[string]any{"kind": c.Kind, "fatigue": c.Fatigue, "illness": c.Illness, "gait_change": c.GaitChange, "context_tags": tags})
}
func checkItems(checks []CheckinFact) []item {
	items := make([]item, len(checks))
	for i, c := range checks {
		items[i] = checkEvidence(c)
	}
	return items
}
func selectChecks(in DetectionInputs, days int, pred func(CheckinFact) bool) []CheckinFact {
	var out []CheckinFact
	for _, c := range in.Checkins {
		if recent(in.Today, c.LocalDate, days) && pred(c) {
			out = append(out, c)
		}
	}
	return out
}
func distinctDays(checks []CheckinFact) int {
	days := map[string]bool{}
	for _, c := range checks {
		days[c.LocalDate] = true
	}
	return len(days)
}
func checkinRules(in DetectionInputs) []Candidate {
	var out []Candidate
	add := func(code, category, sev, key string, checks []CheckinFact, summary string) {
		out = append(out, candidate(code, category, sev, key, checkItems(checks), summary))
	}
	gait := func(c CheckinFact) bool { return val(c.GaitChange) == "yes" }
	if checks := selectChecks(in, 3, gait); len(checks) > 0 {
		add("GAIT_CHANGE", "symptoms_illness", "hold", "gait", checks, "Gait change reported on "+dayLabel(checks[len(checks)-1].LocalDate)+".")
	}
	if checks := selectChecks(in, 7, gait); len(checks) >= 2 && checks[len(checks)-1].ObservedAt.Sub(checks[0].ObservedAt) >= 20*time.Hour {
		add("GAIT_PERSISTING", "symptoms_illness", "escalate", "gait", checks, fmt.Sprintf("Gait change reported on %d check-ins at least 20 hours apart in the last 7 days.", len(checks)))
	}
	known := func(c CheckinFact) bool { return c.Illness != nil }
	for _, rule := range []struct {
		days                   int
		ill, code, sev, prefix string
	}{{2, "possible", "ILLNESS_POSSIBLE", "caution", "Possible illness"}, {3, "present", "ILLNESS_PRESENT", "hold", "Illness"}} {
		checks := selectChecks(in, rule.days, known)
		if len(checks) == 0 {
			continue
		}
		c := checks[len(checks)-1]
		if val(c.Illness) == rule.ill {
			add(rule.code, "symptoms_illness", rule.sev, "illness", []CheckinFact{c}, rule.prefix+" reported on "+dayLabel(c.LocalDate)+".")
		}
	}
	if c := selectChecks(in, 10, func(c CheckinFact) bool { return val(c.Illness) == "present" }); len(c) > 0 && daysAgo(c[len(c)-1].LocalDate, c[0].LocalDate) >= 6 {
		add("ILLNESS_PROLONGED", "symptoms_illness", "escalate", "illness", c, "Illness reported from "+dayLabel(c[0].LocalDate)+" to "+dayLabel(c[len(c)-1].LocalDate)+".")
	}
	if in.ClinicianRestriction != nil && in.ClinicianRestrictionAt != nil {
		r := []rune(*in.ClinicianRestriction)
		ev := evidence("profile", nil, *in.ClinicianRestrictionAt, map[string]any{"clinician_restriction": *in.ClinicianRestriction})
		out = append(out, candidate("CLINICIAN_RESTRICTION", "symptoms_illness", "escalate", "clinician_restriction", []item{ev}, "Clinician restriction on file: "+string(r[:min(160, len(r))])+"."))
	}
	high := func(c CheckinFact) bool { return val(c.Fatigue) >= 7 }
	if checks := selectChecks(in, 2, high); len(checks) > 0 {
		c := checks[len(checks)-1]
		add("FATIGUE_HIGH", "accumulated_fatigue", "observe", "fatigue", checks, fmt.Sprintf("High fatigue (%g/10) reported on %s.", val(c.Fatigue), dayLabel(c.LocalDate)))
	}
	for _, r := range []struct {
		window, min    int
		code, sev, key string
	}{{4, 2, "FATIGUE_PERSISTING", "caution", "fatigue_persisting"}, {10, 4, "FATIGUE_PROLONGED", "hold", "fatigue_prolonged"}} {
		checks := selectChecks(in, r.window, high)
		days := distinctDays(checks)
		if days >= r.min {
			add(r.code, "accumulated_fatigue", r.sev, r.key, checks, fmt.Sprintf("High fatigue reported on %d days in the last %d days.", days, r.window))
		}
	}
	if c := selectChecks(in, 2, func(c CheckinFact) bool { return slices.Contains(c.ContextTags, "travel") }); len(c) > 0 {
		add("TRAVEL_REPORTED", "calendar_disruption", "observe", "travel", c, "Travel reported on "+dayLabel(c[len(c)-1].LocalDate)+".")
	}
	return out
}

type report struct {
	c CheckinFact
	s SymptomFact
}

func (r report) ev(key string) item {
	return evidence("symptom", &r.s.ID, r.c.ObservedAt, map[string]any{"checkin_id": r.c.ID, "site_key": key, "severity": r.s.Severity, "timing": r.s.Timing, "activity_id": r.c.LinkedActivityID})
}
func symptomRules(in DetectionInputs) []Candidate {
	groups := map[string][]report{}
	var keys []string
	for _, c := range in.Checkins {
		for _, s := range c.Symptoms {
			key := strings.ToLower(strings.TrimSpace(s.Site)) + "|" + s.Side
			if groups[key] == nil {
				keys = append(keys, key)
			}
			groups[key] = append(groups[key], report{c, s})
		}
	}
	var out []Candidate
	for _, key := range keys {
		group := groups[key]
		side := group[0].s.Side
		site := strings.TrimSuffix(key, "|"+side)
		if side != "na" {
			site = side + " " + site
		}
		label := capText(site)
		add := func(code, sev, summary string, reports ...report) {
			items := make([]item, len(reports))
			for i, r := range reports {
				items[i] = r.ev(key)
			}
			out = append(out, candidate(code, "symptoms_illness", sev, "site:"+key, items, summary))
		}
		var fresh, low, up, early, later *report
		var two, three []report
		dates := map[string]bool{}
		weeks := map[int]bool{}
		for i := range group {
			r := &group[i]
			age := daysAgo(in.Today, r.c.LocalDate)
			if age >= 0 && age < 21 {
				three = append(three, *r)
				weeks[age/7] = true
			}
			if age >= 0 && age < 14 {
				two = append(two, *r)
				dates[r.c.LocalDate] = true
			}
			if age < 0 || age >= 7 {
				continue
			}
			isNew := true
			var previous, persist *report
			for k := 0; k < i; k++ {
				p := &group[k]
				diff := r.c.ObservedAt.Sub(p.c.ObservedAt)
				if diff <= 0 {
					continue
				}
				if diff <= 28*24*time.Hour {
					isNew = false
				}
				if diff <= 7*24*time.Hour && (previous == nil || p.c.ObservedAt.After(previous.c.ObservedAt) || p.c.ObservedAt.Equal(previous.c.ObservedAt) && (p.c.RecordedAt.After(previous.c.RecordedAt) || p.c.RecordedAt.Equal(previous.c.RecordedAt) && p.s.ID > previous.s.ID)) {
					previous = p
				}
				if (p.s.Timing == "during" || p.s.Timing == "immediately_after") && p.c.LinkedActivityID != nil && val(p.c.LinkedActivityID) == val(r.c.LinkedActivityID) {
					persist = p
				}
			}
			if isNew {
				fresh = r
			}
			if previous != nil && r.s.Severity > previous.s.Severity {
				low, up = previous, r
			}
			if persist != nil && (r.s.Timing == "next_morning" || r.s.Timing == "hours_24_48") {
				early, later = persist, r
			}
		}
		if fresh != nil {
			sev := "observe"
			if fresh.s.Severity >= 7 {
				sev = "caution"
			}
			add("SYM_NEW_SITE", sev, fmt.Sprintf("New symptom: %s at %g/10.", label, fresh.s.Severity), *fresh)
		}
		if low != nil {
			add("SYM_WORSENING", "caution", fmt.Sprintf("%s symptom rose from %g to %g/10 within 7 days.", label, low.s.Severity, up.s.Severity), *low, *up)
		}
		if early != nil {
			when := "the next morning"
			if later.s.Timing == "hours_24_48" {
				when = "24–48 hours later"
			}
			add("SYM_PERSISTING", "caution", fmt.Sprintf("%s symptom from a run was still present %s (%g/10).", label, when, later.s.Severity), *early, *later)
		}
		if len(dates) >= 3 {
			add("SYM_RECURRENT", "caution", fmt.Sprintf("%s symptom reported on %d days in the last 14 days.", label, len(dates)), two...)
		}
		if len(weeks) == 3 {
			add("SYM_MULTIWEEK", "escalate", label+" symptom reported in each of the last three 7-day periods.", three...)
		}
	}
	return out
}
