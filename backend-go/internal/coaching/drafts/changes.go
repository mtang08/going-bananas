package drafts

import (
	"encoding/json"
	"fmt"
	"slices"
	"time"
)

func has(raw json.RawMessage) bool { return len(raw) > 0 && string(raw) != "null" }
func hasField(s *sessionFields, keys ...string) bool {
	if s != nil {
		for _, k := range keys {
			if _, ok := s.raw[k]; ok {
				return true
			}
		}
	}
	return false
}
func fieldsWithin(s *sessionFields, allowed ...string) bool {
	if s != nil {
		for k := range s.raw {
			if !slices.Contains(allowed, k) {
				return false
			}
		}
	}
	return true
}
func horizon(op string) bool {
	return slices.Contains([]string{"review_rolling_plan", "review_training_block", "handle_goal_or_race_change"}, op)
}
func daysBetween(a, b string) int {
	t, _ := time.Parse(time.DateOnly, a)
	u, _ := time.Parse(time.DateOnly, b)
	return int((u.Unix() - t.Unix()) / 86400)
}
func countQuality(state map[string]sessionFields, week string) int {
	n := 0
	for _, s := range state {
		if quality(s) && inWindow(s.LocalDate, week, dayOffset(week, 6)) {
			n++
		}
	}
	return n
}
func changeRules(d ruleDocument, c RuleContext, state map[string]sessionFields) ([]Issue, error) {
	issues := []Issue{}
	ids, uids := map[string]bool{}, map[string]bool{}
	end := scopeEnd(d, c)
	daily := d.Operation == "proceed_or_modify_today" || d.Operation == "exception_review"
	for i, ch := range d.Changes {
		path := fmt.Sprintf("changes.%d", i)
		add := func(code, suffix string) { issues = append(issues, staleIssue(code, path+suffix)) }
		before, found := c.HeadSessions[ch.SessionUID]
		after, err := mergeSession(before, ch.After)
		if err != nil {
			return nil, err
		}
		if ch.After != nil && has(ch.After.Structure) {
			if _, ok := expand(ch.After.Structure); !ok {
				issues = append(issues, Issue{"V6.invalid_structure", path + ".after.structure", "Invalid workout steps or targets"})
			}
		}
		if ids[ch.ID] {
			add("V4.duplicate_change_id", ".change_id")
		}
		ids[ch.ID] = true
		if ch.SessionUID != "" {
			if !found {
				add("V4.unknown_session", ".session_uid")
			}
			if uids[ch.SessionUID] {
				add("V4.session_in_multiple_changes", ".session_uid")
			}
			uids[ch.SessionUID] = true
		}
		days := []string{}
		if found {
			days = append(days, before.LocalDate)
		}
		if ch.After != nil && (ch.Op == "add" || ch.Op == "move") {
			days = append(days, ch.After.LocalDate)
		}
		beyond, out := false, false
		for _, day := range days {
			if day != "" && !inWindow(day, c.Today, end) {
				out = true
				beyond = beyond || day > end
			}
		}
		if out {
			issue := staleIssue("V5.out_of_scope", path)
			if beyond && horizon(d.Operation) {
				issue.Message = "beyond the block review date; accept the block change or reject this session"
			}
			issues = append(issues, issue)
		}
		if after.Kind == "run" && (ch.Op == "add" || (ch.Op == "modify" && hasField(ch.After, "kind", "recipe_id", "custom", "structure"))) {
			eligible := c.EligibleRecipes
			if d.Block != nil {
				eligible = d.Block.Fields.Recipes
			}
			switch {
			case after.Recipe == "" && (!after.Custom || !has(after.Structure) || string(after.Structure) == "[]"):
				add("V6.recipe_required", ".after")
			case after.Recipe != "" && !recipeID.MatchString(after.Recipe):
				add("V6.unknown_recipe", ".after.recipe_id")
			case after.Recipe != "" && !slices.Contains(eligible, after.Recipe):
				add("V6.recipe_not_eligible", ".after.recipe_id")
			}
		}
		produces := (ch.Op == "add" && after.Kind == "run") || (ch.Op == "move" && found && before.Kind == "run") || (ch.Op == "modify" && found && before.Kind != "run" && after.Kind == "run")
		day := after.LocalDate
		if produces && day != "" && (c.CycleAnchor == "" || daysBetween(c.CycleAnchor, day)%2 != 0) && (!slices.Contains(ch.Flags, "off_cycle_run") || !horizon(d.Operation)) {
			add("V8.off_cycle", "")
		}
		if found && before.Kind == "strength" && ch.Op == "move" {
			if daily {
				add("V9.daily_strength_move", "")
			} else if !slices.Contains(ch.Flags, "strength_move") {
				add("V9.strength_move_flag", "")
			}
		}
		if daily && (((ch.Op == "add" || ch.Op == "delete") && after.Kind == "strength") || (ch.Op == "modify" && found && (before.Kind == "strength") != (after.Kind == "strength"))) {
			add("V9.daily_strength_change", "")
		}
		if ch.Op == "move" && found && quality(before) && day != "" && monday(day) != monday(before.LocalDate) && countQuality(state, monday(day)) > countQuality(c.HeadSessions, monday(day)) {
			add("V10.quality_pileup", "")
		}
		if ch.Op != "delete" {
			if x := c.Interruption; x != nil && after.Kind == "run" && day != "" && day >= c.Today && day >= x.Start && (x.Return == "" || day < x.Return) && (!found || before.Kind != "run" || before.LocalDate != day || raisesDose(after, before)) {
				issues = append(issues, Issue{"V12.running_interruption", path, "Running is unavailable on " + day + ". Remove the run or move it outside the confirmed interruption."})
			}
			if msg := restrictionConflict(c.Restriction, after, before, found); msg != "" {
				issues = append(issues, Issue{"V12.running_restriction", path, msg})
			}
			if after.Kind == "run" && inWindow(day, c.Today, dayOffset(c.Today, 3)) && c.Guard.active() && (!found || before.Kind != "run" || !inWindow(before.LocalDate, c.Today, dayOffset(c.Today, 3)) || raisesDose(after, before)) {
				add("V12.safety_guard", "")
			}
		}
		if d.Operation == "select_quality_session" && (ch.Op != "modify" || !found || !quality(before)) {
			add("V15.not_quality_slot", "")
		}
		if d.Operation == "recalibrate_intensity" && (ch.Op != "modify" || !fieldsWithin(ch.After, "intent", "structure", "brief")) {
			add("V15.recalibrate_change_not_allowed", "")
		}
		reworked := ch.Op == "add" || (ch.Op == "modify" && !fieldsWithin(ch.After, "slot", "locked", "brief"))
		if reworked && after.Kind == "run" && inWindow(day, c.Today, dayOffset(c.Today, 13)) && (ch.After == nil || !has(ch.After.Brief)) {
			issues = append(issues, Issue{"V25.brief_required", path + ".after.brief", "A run added or reworked within 14 days needs a brief"})
		}
	}
	return issues, nil
}
