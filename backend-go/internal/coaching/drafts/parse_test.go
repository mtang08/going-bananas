package drafts

import (
	"encoding/json"
	"os"
	"reflect"
	"slices"
	"testing"
)

func TestPythonSchema(t *testing.T) {
	path := os.Getenv("COACHING_SCHEMA_REFERENCE")
	if path == "" {
		t.Skip("check_schema.py supplies corpus")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Input             json.RawMessage
		Document, Payload any
		Issues            []Issue
	}
	if err = json.Unmarshal(data, &cases); err != nil {
		t.Fatal(err)
	}
	for i, c := range cases {
		got := ParseDocument(c.Input)
		if !slices.Equal(got.Issues, c.Issues) {
			t.Fatalf("case %d issues got %v want %v", i, got.Issues, c.Issues)
		}
		for key, pair := range map[string]struct {
			raw  json.RawMessage
			want any
		}{"document": {got.Document, c.Document}, "payload": {got.Payload, c.Payload}} {
			var decoded any
			if pair.raw != nil {
				if err = json.Unmarshal(pair.raw, &decoded); err != nil {
					t.Fatal(err)
				}
			}
			if !reflect.DeepEqual(decoded, pair.want) {
				t.Fatalf("case %d %s got %v want %v", i, key, decoded, pair.want)
			}
		}
	}
}
