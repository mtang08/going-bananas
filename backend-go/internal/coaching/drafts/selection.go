package drafts

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
	"slices"
	"strings"
	"time"
	"unicode/utf8"
)

type DecisionRequest struct {
	Key      string   `json:"idempotency_key"`
	Head     int      `json:"expected_head"`
	Revision int      `json:"expected_revision"`
	Accept   []string `json:"accept_change_ids"`
	Reject   []string `json:"reject_change_ids"`
	Block    bool     `json:"accept_block_change"`
	Anchors  []string `json:"accept_anchor_changes"`
}
type PreparedDecision struct {
	ProposalID   uuid.UUID                  `json:"proposal_id"`
	Selection    DecisionRequest            `json:"selection"`
	DecisionHash string                     `json:"decision_hash"`
	Changes      map[string]Change          `json:"changes"`
	Block        json.RawMessage            `json:"block_change"`
	Anchors      map[string]json.RawMessage `json:"anchor_changes"`
}

func sortedIDs(ids []string) ([]string, error) {
	ordered := append([]string{}, ids...)
	slices.Sort(ordered)
	if len(slices.Compact(slices.Clone(ordered))) != len(ordered) {
		return nil, &Error{"invalid_decision", "Duplicate selected IDs", 422}
	}
	return ordered, nil
}
func (r DecisionRequest) hash(id uuid.UUID) (string, error) {
	accept, err := sortedIDs(r.Accept)
	if err != nil {
		return "", err
	}
	reject, err := sortedIDs(r.Reject)
	if err != nil {
		return "", err
	}
	anchors, err := sortedIDs(r.Anchors)
	if err != nil {
		return "", err
	}
	return hashObject(map[string]any{"proposal_id": id.String(), "revision": r.Revision, "accept_change_ids": accept, "reject_change_ids": reject, "accept_anchor_changes": anchors, "accept_block_change": r.Block})
}

type targetPosition struct {
	outer, inner    int
	modality        string
	low, high       float64
	hasLow, hasHigh bool
}

func numericTargets(raw json.RawMessage) map[targetPosition]bool {
	out := map[targetPosition]bool{}
	var steps []step
	if json.Unmarshal(raw, &steps) != nil {
		return out
	}
	for i, s := range steps {
		children := []step{s}
		if s.Type == "repeat" {
			children = s.Children
		}
		for j, c := range children {
			t := c.Target
			if t == nil || (t.Modality != "hr" && t.Modality != "speed") || (t.Low == nil && t.High == nil) {
				continue
			}
			pos := targetPosition{outer: i, inner: j, modality: t.Modality, hasLow: t.Low != nil, hasHigh: t.High != nil}
			if t.Low != nil {
				pos.low = *t.Low
			}
			if t.High != nil {
				pos.high = *t.High
			}
			out[pos] = true
		}
	}
	return out
}

func validateSelection(r DecisionRequest, parsed Validation, ctx RuleContext, idx coaching.KnowledgeIndex, prepared *PreparedDecision) ([]Issue, error) {
	var d ruleDocument
	if err := json.Unmarshal(parsed.Document, &d); err != nil {
		return nil, err
	}
	var authored struct {
		Changes []changeRequest   `json:"changes"`
		Block   json.RawMessage   `json:"block_change"`
		Anchors []json.RawMessage `json:"anchor_changes"`
	}
	if err := json.Unmarshal(parsed.Payload, &authored); err != nil {
		return nil, err
	}
	incomplete := &Error{"decision_incomplete", "Selection must partition all changes", 422}
	if r.Block && d.Block == nil {
		return nil, incomplete
	}
	if r.Block {
		prepared.Block = authored.Block
	} else {
		d.Block = nil
	}
	tz, err := time.LoadLocation(ctx.Timezone)
	if err != nil {
		return nil, err
	}
	proposed := map[string][]string{}
	allAnchors := d.Anchors
	d.Anchors = nil
	for i, a := range allAnchors {
		key := a.Kind + "-" + a.At.In(tz).Format(time.DateOnly)
		modality := "speed"
		if strings.HasPrefix(a.Kind, "hr_") {
			modality = "hr"
		}
		proposed[modality] = append(proposed[modality], key)
		if slices.Contains(r.Anchors, key) {
			prepared.Anchors[key] = authored.Anchors[i]
			d.Anchors = append(d.Anchors, a)
		}
	}
	if len(prepared.Anchors) != len(r.Anchors) {
		return nil, incomplete
	}
	if len(r.Accept) == 0 && !r.Block && len(r.Anchors) == 0 {
		return []Issue{}, nil
	}
	d.Changes = nil
	for _, c := range authored.Changes {
		if slices.Contains(r.Accept, c.ID) {
			d.Changes = append(d.Changes, c)
		}
	}
	issues, err := runRules(d, nil, ctx, idx, false)
	if err != nil {
		return nil, err
	}
	allowed := d.Operation == "recalibrate_intensity" || d.Operation == "post_event_review" || (d.Operation == "review_training_block" && d.EventReview != nil)
	if !allowed {
		return issues, nil
	}
	for i, c := range authored.Changes {
		if c.After == nil || !slices.Contains(r.Accept, c.ID) {
			continue
		}
		existing := numericTargets(ctx.HeadSessions[c.SessionUID].Structure)
		missing := false
		for pos := range numericTargets(c.After.Structure) {
			if !existing[pos] {
				for _, key := range proposed[pos.modality] {
					if _, ok := prepared.Anchors[key]; !ok {
						missing = true
					}
				}
			}
		}
		if missing {
			issues = append(issues, Issue{"V14.anchor_dependency", fmt.Sprintf("changes.%d.after.structure", i), "Accept the associated anchor or reject the target change"})
		}
	}
	return issues, nil
}

