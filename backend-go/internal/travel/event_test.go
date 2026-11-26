package travel

import (
	"encoding/json"
	"errors"
	"os"
	"reflect"
	"testing"
	"time"
)

// These hashes were produced by app.adapters.google_calendar.to_record from
// the existing synthetic paginated response. Each covers the complete projection.
func TestNormalizeCalendarFixture(t *testing.T) {
	data, err := os.ReadFile("../../../backend/tests/fixtures/gcal/basic_pages.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Pages  []struct{ Items []map[string]any }
		Expect struct {
			Categories map[string]string
			Skipped    []string
		}
	}
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	hashes := map[string]string{
		"evt-flight-1":   "00fefce2ad7b4ea4d82715741293370c41417c2cc255e83c408a256f76c71846",
		"evt-lodging-1":  "65ca56739993b7587a5ac0dff8e24cf9b70ecadacd4c0123a9b88b97885b9bfe",
		"evt-declined-1": "ef38b5b119d7a6eabce6ced630bfcd598200aefceda2a05a8f0535a9d98eab32",
		"evt-focus-1":    "453c8cac092db7cede56e200a89d6a2fb2f7bfe51e18b596d0023263e92c6423",
		"evt-ooo-1":      "c164d3424b26f943ee939d054cfa452e2c0f5ba3f3b60ecff0a9902db6605adf",
	}
	home, err := time.LoadLocation("America/New_York")
	if err != nil {
		t.Fatal(err)
	}
	for _, page := range fixture.Pages {
		for _, raw := range page.Items {
			id := raw["id"].(string)
			r, err := NormalizeEvent(raw)
			if err != nil {
				t.Fatalf("%s: %v", id, err)
			}
			if hashes[id] == "" {
				if r != nil {
					t.Errorf("%s: expected skip", id)
				}
				continue
			}
			if r == nil || r.ContentHash != hashes[id] {
				t.Fatalf("%s: projected hash mismatch", id)
			}
			d := DeriveEvent(*r, home)
			if d.AutoCategory != fixture.Expect.Categories[id] {
				t.Errorf("%s: category %s", id, d.AutoCategory)
			}
			if id == "evt-flight-1" && (d.FlightCode == nil || *d.FlightCode != "ZZ 101" || d.DestinationLabel == nil || *d.DestinationLabel != "Synthetic City" || d.FlightConfidence == nil || *d.FlightConfidence != "high") {
				t.Error("flight fields differ")
			}
		}
	}
}

func TestUnicodeEventHash(t *testing.T) {
	raw := map[string]any{
		"id": "unicode", "summary": "Café & <SYN>\u2028", "location": "éJFK ORD 東京SFO XAA XXX XXX XXX",
		"start": map[string]any{"dateTime": "2026-12-03T16:00:00.123456789+03:00"},
		"end":   map[string]any{"dateTime": "2026-12-03T19:30:00Z"},
	}
	for _, version := range []string{"2026-12-02T03:01:00Z", "2026-12-02T08:00:00-05:00"} {
		raw["updated"] = version
		r, err := NormalizeEvent(raw)
		if err != nil {
			t.Fatal(err)
		}
		if r.ContentHash != "3f3690d856763aba63cfff3a1d6d7a37423fa6cd2830e76264228ffdfdd9cb9a" ||
			!reflect.DeepEqual(r.LocationCodes, []string{"ORD", "XAA", "XXX", "XXX"}) || r.GoogleUpdatedAt == nil || *r.GoogleUpdatedAt != version {
			t.Fatal("Unicode projection or hash differs from Python")
		}
	}
}

func TestInvalidEvent(t *testing.T) {
	date := map[string]any{"date": "2026-12-03"}
	for _, bad := range []map[string]any{
		{"id": true}, {"start": []any{}}, {"end": map[string]any{"date": "2026-02-30"}},
		{"start": map[string]any{"dateTime": "2026-12-03T08:05:00"}, "end": map[string]any{"dateTime": "2026-12-03T09:05:00Z"}},
		{"attendees": []any{map[string]any{"self": true}, "invalid"}}, {"updated": "bad"},
		{"eventType": false}, {"start": map[string]any{"date": "2026-12-03", "timeZone": 1}},
	} {
		raw := map[string]any{"id": "x", "start": date, "end": date}
		for k, v := range bad {
			raw[k] = v
		}
		if r, err := NormalizeEvent(raw); r != nil || !errors.Is(err, ErrInvalidResponse) {
			t.Fatal("malformed item must return gcal_invalid_response")
		}
	}
}
