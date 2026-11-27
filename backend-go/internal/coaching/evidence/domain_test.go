package evidence

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
)

func TestDecisionInputsDomainReferences(t *testing.T) {
	tx := evidenceTx(t)
	b, err := os.ReadFile("testdata/domain.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Name            string
		Operation, AsOf string
		Now             time.Time
		SavedHash       string
		Fresh           bool
		Selection       []coaching.SelectionEntry
		Sources         map[string]string
		Guard, Schedule json.RawMessage
		CurrentHash     string
	}
	if err := json.Unmarshal(b, &cases); err != nil {
		t.Fatal(err)
	}
	if len(cases) != 6 {
		t.Fatal("missing captured evidence phases")
	}
	for _, fixture := range cases {
		// Each SQL file advances the prior phase, even when -run selects one subtest.
		seed, err := os.ReadFile("testdata/" + fixture.Name + ".sql")
		if err != nil {
			t.Fatal(err)
		}
		executeEvidenceSQL(t, tx, string(seed))
		t.Run(fixture.Name, func(t *testing.T) {
			got, err := CollectInputs(t.Context(), tx, fixture.Operation, fixture.AsOf, fixture.Now)
			if err != nil {
				t.Fatal(err)
			}
			compare := func(k string, v any, want []byte) {
				t.Helper()
				raw, err := canonicaljson.Coaching(v)
				if err != nil {
					t.Fatal(err)
				}
				if !bytes.Equal(raw, want) {
					t.Errorf("canonical mismatch in %s: got %s, want %s", k, raw, want)
				}
			}
			if len(fixture.Sources) != len(got.Sources) {
				t.Errorf("source keys: got %d want %d", len(got.Sources), len(fixture.Sources))
			}
			for key, expected := range fixture.Sources {
				value, exists := got.Sources[key]
				if !exists {
					t.Errorf("missing %s", key)
					continue
				}
				raw, err := canonicaljson.Coaching(value)
				if err != nil {
					t.Fatal(err)
				}
				if got := fmt.Sprintf("%x", sha256.Sum256(raw)); got != expected {
					t.Errorf("%s digest: got %s, want %s", key, got, expected)
				}
			}
			compare("confirmed_strength_sessions", got.ConfirmedStrengthSessions, fixture.Schedule)
			compare("safety_guard", got.SafetyGuard, fixture.Guard)
			kb, _, err := coaching.VerifySelection("../../../../running_coach_kb", fixture.Selection)
			if err != nil {
				t.Fatal(err)
			}
			_, hash, err := coaching.Fingerprint(got.Sources, kb)
			if err != nil {
				t.Fatal(err)
			}
			if hash != fixture.CurrentHash || (hash == fixture.SavedHash) != fixture.Fresh {
				t.Errorf("freshness mismatch for captured snapshot: current=%s saved=%s fresh=%t", hash, fixture.SavedHash, fixture.Fresh)
			}
		})
	}
}
