package coaching

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"maps"
	"os"
	"path/filepath"
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

func TestChangedSelectedRecipe(t *testing.T) {
	root := t.TempDir()
	if err := os.CopyFS(root, os.DirFS("../../../running_coach_kb")); err != nil {
		t.Fatal(err)
	}
	selection := []SelectionEntry{{Path: recipes, RecordIDs: []string{"REC001"}}}
	original, _, err := VerifySelection(root, selection)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, recipes)
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var content map[string]any
	if err := json.Unmarshal(raw, &content); err != nil {
		t.Fatal(err)
	}
	records := content["recipes"].([]any)
	records[0].(map[string]any)["title"] = "Synthetic revised record"
	revised, err := json.Marshal(content)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, revised, 0600); err != nil {
		t.Fatal(err)
	}
	if _, _, err := VerifySelection(root, selection); err == nil {
		t.Fatal("unverified file passed")
	}
	manifest := filepath.Join(root, "manifest.json")
	raw, err = os.ReadFile(manifest)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(raw, &m); err != nil {
		t.Fatal(err)
	}
	for _, row := range m["files"].([]any) {
		r := row.(map[string]any)
		if r["path"] == recipes {
			r["bytes"] = len(revised)
			r["sha256"] = fmt.Sprintf("%x", sha256.Sum256(revised))
		}
	}
	raw, err = json.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(manifest, raw, 0600); err != nil {
		t.Fatal(err)
	}
	fresh, _, err := VerifySelection(root, selection)
	if err != nil {
		t.Fatal(err)
	}
	_, before, err := Fingerprint(SourceVersions{}, original)
	if err != nil {
		t.Fatal(err)
	}
	_, after, err := Fingerprint(SourceVersions{}, fresh)
	if err != nil {
		t.Fatal(err)
	}
	if before == after || fresh.SelectedRecords[0].Content["title"] != "Synthetic revised record" {
		t.Fatal("changed selection did not invalidate saved fingerprint")
	}
}
