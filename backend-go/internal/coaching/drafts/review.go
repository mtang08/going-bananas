package drafts

import (
	"fmt"
	"slices"
	"time"
)

type Event struct {
	Status string `json:"status"`
	Day    string `json:"day"`
	Rank   *int   `json:"rank"`
}
type Benchmark struct {
	Status     string `json:"status"`
	ActivityID string `json:"activity_id"`
	EventID    string `json:"event_id"`
	Day        string `json:"local_date"`
}

type reviewFacts struct {
	Findings      map[string]string `json:"findings"`
	Patches       map[string]string `json:"patches"`
	Events        map[string]Event  `json:"events"`
	OpenCodes     []string          `json:"open_rule_codes"`
	Benchmark     *Benchmark        `json:"benchmark"`
	LastBenchmark string            `json:"last_benchmark_date"`
}

type sessionFields struct {
	LocalDate string `json:"local_date"`
	Kind      string `json:"kind"`
}
type changeRequest struct {
	SessionUID string         `json:"session_uid"`
	After      *sessionFields `json:"after"`
}

type exceptionDoc struct {
	Severity string `json:"severity"`
	Window   struct {
		Start string `json:"start"`
		End   string `json:"end"`
	} `json:"patch_window"`
	Ladder    string `json:"ladder_level"`
	Reassess  string `json:"reassess_on"`
	Unchanged []struct {
		UID string `json:"session_uid"`
	} `json:"unchanged"`
	FindingIDs []string `json:"finding_ids"`
}
type eventReview struct {
	EventID    string `json:"event_id"`
	ActivityID string `json:"activity_id"`
	Outcome    string `json:"outcome"`
}
type reviewDocument struct {
	Exception   *exceptionDoc   `json:"exception"`
	EventReview *eventReview    `json:"event_review"`
	Escalation  string          `json:"escalation"`
	Changes     []changeRequest `json:"changes"`
	Resolutions []struct {
		ID string `json:"patch_id"`
	} `json:"patch_resolutions"`
}
type benchmarkFields struct {
	Status  string `json:"status"`
	Target  string `json:"target_event_id"`
	Outline []struct {
		Weeks int `json:"weeks"`
	} `json:"build_outline"`
	Indicators []struct{} `json:"indicators"`
	Benchmark  *struct {
		Day     string `json:"planned_date"`
		Kind    string `json:"kind"`
		EventID string `json:"event_id"`
	} `json:"benchmark"`
}

// Dates reach these rules after schema validation. Calendar arithmetic is civil,
// independent of DST and of the timezone used to determine today's date.
func dayOffset(day string, offset int) string {
	t, _ := time.Parse(time.DateOnly, day)
	return t.AddDate(0, 0, offset).Format(time.DateOnly)
}
func inWindow(day, first, last string) bool { return day >= first && day <= last }

func exceptionRules(d ruleDocument, c RuleContext) []Issue {
	e := d.Exception
	if e == nil {
		if d.Operation == "exception_review" {
			return []Issue{staleIssue("V16.exception_required", "exception")}
		}
		return nil
	}
	if d.Operation != "exception_review" {
		return []Issue{staleIssue("V16.exception_forbidden", "exception")}
	}
	first, last := e.Window.Start, e.Window.End
	lastAllowed := dayOffset(c.Today, 6)
	var out []Issue
	if first < c.Today || first > last || last > lastAllowed {
		out = append(out, staleIssue("V17.window_out_of_scope", "exception.patch_window"))
	}
	maxDays := 7
	if e.Severity == "observe" || e.Severity == "caution" {
		maxDays = 3
	}
	if last > dayOffset(first, maxDays-1) {
		out = append(out, staleIssue("V17.window_too_long", "exception.patch_window"))
	}
	touched := map[string]bool{}
	for i, ch := range d.Changes {
		h, exists := c.HeadSessions[ch.SessionUID]
		touched[ch.SessionUID] = true
		if (exists && !inWindow(h.LocalDate, first, last)) || (ch.After != nil && ch.After.LocalDate != "" && !inWindow(ch.After.LocalDate, first, last)) {
			out = append(out, staleIssue("V17.change_outside_window", fmt.Sprintf("changes.%d", i)))
		}
	}
	if !inWindow(e.Reassess, c.Today, dayOffset(c.Today, 7)) {
		out = append(out, staleIssue("V17.reassess_out_of_range", "exception.reassess_on"))
	}
	var ladderOK bool
	switch e.Ladder {
	case "current_session", "next_session":
		ladderOK = len(d.Changes) == 1 || (len(d.Changes) == 0 && e.Severity == "observe")
	case "next_days":
		ladderOK = last <= dayOffset(first, 2)
	case "committed_window":
		ladderOK = e.Severity == "hold" || e.Severity == "escalate"
	case "block":
		ladderOK = e.Severity == "escalate" && d.Escalation == "review_training_block"
	}
	if !ladderOK {
		out = append(out, staleIssue("V18.ladder_mismatch", "exception.ladder_level"))
	}
	for i, u := range e.Unchanged {
		h, ok := c.HeadSessions[u.UID]
		if !ok || !inWindow(h.LocalDate, c.Today, lastAllowed) || touched[u.UID] {
			out = append(out, staleIssue("V19.unchanged_invalid", fmt.Sprintf("exception.unchanged.%d", i)))
		}
		touched[u.UID] = true
	}
	for i, id := range e.FindingIDs {
		status, ok := c.Findings[id]
		path := fmt.Sprintf("exception.finding_ids.%d", i)
		if !ok {
			out = append(out, staleIssue("V20.finding_unknown", path))
		} else if status != "open" && status != "addressed" {
			out = append(out, staleIssue("V20.finding_closed", path))
		}
	}
	return out
}

