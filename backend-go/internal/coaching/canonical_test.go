package coaching

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"math"
	"os"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestCoachingCanonicalFixture(t *testing.T) {
	raw, err := os.ReadFile("../../../backend/tests/fixtures/canonical-hashes.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Input    map[string]any
		Expected struct {
			Coaching struct {
				Canonical string `json:"canonical_json"`
				SHA256    string
			}
		}
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err := decoder.Decode(&fixture); err != nil {
		t.Fatal(err)
	}
	id, err := uuid.Parse(fixture.Input["id"].(string))
	if err != nil {
		t.Fatal(err)
	}
	fixture.Input["id"] = id
	var instants []time.Time
	for _, raw := range fixture.Input["instants"].([]any) {
		instant, err := time.Parse(time.RFC3339Nano, raw.(string))
		if err != nil {
			t.Fatal(err)
		}
		instants = append(instants, instant)
	}
	fixture.Input["instants"] = instants
	got, err := CanonicalJSON(fixture.Input)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != fixture.Expected.Coaching.Canonical {
		t.Errorf("canonical bytes = %q, want %q", got, fixture.Expected.Coaching.Canonical)
	}
	hash := sha256.Sum256(got)
	if digest := hex.EncodeToString(hash[:]); digest != fixture.Expected.Coaching.SHA256 {
		t.Errorf("sha256 = %s, want %s", digest, fixture.Expected.Coaching.SHA256)
	}
}

func TestCanonicalScalarEdges(t *testing.T) {
	for _, tc := range []struct {
		name  string
		input any
		want  string
	}{
		{"binary64 cutovers", []any{1e-5, 1e-4, 1e15, 1e16, math.SmallestNonzeroFloat64}, "[1e-05,0.0001,1000000000000000.0,1e+16,5e-324]"},
		{"arbitrary integer and zero", []json.Number{"18446744073709551619", "-0", "-0E+5"}, "[18446744073709551619,0,-0.0]"},
		{"controls and quotes", "\"\\/\x00\b\f\n\r\t\x1b\x7f🍌", `"\"\\/\u0000\b\f\n\r\t\u001b` + "\x7f🍌\""},
		{"offset crosses date", time.Date(2026, 1, 1, 0, 30, 0, 1000, time.FixedZone("plus one", 3600)), `"2025-12-31T23:30:00.000001+00:00"`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, err := CanonicalJSON(tc.input)
			if err != nil || string(got) != tc.want {
				t.Fatalf("CanonicalJSON = %q, %v; want %q", got, err, tc.want)
			}
		})
	}
}

func TestCanonicalInvalidValues(t *testing.T) {
	for _, value := range []any{
		math.Inf(1), math.NaN(), json.Number("01"), json.Number("1e400"), map[int]string{},
		"\xff", time.Unix(0, 1),
	} {
		if got, err := CanonicalJSON(value); err == nil {
			t.Errorf("CanonicalJSON(%v) = %q, want error", value, got)
		}
	}
}
