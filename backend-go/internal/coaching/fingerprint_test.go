package coaching

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"slices"
	"testing"
)

func TestPersistedFingerprint(t *testing.T) {
	var fixture struct {
		Vector struct {
			Sources SourceVersions    `json:"source_versions"`
			KB      VerifiedKnowledge `json:"knowledge"`
		} `json:"canonical_vector"`
		Hash        string `json:"sha256"`
		ChangedHash string `json:"changed_selected_content_sha256"`
	}
	data, err := os.ReadFile("../../../backend/tests/fixtures/coach-fingerprint.json")
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	assertDigest := func(want string) {
		t.Helper()
		canonical, got, err := Fingerprint(fixture.Vector.Sources, fixture.Vector.KB)
		if err != nil {
			t.Fatal(err)
		}
		fromBytes := fmt.Sprintf("%x", sha256.Sum256(canonical))
		if got != want || fromBytes != want {
			t.Fatalf("returned digest %s, digest of canonical bytes %s, want %s", got, fromBytes, want)
		}
	}
	assertDigest(fixture.Hash)
	fixture.Vector.KB.SelectedRecords[0].Content["title"] = "Easy revised"
	assertDigest(fixture.ChangedHash)
}

func TestSourceEvidenceIdentity(t *testing.T) {
	canonical := func(input string) ([]byte, string) {
		t.Helper()
		var sources SourceVersions
		if err := json.Unmarshal([]byte(input), &sources); err != nil {
			t.Fatal(err)
		}
		raw, digest, err := Fingerprint(sources, VerifiedKnowledge{})
		if err != nil {
			t.Fatal(err)
		}
		return raw, digest
	}
	raw, original := canonical(`{"legacy":[2,1],"x":9007199254740993,"maybe":null}`)
	want := `{"knowledge":{"digest":"","selected_records":[],"selection":[]},"source_versions":{"legacy":[2,1],"maybe":null,"x":9007199254740993}}`
	if string(raw) != want {
		t.Fatalf("got %s, want %s", raw, want)
	}
	for _, tc := range []struct {
		input string
		equal bool
	}{
		{`{"maybe":null,"x":9007199254740993,"legacy":[2,1]}`, true},
		{`{"x":9007199254740993,"legacy":[2,1]}`, false},
		{`{"maybe":null,"x":9007199254740992,"legacy":[2,1]}`, false},
		{`{"maybe":null,"x":9007199254740993,"legacy":[1,2]}`, false},
	} {
		_, got := canonical(tc.input)
		if (got == original) != tc.equal {
			t.Errorf("unexpected identity for %s: %s", tc.input, got)
		}
	}
}

func TestVerifiedKnowledgeOrder(t *testing.T) {
	var kb VerifiedKnowledge
	err := json.Unmarshal([]byte(`{
		"digest": "synthetic",
		"selection": [{"path":"a","sections":["first","second"]},{"path":"b","record_ids":["a","b"]}],
		"selected_records": [
			{"path":"b","record_id":"a","content":{"n":9007199254740993}},
			{"path":"b","record_id":"b","content":{}}
		]
	}`), &kb)
	if err != nil {
		t.Fatal(err)
	}
	raw, base, err := Fingerprint(SourceVersions{}, kb)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(raw, []byte(`"content":{"n":9007199254740993}`)) {
		t.Fatalf("record content lost precision: %s", raw)
	}
	if !bytes.Contains(raw, []byte(`{"path":"a","sections":["first","second"]}`)) {
		t.Fatalf("section selection changed shape: %s", raw)
	}
	for _, tc := range []struct {
		name string
		swap func()
	}{
		{"sections", func() { slices.Reverse(kb.Selection[0].Sections) }},
		{"record IDs", func() { slices.Reverse(kb.Selection[1].RecordIDs) }},
		{"selection", func() { slices.Reverse(kb.Selection) }},
		{"selected records", func() { slices.Reverse(kb.SelectedRecords) }},
	} {
		tc.swap()
		_, changed, err := Fingerprint(SourceVersions{}, kb)
		if err != nil || changed == base {
			t.Errorf("reordered %s: digest %s, error %v", tc.name, changed, err)
		}
		tc.swap()
	}
}