func eventRules(d ruleDocument, c RuleContext) []Issue {
	r := d.EventReview
	var out []Issue
	if r != nil && r.EventID == "" && r.ActivityID == "" {
		out = append(out, staleIssue("V20.event_target_invalid", "event_review"))
	}
	if r != nil && r.Outcome != "" && d.Operation != "review_training_block" {
		out = append(out, staleIssue("V20.event_forbidden", "event_review.outcome"))
	}
	switch d.Operation {
	case "post_event_review":
		if r == nil {
			out = append(out, staleIssue("V20.event_required", "event_review"))
		} else if ev, ok := c.Events[r.EventID]; !ok || ev.Status == "cancelled" {
			out = append(out, staleIssue("V20.event_unknown", "event_review.event_id"))
		}
	case "review_training_block":
		if slices.Contains(c.OpenCodes, "BLOCK_BENCHMARK_COMPLETED") && (r == nil || r.Outcome == "") {
			out = append(out, staleIssue("V20.event_required", "event_review"))
		}
		b := c.Benchmark
		if r != nil && (b == nil || b.Status != "completed" || (r.ActivityID != "" && r.ActivityID != b.ActivityID) || (r.EventID != "" && r.EventID != b.EventID)) {
			out = append(out, staleIssue("V20.event_target_invalid", "event_review"))
		}
	default:
		if r != nil {
			out = append(out, staleIssue("V20.event_forbidden", "event_review"))
		}
	}
	return out
}

func benchmarkRules(d ruleDocument, c RuleContext) []Issue {
	if d.Block == nil || d.Block.Fields.Status != "active" {
		return nil
	}
	f := d.Block.Fields
	b := f.Benchmark
	latest := dayOffset(f.Review, -7)
	if b == nil {
		last := c.LastBenchmark
		if c.Benchmark != nil && c.Benchmark.Status == "completed" && d.EventReview != nil && slices.Contains([]string{"progress", "consolidate", "recalibrate_only"}, d.EventReview.Outcome) {
			last = max(last, c.Benchmark.Day)
		}
		if last == "" || latest >= dayOffset(last, 42) {
			msg := "no credible benchmark result yet; set a benchmark"
			if last != "" {
				msg = fmt.Sprintf("Last credible benchmark %s. Set a benchmark or choose a review date on or before %s.", last, dayOffset(last, 48))
			}
			return []Issue{{"V22.benchmark_required", "block_change.version_fields.benchmark", msg}}
		}
		if len(f.Indicators) == 0 {
			return []Issue{staleIssue("V22.indicators_required", "block_change.version_fields.indicators")}
		}
		return nil
	}
	var out []Issue
	if !inWindow(b.Day, dayOffset(f.Review, -13), latest) {
		out = append(out, staleIssue("V22.benchmark_date", "block_change.version_fields.benchmark.planned_date"))
	}
	ev, exists := c.Events[b.EventID]
	if (b.Kind == "event" && (!exists || ev.Status == "cancelled" || ev.Day != b.Day)) || (b.Kind == "time_trial" && (b.EventID != "" || !slices.Contains(f.Recipes, "REC009"))) {
		out = append(out, staleIssue("V22.benchmark_event", "block_change.version_fields.benchmark"))
	}
	return out
}

func targetRules(d ruleDocument, c RuleContext) []Issue {
	if d.Block == nil || !slices.Contains([]string{"review_training_block", "handle_goal_or_race_change"}, d.Operation) {
		return nil
	}
	f := d.Block.Fields
	if f.Status != "active" && f.Status != "consolidating" {
		return nil
	}
	const path = "block_change.version_fields.target_event_id"
	var out []Issue
	var race string
	if f.Target == "" {
		for _, e := range c.Events {
			if e.Rank != nil {
				out = append(out, staleIssue("V23.target_event_required", path))
				break
			}
		}
	} else {
		ev, exists := c.Events[f.Target]
		if !exists || ev.Rank == nil {
			return []Issue{staleIssue("V23.target_event_invalid", path)}
		}
		if *ev.Rank != 1 {
			out = append(out, staleIssue("V23.target_event_not_top", path))
		}
		if ev.Day < f.Start {
			out = append(out, staleIssue("V23.target_event_date", path))
		}
		race = ev.Day
	}
	valid := len(f.Outline) == 0
	if race > f.Review {
		lower, upper := f.Review, f.Review
		for _, step := range f.Outline {
			lower = upper
			upper = dayOffset(upper, 7*step.Weeks)
		}
		valid = len(f.Outline) > 0 && race > lower && race <= upper
	}
	if !valid {
		out = append(out, staleIssue("V23.build_outline_span", "block_change.version_fields.build_outline"))
	}
	return out
}

func resolutionRules(d ruleDocument, c RuleContext) []Issue {
	var out []Issue
	if len(d.Resolutions) > 0 && !slices.Contains([]string{"exception_review", "review_rolling_plan", "review_training_block", "post_event_review"}, d.Operation) {
		out = append(out, staleIssue("V21.resolution_forbidden", "patch_resolutions"))
	}
	seen := map[string]bool{}
	for i, r := range d.Resolutions {
		path := fmt.Sprintf("patch_resolutions.%d.patch_id", i)
		status, ok := c.Patches[r.ID]
		if !ok {
			out = append(out, staleIssue("V21.patch_unknown", path))
		} else if status != "open" && status != "escalated" {
			out = append(out, staleIssue("V21.patch_closed", path))
		}
		if seen[r.ID] {
			out = append(out, staleIssue("V21.patch_duplicate", path))
		}
		seen[r.ID] = true
	}
	return out
}
