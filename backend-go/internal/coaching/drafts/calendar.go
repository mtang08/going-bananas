package drafts

import (
	"encoding/json"
	"fmt"
	"maps"
	"slices"
	"strings"
	"time"
)

type sessionFields struct {
	LocalDate    string          `json:"local_date"`
	Kind         string          `json:"kind"`
	Recipe       string          `json:"recipe_id"`
	Intent       string          `json:"intent"`
	Locked       bool            `json:"locked"`
	Placeholder  bool            `json:"placeholder"`
	Custom       bool            `json:"custom"`
	StrengthSlot string          `json:"strength_slot_id"`
	Duration     *int            `json:"planned_duration_s"`
	Distance     *int            `json:"planned_distance_m"`
	Structure    json.RawMessage `json:"structure"`
	Brief        json.RawMessage `json:"brief"`
	raw          map[string]json.RawMessage
}

func (s *sessionFields) UnmarshalJSON(b []byte) error {
	type fields sessionFields
	var f fields
	if err := json.Unmarshal(b, &f); err != nil {
		return err
	}
	*s = sessionFields(f)
	return json.Unmarshal(b, &s.raw)
}

type changeRequest struct {
	ID         string         `json:"change_id"`
	Op         string         `json:"op"`
	SessionUID string         `json:"session_uid"`
	After      *sessionFields `json:"after"`
	Flags      []string       `json:"material_flags"`
	Reason     string         `json:"reason"`
}

func mergeSession(head sessionFields, after *sessionFields) (sessionFields, error) {
	if after == nil {
		return head, nil
	}
	if head.raw == nil {
		return *after, nil
	}
	merged := maps.Clone(head.raw)
	maps.Copy(merged, after.raw)
	b, err := json.Marshal(merged)
	if err != nil {
		return sessionFields{}, err
	}
	var out sessionFields
	err = json.Unmarshal(b, &out)
	return out, err
}

func resulting(d ruleDocument, ctx RuleContext) (map[string]sessionFields, error) {
	state := maps.Clone(ctx.HeadSessions)
	if state == nil {
		state = map[string]sessionFields{}
	}
	for _, ch := range d.Changes {
		if ch.Op == "add" && slices.Contains(ch.Flags, "strength_omission") {
			continue
		}
		id := ch.SessionUID
		if id == "" {
			id = "new:" + ch.ID
		}
		switch ch.Op {
		case "delete":
			delete(state, id)
		case "add":
			if ch.After != nil {
				state[id] = *ch.After
			}
		default:
			if p, ok := state[id]; ok && ch.After != nil {
				r, err := mergeSession(p, ch.After)
				if err != nil {
					return nil, err
				}
				state[id] = r
			}
		}
	}
	return state, nil
}

func monday(day string) string {
	d, _ := time.Parse(time.DateOnly, day)
	return dayOffset(day, -(int(d.Weekday())+6)%7)
}

func scopeEnd(d ruleDocument, ctx RuleContext) string {
	switch d.Operation {
	case "proceed_or_modify_today":
		return dayOffset(ctx.Today, 3)
	case "exception_review", "post_event_review":
		return dayOffset(ctx.Today, 6)
	case "review_rolling_plan", "review_training_block", "handle_goal_or_race_change":
		review := ctx.ReviewDate
		if d.Block != nil {
			review = ""
			if d.Block.Fields.Status == "active" || d.Block.Fields.Status == "consolidating" {
				review = d.Block.Fields.Review
			}
		}
		return min(max(review, dayOffset(ctx.Today, 13)), dayOffset(ctx.Today, 42))
	default:
		return dayOffset(ctx.Today, 13)
	}
}

type liftSchedule struct {
	days  map[string]bool
	slots map[string]bool
}

func lifts(state map[string]sessionFields) liftSchedule {
	l := liftSchedule{map[string]bool{}, map[string]bool{}}
	for _, p := range state {
		if p.Kind == "strength" {
			l.days[p.LocalDate] = true
			if p.LocalDate != "" && p.StrengthSlot != "" {
				l.slots[monday(p.LocalDate)+"/"+p.StrengthSlot] = true
			}
		}
	}
	return l
}

func omissionTarget(ch changeRequest, ctx RuleContext, head liftSchedule) (string, string) {
	s := ch.After
	if ch.Op == "delete" {
		p, ok := ctx.HeadSessions[ch.SessionUID]
		if ok && p.Kind == "strength" && !p.Locked {
			return p.LocalDate, p.StrengthSlot
		}
		return "", ""
	}
	if ch.Op != "add" || s == nil || s.Kind != "rest" || strings.TrimSpace(s.Intent) == "" {
		return "", ""
	}
	for k, v := range s.raw {
		if string(v) != "null" && k != "local_date" && k != "kind" && k != "intent" {
			return "", ""
		}
	}
	if s.LocalDate != "" && ctx.ConfirmedDates[s.LocalDate] && !head.days[s.LocalDate] {
		return s.LocalDate, ctx.ConfirmedSlots[s.LocalDate]
	}
	return "", ""
}

