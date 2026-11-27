package protocol

import (
	_ "embed"
	"encoding/json"
)

//go:embed proposal.json
var proposal string

//go:embed revision.json
var revision string

func Proposal() json.RawMessage { return json.RawMessage(proposal) }

func Schema() map[string]any {
	return map[string]any{"protocol": "coach_proposal.v2", "activation": "manual", "required_authority": "calendar", "proposal": Proposal(), "revision": json.RawMessage(revision)}
}
