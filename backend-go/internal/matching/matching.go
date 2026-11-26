package matching

import (
	"cmp"
	"maps"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"
)

var extraNamespace = uuid.MustParse("e35269d4-74b0-53bf-8a74-f01b3ef69218")

type dayKind struct {
	day  string
	kind string
}

type reservations struct {
	plans, subjects map[string]bool
	recheck         map[string]string
	deleteAuto      map[string]bool
	oldExtras       map[string]bool
}

func reserve(completions []Completion, scope map[string]bool, plans map[string]Plan, subjects map[string]Subject, eligible map[string]bool) reservations {
	r := reservations{
		plans: map[string]bool{}, subjects: map[string]bool{}, recheck: map[string]string{},
		deleteAuto: map[string]bool{}, oldExtras: map[string]bool{},
	}
	for _, c := range completions {
		uid, key := c.SessionUID, c.key()
		subject, known := subjects[key]
		switch {
		case c.MatchMethod == "user_marked" && c.Status == "completed_as_planned" && key == "":
			// A later recording can supply a subject for this self-report.
			continue
		case c.MatchMethod == "explicit" || c.MatchMethod == "user_marked" || c.MatchMethod == "confirmed_move" || c.Status == "skipped":
			r.plans[uid], r.subjects[key] = true, true
		case c.MatchMethod == "auto_same_day":
			p, found := plans[uid]
			switch {
			case !found || !known || !scope[p.LocalDate]:
				// An incomplete context cannot disprove an existing link.
				r.plans[uid], r.subjects[key] = true, true
			case !eligible[key] || fragment(subject) || p.LocalDate != subject.LocalDate || p.Kind != subject.Kind:
				r.deleteAuto[uid] = true
			default:
				r.recheck[uid] = key
			}
		case c.Status == "extra" && known && scope[subject.LocalDate]:
			r.oldExtras[key] = true
		}
	}
	return r
}

func eligibleKind(kind string) bool {
	return kind == "run" || kind == "strength"
}

func normalizeSubject(s Subject) Subject {
	s.SubjectKey = s.key()
	if !eligibleKind(s.Kind) {
		s.Kind = "run"
		if strings.HasPrefix(s.SubjectKey, "strong:") || strings.HasPrefix(s.SubjectKey, "manual:") {
			s.Kind = "strength"
		}
	}
	return s
}

func neighborDays(day string) [2]string {
	// Input days are already local dates. UTC date arithmetic is independent
	// of the athlete's timezone and of UTC-offset changes across DST.
	t, err := time.Parse(time.DateOnly, day)
	if err != nil {
		return [2]string{}
	}
	return [2]string{t.AddDate(0, 0, -1).Format(time.DateOnly), t.AddDate(0, 0, 1).Format(time.DateOnly)}
}

func candidate(s Subject, reason string) Candidate {
	return Candidate{SubjectKey: s.SubjectKey, LocalDate: s.LocalDate, Kind: s.Kind, Reason: reason}
}

func unresolved(group dayKind, plans []Plan, scores []float64, available map[dayKind][]Subject, fragments []Subject, linked map[string]bool) []Candidate {
	items := []Candidate{}
	for i, s := range available[group] {
		if linked[s.SubjectKey] {
			continue
		}
		c := candidate(s, "SAME_DAY_CANDIDATE")
		if len(scores) > 0 {
			c.Reason = "AMBIGUOUS_MATCH"
			c.Cost = &scores[i]
		}
		items = append(items, c)
	}
	if len(scores) > 0 {
		// Rank using the full precision cost; preserve input order on ties.
		slices.SortStableFunc(items, func(a, b Candidate) int { return cmp.Compare(*a.Cost, *b.Cost) })
		for i := range items {
			n := roundedCost(*items[i].Cost)
			items[i].Cost = &n
		}
	} else {
		if len(plans) > 1 || len(items) > 1 {
			for i := range items {
				items[i].Reason = "AMBIGUOUS_MATCH"
			}
		}
		if len(items) == 0 && group.kind == "run" {
			for _, day := range neighborDays(group.day) {
				for _, s := range available[dayKind{day, "run"}] {
					if !linked[s.SubjectKey] {
						items = append(items, candidate(s, "MOVE_CANDIDATE"))
					}
				}
			}
		}
		// Every candidate here has the same kind. Neighbor-day groups were
		// visited in date order; sorting by date and key also orders same-day ties.
		slices.SortStableFunc(items, func(a, b Candidate) int {
			return cmp.Or(cmp.Compare(a.LocalDate, b.LocalDate), cmp.Compare(a.SubjectKey, b.SubjectKey))
		})
	}
	for _, s := range fragments {
		items = append(items, candidate(s, "FRAGMENT_CANDIDATE"))
	}
	return items
}

type dayGroups struct {
	plans     map[dayKind][]Plan
	subjects  map[dayKind][]Subject
	fragments map[dayKind][]Subject
	planned   map[dayKind]bool // Includes protected plans that suppress an adjacent extra.
}