type omissions struct{ dates, deletions map[string]bool }

func omissionRules(d ruleDocument, c RuleContext, state map[string]sessionFields) (omissions, []Issue) {
	head, result := lifts(c.HeadSessions), lifts(state)
	shared := map[string]bool{}
	for _, slots := range []map[string]string{c.ConfirmedSlots, c.OmittedSlots} {
		counts := map[string]int{}
		for day, slot := range slots {
			k := monday(day) + "/" + slot
			counts[k]++
			if counts[k] > 1 {
				shared[k] = true
			}
		}
	}
	unique := func(day, slot string) string {
		if slot == "" {
			return ""
		}
		k := monday(day) + "/" + slot
		if shared[k] {
			return ""
		}
		return k
	}
	o := omissions{map[string]bool{}, map[string]bool{}}
	slots := map[string]bool{}
	for day := range c.OmittedDates {
		slot := unique(day, c.OmittedSlots[day])
		if head.days[day] || result.days[day] || head.slots[slot] || result.slots[slot] {
			continue
		}
		o.dates[day] = true
		if slot != "" {
			slots[slot] = true
		}
	}
	var issues []Issue
	for i, ch := range d.Changes {
		if !slices.Contains(ch.Flags, "strength_omission") {
			continue
		}
		path := fmt.Sprintf("changes.%d", i)
		day, id := omissionTarget(ch, c, head)
		slot := unique(day, id)
		switch {
		case ch.Op == "add" && (d.Operation == "proceed_or_modify_today" || d.Operation == "exception_review"):
			issues = append(issues, staleIssue("V9.daily_strength_change", path))
		case strings.TrimSpace(ch.Reason) == "":
			issues = append(issues, Issue{"V9.strength_omission_invalid", path + ".reason", "Explain why the lift is omitted"})
		case day == "" || result.days[day] || result.slots[slot] || (ch.Op == "add" && head.slots[slot]) || len(ch.Flags) != 1:
			issues = append(issues, Issue{"V9.strength_omission_invalid", path, "Mark the deletion of a planned lift or identify an absent confirmed recurring lift"})
		case o.dates[day] || slots[slot]:
			issues = append(issues, Issue{"V9.strength_omission_duplicate", path, "This date already has a lift omission"})
		default:
			o.dates[day] = true
			if slot != "" {
				slots[slot] = true
			}
			if ch.Op == "delete" {
				o.deletions[day] = true
			}
		}
	}
	return o, issues
}

func countDays(days map[string]bool, start, end string) int {
	n := 0
	for d := range days {
		if inWindow(d, start, end) {
			n++
		}
	}
	return n
}

func calendarRules(d ruleDocument, c RuleContext, state map[string]sessionFields) []Issue {
	o, issues := omissionRules(d, c, state)
	end := scopeEnd(d, c)
	for day := c.Today; day <= end; day = dayOffset(day, 1) {
		runs, seconds := 0, 0
		missing := false
		for _, p := range state {
			if p.LocalDate != day {
				continue
			}
			switch p.Kind {
			case "rehab":
				if p.Duration == nil {
					missing = true
				} else {
					seconds += *p.Duration
				}
			case "run":
				runs++
			}
		}
		if missing {
			issues = append(issues, Issue{"V7.rehab_duration_required", "changes", day})
		}
		if seconds > 900 {
			issues = append(issues, Issue{"V7.rehab_daily_limit", "changes", day})
		}
		if runs > 1 {
			issues = append(issues, Issue{"V7.multiple_runs_per_day", "changes", day})
		}
	}
	for week := monday(c.Today); week <= end; week = dayOffset(week, 7) {
		stop := dayOffset(week, 6)
		total, strength, long := 0, 0, 0
		for _, p := range state {
			if inWindow(p.LocalDate, week, stop) {
				total++
				if p.Kind == "strength" {
					strength++
				}
				if p.Kind == "run" && p.Recipe == "REC002" {
					long++
				}
			}
		}
		if week >= c.Today && stop <= end {
			head := 0
			for _, p := range c.HeadSessions {
				if p.Kind == "strength" && inWindow(p.LocalDate, week, stop) {
					head++
				}
			}
			omitted, deleted := countDays(o.dates, week, stop), countDays(o.deletions, week, stop)
			if total+head+omitted > 0 && (strength+omitted < 2 || strength+deleted < min(2, head)) {
				issues = append(issues, staleIssue("V9.strength_count", "changes"))
			}
		}
		if long > 1 {
			issues = append(issues, staleIssue("V10.multiple_long", "changes"))
		}
	}
	return issues
}
