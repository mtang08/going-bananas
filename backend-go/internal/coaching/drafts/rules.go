package drafts

import (
	"bytes"
	"encoding/json"
	"fmt"
	"regexp"
	"slices"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
)

// RuleContext carries the facts needed for draft validation after freshness.
type RuleContext struct {
	Today        string          `json:"today"`
	Timezone     string          `json:"timezone"`
	BlockUID     string          `json:"block_uid"`
	HeadSessions map[string]bool `json:"head_sessions"`
}

// ReferenceGroups contains only groups whose validation is still furnished by
// the synthetic reference adapter. Native checks keep the same issue ordering.
type ReferenceGroups struct {
	Changes    []Issue `json:"changes"`
	Calendar   []Issue `json:"calendar"`
	Exceptions []Issue `json:"exceptions"`
}

type reason struct {
	Kind string `json:"kind"`
}
type ruleDocument struct {
	Operation   string   `json:"operation"`
	Preserved   []string `json:"preserved"`
	PolicyIDs   []string `json:"policy_ids"`
	RecipeIDs   []string `json:"recipe_ids"`
	EvidenceIDs []string `json:"evidence_ids"`
	Why         []reason `json:"why"`
	Confidence  struct {
		Decision string `json:"decision"`
	} `json:"confidence"`
	Uncertainty []string          `json:"uncertainty"`
	Triggers    []json.RawMessage `json:"change_triggers"`
	NextCheck   struct {
		On string `json:"on"`
	} `json:"next_check"`
	Block *struct {
		Decision string `json:"decision"`
		UID      string `json:"block_uid"`
		Fields   struct {
			Start   string   `json:"start_date"`
			Review  string   `json:"review_date"`
			Recipes []string `json:"eligible_recipe_ids"`
			Why     []reason `json:"why"`
		} `json:"version_fields"`
	} `json:"block_change"`
	EventReview *json.RawMessage `json:"event_review"`
	Anchors     []struct {
		Kind       string    `json:"kind"`
		Unit       string    `json:"unit"`
		Protocol   string    `json:"protocol"`
		Confidence string    `json:"confidence"`
		Low        float64   `json:"value_low"`
		High       *float64  `json:"value_high"`
		At         time.Time `json:"calibrated_at"`
	} `json:"anchor_changes"`
}

func blockRules(d ruleDocument, ctx RuleContext) []Issue {
	b := d.Block
	if b == nil {
		return nil
	}
	if d.Operation != "review_training_block" && d.Operation != "handle_goal_or_race_change" {
		return []Issue{staleIssue("V13.block_change_not_allowed", "block_change")}
	}
	var issues []Issue
	if (b.Decision == "start") != (ctx.BlockUID == "") {
		issues = append(issues, staleIssue("V13.block_change_invalid", "block_change.decision"))
	}
	if (b.Decision == "start" && b.UID != "") || (b.Decision != "start" && ctx.BlockUID != "" && b.UID != ctx.BlockUID) {
		issues = append(issues, staleIssue("V13.block_change_invalid", "block_change.block_uid"))
	}
	if b.Fields.Review <= b.Fields.Start {
		issues = append(issues, staleIssue("V13.block_change_invalid", "block_change.version_fields.review_date"))
	}
	for i, r := range b.Fields.Recipes {
		if !recipeID.MatchString(r) {
			issues = append(issues, staleIssue("V13.block_change_invalid", fmt.Sprintf("block_change.version_fields.eligible_recipe_ids.%d", i)))
		}
	}
	return issues
}

var recipeID = regexp.MustCompile(`^REC(00[1-9]|010)$`)
var anchorUnits = map[string]string{"hr_aerobic_upper": "bpm", "hr_threshold_lower": "bpm", "speed_aerobic_upper": "mps", "speed_threshold_lower": "mps", "performance_5k": "s", "performance_1mile": "s", "performance_3min": "m", "performance_20_30min": "mps"}
var protocols = strings.Fields("race_5k time_trial_5k time_trial_1mile time_trial_3min time_trial_20_30min workout_derived lab_test manual")
var confidences = strings.Fields("high moderate low insufficient")

func anchorRules(d ruleDocument, ctx RuleContext) ([]Issue, error) {
	if len(d.Anchors) == 0 {
		return nil, nil
	}
	tz, err := time.LoadLocation(ctx.Timezone)
	if err != nil {
		return nil, err
	}
	var issues []Issue
	allowed := d.Operation == "recalibrate_intensity" || d.Operation == "post_event_review" || (d.Operation == "review_training_block" && d.EventReview != nil)
	if !allowed {
		issues = append(issues, staleIssue("V14.anchor_change_not_allowed", "anchor_changes"))
	}
	seen := map[string]bool{}
	for i, a := range d.Anchors {
		unit, ok := anchorUnits[a.Kind]
		key := a.Kind + "-" + a.At.In(tz).Format(time.DateOnly)
		for _, test := range []struct {
			field   string
			invalid bool
		}{
			{"kind", !ok}, {"unit", !ok || a.Unit != unit}, {"protocol", !slices.Contains(protocols, a.Protocol)},
			{"confidence", !slices.Contains(confidences, a.Confidence)}, {"value_high", a.High != nil && a.Low > *a.High}, {"kind", seen[key]},
		} {
			if test.invalid {
				issues = append(issues, staleIssue("V14.anchor_invalid", fmt.Sprintf("anchor_changes.%d.%s", i, test.field)))
			}
		}
		seen[key] = true
	}
	return issues, nil
}

