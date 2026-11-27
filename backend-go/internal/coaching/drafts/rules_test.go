package drafts

import (
	"encoding/json"
	"os"
	"slices"
	"testing"

	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
)

func TestProposalRuleReferences(t *testing.T) {
	data, err := os.ReadFile("testdata/rules.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Contexts []RuleContext
		Index    coaching.KnowledgeIndex
		Cases    []struct {
			Payload   json.RawMessage
			Document  json.RawMessage
			Context   int
			Selection *DecisionRequest
			Expected  []Issue
		}
	}
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	for i, c := range fixture.Cases {
		ctx := fixture.Contexts[c.Context]
		var got []Issue
		var err error
		if c.Selection != nil {
			got, err = validateSelection(*c.Selection, Validation{Document: c.Document, Payload: c.Payload}, ctx, fixture.Index, &PreparedDecision{Anchors: map[string]json.RawMessage{}})
		} else {
			got, err = ValidateRules(c.Document, c.Payload, ctx, fixture.Index)
		}
		if err != nil || !slices.Equal(got, c.Expected) {
			t.Errorf("case %d:\ngot %v %v\nwant %v", i, got, err, c.Expected)
		}
	}
}