func groupAvailable(input Input, context, scope map[string]bool) (dayGroups, reservations) {
	plansByUID := map[string]Plan{}
	plannedGroups := map[dayKind]bool{}
	var plans []Plan
	for _, p := range input.Planned {
		if !context[p.LocalDate] || !eligibleKind(p.Kind) || p.Deleted || p.Skipped {
			continue
		}
		plans = append(plans, p)
		plansByUID[p.SessionUID] = p
		plannedGroups[dayKind{p.LocalDate, p.Kind}] = true
	}
	subjectsByKey := map[string]Subject{}
	eligible := map[string]bool{}
	var subjects []Subject
	for _, s := range input.Runs {
		s = normalizeSubject(s)
		if !context[s.LocalDate] || s.SubjectKey == "" {
			continue
		}
		subjectsByKey[s.SubjectKey] = s
		if (s.Eligible == nil || *s.Eligible) && (s.ResolutionState == nil || *s.ResolutionState == "resolved") {
			subjects = append(subjects, s)
			eligible[s.SubjectKey] = true
		}
	}
	r := reserve(input.Completions, scope, plansByUID, subjectsByKey, eligible)
	groups := dayGroups{map[dayKind][]Plan{}, map[dayKind][]Subject{}, map[dayKind][]Subject{}, plannedGroups}
	for _, p := range plans {
		if !r.plans[p.SessionUID] {
			group := dayKind{p.LocalDate, p.Kind}
			groups.plans[group] = append(groups.plans[group], p)
		}
	}
	for _, s := range subjects {
		if r.subjects[s.SubjectKey] {
			continue
		}
		group := dayKind{s.LocalDate, s.Kind}
		if fragment(s) {
			groups.fragments[group] = append(groups.fragments[group], s)
		} else {
			groups.subjects[group] = append(groups.subjects[group], s)
		}
	}

	return groups, r
}

func resolveDays(groups dayGroups, r reservations, scope, context map[string]bool, result *Result) (map[string]string, map[string]bool, map[string][]float64) {
	winners, linked := map[string]string{}, map[string]bool{}
	costsByUID := map[string][]float64{}
	for _, day := range slices.Sorted(maps.Keys(context)) {
		for _, kind := range []string{"run", "strength"} {
			group := dayKind{day, kind}
			dayPlans, daySubjects := groups.plans[group], groups.subjects[group]
			slices.SortStableFunc(dayPlans, func(a, b Plan) int { return cmp.Compare(a.SessionUID, b.SessionUID) })
			assignment, costs := chooseDay(dayPlans, daySubjects, kind)
			for i, j := range assignment {
				uid, key := dayPlans[i].SessionUID, daySubjects[j].SubjectKey
				winners[uid], linked[key] = key, true
				if scope[day] && r.recheck[uid] != key {
					result.Links = append(result.Links, Link{uid, key, "auto_same_day"})
				}
			}
			for i, scores := range costs {
				costsByUID[dayPlans[i].SessionUID] = scores
			}
		}
	}
	return winners, linked, costsByUID
}

// PlanMatches computes links inside Days. ContextDays may reserve subjects
// for neighboring plans and supplies evidence for moved-session candidates.
func PlanMatches(input Input) Result {
	result := Result{
		DeleteAutoSessionUIDs: []string{}, DeleteExtraSubjectKeys: []string{},
		Links: []Link{}, Extras: []Link{}, Candidates: map[string][]Candidate{},
	}
	scope, context := map[string]bool{}, map[string]bool{}
	for _, d := range input.Days {
		scope[d], context[d] = true, true
	}
	for _, d := range input.ContextDays {
		context[d] = true
	}

	groups, r := groupAvailable(input, context, scope)
	winners, linked, costsByUID := resolveDays(groups, r, scope, context, &result)
	for uid, key := range r.recheck {
		if winners[uid] != key {
			r.deleteAuto[uid] = true
		}
	}
	for group, dayPlans := range groups.plans {
		if !scope[group.day] {
			continue
		}
		for _, p := range dayPlans {
			if winners[p.SessionUID] == "" {
				result.Candidates[p.SessionUID] = unresolved(group, dayPlans, costsByUID[p.SessionUID], groups.subjects, groups.fragments[group], linked)
			}
		}
	}
	for group, daySubjects := range groups.subjects {
		if !scope[group.day] || groups.planned[group] {
			continue
		}
		neighbors := neighborDays(group.day)
		if groups.planned[dayKind{neighbors[0], group.kind}] || groups.planned[dayKind{neighbors[1], group.kind}] {
			continue
		}
		for _, s := range daySubjects {
			if !linked[s.SubjectKey] {
				id := uuid.NewSHA1(extraNamespace, []byte("extra:"+s.SubjectKey))
				result.Extras = append(result.Extras, Link{id.String(), s.SubjectKey, "none"})
				delete(r.oldExtras, s.SubjectKey)
			}
		}
	}
	slices.SortFunc(result.Extras, func(a, b Link) int { return cmp.Compare(a.SubjectKey, b.SubjectKey) })
	for uid := range r.deleteAuto {
		result.DeleteAutoSessionUIDs = append(result.DeleteAutoSessionUIDs, uid)
	}
	slices.Sort(result.DeleteAutoSessionUIDs)
	for key := range r.oldExtras {
		result.DeleteExtraSubjectKeys = append(result.DeleteExtraSubjectKeys, key)
	}
	slices.Sort(result.DeleteExtraSubjectKeys)
	return result
}
