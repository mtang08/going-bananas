package coaching

import (
	"encoding/json"
	"maps"
	"os"
	"reflect"
	"slices"
	"testing"
)

func TestKnowledgePython(t *testing.T) {
	ref := os.Getenv("COACHING_KB_REFERENCE")
	if ref == "" {
		t.Skip("scripts/rewrite/coaching/check_knowledge.py supplies live Python selections")
	}
	b, err := os.ReadFile(ref)
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Selection   []SelectionEntry `json:"selection"`
		Digest      string           `json:"digest"`
		Records     []SelectedRecord `json:"records"`
		PolicyIDs   []string         `json:"policy_ids"`
		RecipeIDs   []string         `json:"recipe_ids"`
		EvidenceIDs []string         `json:"evidence_ids"`
	}
	if err := json.Unmarshal(b, &cases); err != nil {
		t.Fatal(err)
	}
	for i, c := range cases {
		got, index, err := VerifySelection("../../../running_coach_kb", c.Selection)
		if err != nil {
			t.Fatalf("case %d: %v", i, err)
		}
		if got.Digest != c.Digest || !reflect.DeepEqual(got.SelectedRecords, c.Records) || !slices.Equal(slices.Sorted(maps.Keys(index.PolicyIDs)), c.PolicyIDs) || !slices.Equal(slices.Sorted(maps.Keys(index.RecipeIDs)), c.RecipeIDs) || !slices.Equal(slices.Sorted(maps.Keys(index.EvidenceIDs)), c.EvidenceIDs) {
			t.Errorf("case %d: knowledge mismatch, got digest %s, want %s", i, got.Digest, c.Digest)
		}
	}
}

func TestKnowledgeRejectsMissingSection(t *testing.T) {
	_, _, err := VerifySelection("../../../running_coach_kb", []SelectionEntry{{Path: "COACHING_GUIDE.md", Sections: []string{"missing fixture heading"}}})
	if err == nil {
		t.Fatal("missing section passed verification")
	}
}