// PrepareDecision rechecks a pending draft and its accepted subset in the caller's
// locked planning transaction. Core resolves stored idempotency receipts before calling.
func PrepareDecision(ctx context.Context, tx pgx.Tx, id uuid.UUID, r DecisionRequest, now time.Time, kbRoot string) (PreparedDecision, error) {
	out := PreparedDecision{ProposalID: id, Selection: r, Anchors: map[string]json.RawMessage{}}
	if n := utf8.RuneCountInString(r.Key); n < 8 || n > 100 || r.Head < 0 || r.Revision < 1 {
		return out, &Error{"invalid_decision", "Invalid decision request", 422}
	}
	hash, err := r.hash(id)
	if err != nil {
		return out, err
	}
	out.DecisionHash = hash
	var draft Draft
	if err := loadDraft(ctx, tx, id, &draft); err != nil {
		return out, err
	}
	if draft.Status == "discarded" {
		return out, &Error{"proposal_discarded", "Discarded proposals cannot be decided", 409}
	}
	if draft.Revision != r.Revision {
		return out, &Error{"proposal_revision_conflict", "This proposal was revised. Reload and review the latest revision.", 409}
	}
	if draft.Status != "pending" {
		return out, &Error{"proposal_stale", "Proposal is no longer pending", 409}
	}
	snap, err := LoadSnapshot(ctx, tx, draft.SnapshotID)
	if err != nil {
		return out, err
	}
	kb, idx, err := coaching.VerifySelection(kbRoot, snap.Selection)
	if err != nil {
		return out, &Error{"knowledge_unavailable", "Verified knowledge is unavailable", 503}
	}
	rules, current, err := LoadRuleContext(ctx, tx, snap, now)
	if err != nil {
		return out, err
	}
	if current.Head != r.Head {
		return out, &Error{"calendar_head_moved", "Calendar changed", 409}
	}
	parsed := ParseDocument(draft.Payload)
	if parsed.Document == nil {
		return out, &CommandError{Error{"invalid_proposal", "Stored proposal is invalid", 422}, parsed.Issues}
	}
	var base DocumentBase
	if err := json.Unmarshal(parsed.Document, &base); err != nil {
		return out, err
	}
	status, issues, err := Freshness(snap, base, current, kb, now)
	if err != nil {
		return out, err
	}
	if status != "pending" {
		code, msg := "proposal_stale", "Proposal base changed"
		switch issues[0].Code {
		case "V2.snapshot_expired":
			msg = "Proposal expired"
		case "V3.stale_sources":
			code, msg = "stale_evidence", "Decision evidence changed"
		}
		return out, &Error{code, msg, 409}
	}
	out.Changes, err = draft.Partition(r.Accept, r.Reject)
	if err != nil {
		return out, &Error{"decision_incomplete", "Selection must partition all changes", 422}
	}
	issues, err = validateSelection(r, parsed, rules, idx, &out)
	if err != nil {
		return out, err
	}
	if len(issues) > 0 {
		return out, &CommandError{Error{"proposal_invalid_subset", "Accepted subset is invalid", 422}, issues}
	}
	return out, nil
}
