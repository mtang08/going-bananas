package drafts

import (
	_ "embed"
	"encoding/json"
	"github.com/mtang08/going-bananas/backend-go/internal/jsonmodel"
)

//go:embed model.json
var modelData []byte
var models = jsonmodel.Load(modelData, modelCheck)

func modelCheck(name string, authored []byte) string {
	switch name {
	case "Effort":
		var e effort
		_ = json.Unmarshal(authored, &e)
		if e.Low > e.High {
			return "rpe_low must not exceed rpe_high"
		}
	case "Change":
		var c changeRequest
		_ = json.Unmarshal(authored, &c)
		switch c.Op {
		case "add":
			if c.SessionUID != "" || c.After == nil || !hasField(c.After, "local_date") || !hasField(c.After, "kind") || !hasField(c.After, "intent") {
				return "add requires local_date, kind, intent and no session_uid"
			}
		case "modify":
			if c.SessionUID == "" || c.After == nil || len(c.After.raw) == 0 || hasField(c.After, "local_date") {
				return "modify requires session_uid and non-date after fields"
			}
		case "move":
			if c.SessionUID == "" || c.After == nil || !hasField(c.After, "local_date") || !fieldsWithin(c.After, "local_date", "slot") {
				return "move requires session_uid and local_date/slot only"
			}
		case "delete":
			if c.SessionUID == "" || c.After != nil {
				return "delete requires session_uid and no after"
			}
		}
	}
	return ""
}

// ParseDocument normalizes authored and defaulted fields separately, preserving
// the field set used for revision diffs and partial calendar edits.
func ParseDocument(raw json.RawMessage) Validation {
	full, authored, issues := models.Parse("ProposalDoc", "", raw)
	return Validation{Document: full, Payload: authored, Issues: commandIssues(issues)}
}

func parseCommand(name string, raw json.RawMessage, out any) ([]Issue, error) {
	full, _, issues := models.Parse(name, "body", raw)
	if issues != nil {
		return commandIssues(issues), nil
	}
	return nil, json.Unmarshal(full, out)
}
func ParseRevisionRequest(raw json.RawMessage) (RevisionRequest, []Issue, error) {
	var req RevisionRequest
	issues, err := parseCommand("RevisionRequest", raw, &req)
	return req, issues, err
}
func ParseDecisionRequest(raw json.RawMessage) (DecisionRequest, []Issue, error) {
	var req DecisionRequest
	issues, err := parseCommand("DecisionRequest", raw, &req)
	return req, issues, err
}

func commandIssues(src []jsonmodel.Issue) []Issue {
	var out []Issue
	for _, item := range src {
		out = append(out, Issue(item))
	}
	return out
}
