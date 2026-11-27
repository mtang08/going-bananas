package snapshots

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"slices"
	"testing"

	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/snapshotreads"
)

func TestSnapshotRouteReferences(t *testing.T) {
	raw, err := os.ReadFile("testdata/route.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Operation       string
		Inputs          snapshotreads.Inputs
		Topics, Recipes []string
		ExcerptsSHA     string `json:"excerpts_sha"`
		Digest, Version string
		Chars           int
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	if len(cases) != 16 {
		t.Fatalf("unexpected case count %d", len(cases))
	}
	for _, c := range cases {
		recipes, topics, err := selectRoute(c.Inputs, c.Operation)
		if err != nil {
			t.Fatal(err)
		}
		if !slices.Equal(topics, c.Topics) || !slices.Equal(recipes, c.Recipes) {
			t.Fatalf("%s: topics or recipe selection differs (%v, %v)", c.Operation, topics, recipes)
		}
		route, err := coaching.LoadRoute("../../../../running_coach_kb", c.Operation, recipes, topics)
		if err != nil {
			t.Fatal(err)
		}
		b, err := coaching.CanonicalJSON(route.Excerpts)
		if err != nil {
			t.Fatal(err)
		}
		if fmt.Sprintf("%x", sha256.Sum256(b)) != c.ExcerptsSHA || route.Knowledge.Digest != c.Digest || route.Chars != c.Chars || route.Version != c.Version {
			t.Fatalf("%s: verified route bytes differ", c.Operation)
		}
	}
}