var proseKeys = strings.Fields("headline text when then check coach_note uncertainty reason intent feel focus why effort_cue objective maintained_qualities non_goals early_review_triggers label progress_when protocol progress_if consolidate_if emphasis conditions triggering_evidence relevant_context monitor return_criteria escalate_criteria pacing effort_and_limiter symptoms recovery_observation training_implication compared_with note")
var tokenPattern = regexp.MustCompile(`E-[A-Z]{2,8}-\p{Nd}{2}|P\p{Nd}{3}|REC\p{Nd}{3}|S\p{Nd}{3}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}`)

func hasID(text string) bool {
	word := func(r rune) bool { return r == '_' || unicode.IsLetter(r) || unicode.IsNumber(r) }
	for _, loc := range tokenPattern.FindAllStringIndex(text, -1) {
		before, _ := utf8.DecodeLastRuneInString(text[:loc[0]])
		after, _ := utf8.DecodeRuneInString(text[loc[1]:])
		if !word(before) && !word(after) {
			return true
		}
	}
	return false
}

// Walking normalized JSON tokens preserves the schema field order when several
// prose fields contain IDs. Map iteration would reorder validation issues.
func proseIssues(dec *json.Decoder, path string, prose bool, issues *[]Issue) error {
	value, err := dec.Token()
	if err != nil {
		return err
	}
	switch value {
	case json.Delim('{'):
		for dec.More() {
			key, err := dec.Token()
			if err != nil {
				return err
			}
			name := key.(string)
			p := name
			if path != "" {
				p = path + "." + name
			}
			if err := proseIssues(dec, p, slices.Contains(proseKeys, name), issues); err != nil {
				return err
			}
		}
		_, err = dec.Token()
	case json.Delim('['):
		for i := 0; dec.More(); i++ {
			if err := proseIssues(dec, fmt.Sprintf("%s.%d", path, i), prose, issues); err != nil {
				return err
			}
		}
		_, err = dec.Token()
	default:
		if s, ok := value.(string); ok && prose && hasID(s) {
			*issues = append(*issues, Issue{"V24.id_in_text", path, "Cite IDs in evidence_ids, policy_ids, or recipe_ids, not in text"})
		}
	}
	return err
}

func textRules(d ruleDocument, raw json.RawMessage, today string) ([]Issue, error) {
	var issues []Issue
	if err := proseIssues(json.NewDecoder(bytes.NewReader(raw)), "", false, &issues); err != nil {
		return nil, err
	}
	if d.Confidence.Decision != "high" && len(d.Uncertainty) == 0 {
		issues = append(issues, Issue{"V24.uncertainty_required", "uncertainty", "Name the main unknowns"})
	}
	if d.Operation != "exception_review" && len(d.Triggers) == 0 {
		issues = append(issues, Issue{"V24.triggers_required", "change_triggers", "Name the feedback that would change this decision"})
	}
	day, err := time.Parse(time.DateOnly, today)
	if err != nil {
		return nil, err
	}
	last := day.AddDate(0, 0, 14).Format(time.DateOnly)
	if d.NextCheck.On < today || d.NextCheck.On > last {
		issues = append(issues, Issue{"V24.next_check_date", "next_check.on", fmt.Sprintf("Next check must fall between %s and %s", today, last)})
	}
	if len(d.EvidenceIDs)+len(d.PolicyIDs) == 0 {
		reasons := []struct {
			prefix string
			items  []reason
		}{{"why", d.Why}}
		if d.Block != nil {
			reasons = append(reasons, struct {
				prefix string
				items  []reason
			}{"block_change.version_fields.why", d.Block.Fields.Why})
		}
		for _, group := range reasons {
			for i, v := range group.items {
				if v.Kind == "research" {
					return append(issues, Issue{"V24.research_unsourced", fmt.Sprintf("%s.%d", group.prefix, i), "A research reason needs evidence_ids or policy_ids"}), nil
				}
			}
		}
	}
	return issues, nil
}

func ValidateRules(raw json.RawMessage, ctx RuleContext, idx coaching.KnowledgeIndex, ref ReferenceGroups) ([]Issue, error) {
	var d ruleDocument
	if err := json.Unmarshal(raw, &d); err != nil {
		return nil, err
	}
	issues := append([]Issue{}, ref.Changes...)
	for i, uid := range d.Preserved {
		if !ctx.HeadSessions[uid] {
			issues = append(issues, staleIssue("V4.unknown_preserved", fmt.Sprintf("preserved.%d", i)))
		}
	}
	issues = append(issues, ref.Calendar...)
	for _, group := range []struct {
		name  string
		ids   []string
		known map[string]bool
	}{{"policy_ids", d.PolicyIDs, idx.PolicyIDs}, {"recipe_ids", d.RecipeIDs, idx.RecipeIDs}, {"evidence_ids", d.EvidenceIDs, idx.EvidenceIDs}} {
		for i, id := range group.ids {
			if !group.known[id] {
				issues = append(issues, staleIssue("V11.unknown_kb_id", fmt.Sprintf("%s.%d", group.name, i)))
			}
		}
	}
	issues = append(issues, blockRules(d, ctx)...)
	a, err := anchorRules(d, ctx)
	if err != nil {
		return nil, err
	}
	issues = append(issues, a...)
	issues = append(issues, ref.Exceptions...)
	t, err := textRules(d, raw, ctx.Today)
	return append(issues, t...), err
}
