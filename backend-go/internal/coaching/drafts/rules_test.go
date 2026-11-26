package drafts

import (
	"encoding/json"
	"os"
	"slices"
	"testing"

	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
)

func TestPythonRules(t *testing.T) {
	path := os.Getenv("COACHING_RULES_REFERENCE")
	if path == "" {
		t.Skip("scripts/rewrite/coaching/check_rules.py supplies captured cases")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Document json.RawMessage         `json:"document"`
		Context  RuleContext             `json:"rule_context"`
		Index    coaching.KnowledgeIndex `json:"index"`
		Groups   ReferenceGroups         `json:"groups"`
		Expected []Issue                 `json:"expected"`
	}
	if err := json.Unmarshal(data, &cases); err != nil {
		t.Fatal(err)
	}
	for i, c := range cases {
		got, err := ValidateRules(c.Document, c.Context, c.Index, c.Groups)
		if err != nil || !slices.Equal(got, c.Expected) {
			t.Errorf("case %d:\ngot %v %v\nwant %v", i, got, err, c.Expected)
		}
	}
}
