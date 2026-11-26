package travelhttp

import (
	"net/url"
	"testing"
	"time"
)

func TestTravelReadRanges(t *testing.T) {
	home, err := time.LoadLocation("America/New_York")
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 3, 8, 4, 30, 0, 0, time.UTC).In(home)
	first, last, err := (listRange{}).bounds(now, 180)
	if err != nil || first.Format(time.DateOnly) != "2026-02-05" || last.Format(time.DateOnly) != "2026-09-03" {
		t.Fatalf("home-day bounds: %v %v %v", first, last, err)
	}
	start := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	end := start.AddDate(0, 0, 400)
	limits := listRange{start: &start, end: &end}
	if _, _, err := limits.bounds(now, 180); err != nil {
		t.Fatal(err)
	}
	end = end.AddDate(0, 0, 1)
	if _, _, err := limits.bounds(now, 180); err == nil {
		t.Fatal("accepted 401-day range")
	}
}

func TestViewTimes(t *testing.T) {
	la, err := time.LoadLocation("America/Los_Angeles")
	if err != nil {
		t.Fatal(err)
	}
	instant := time.Date(2026, 1, 1, 2, 3, 4, 120000000, time.UTC)
	if got := *isoTime(&instant, la); got != "2025-12-31T18:03:04.120000-08:00" {
		t.Fatal(got)
	}
	if got := *isoTime(&instant, time.UTC); got != "2026-01-01T02:03:04.120000+00:00" {
		t.Fatal(got)
	}
	for raw, want := range map[string]string{"2026-01-01T02:03:04.12+00:00": "2026-01-01T02:03:04.120000Z", "2026-01-01T07:48:04.12+05:45": "2026-01-01T07:48:04.120000+05:45"} {
		got, err := statusTime(&raw)
		if err != nil || got == nil || *got != want {
			t.Fatalf("status time: %v %v", got, err)
		}
	}
	if isoTime(nil, time.UTC) != nil {
		t.Fatal("absent time must stay null")
	}

}

func TestIncludeRemovedQuery(t *testing.T) {
	q := url.Values{"include_removed": {"no", "yes"}}
	if included, err := queryBool(q, "include_removed"); err != nil || !included {
		t.Fatal("last repeated parameter should win")
	}
	q.Set("include_removed", "unknown")
	if _, err := queryBool(q, "include_removed"); err == nil {
		t.Fatal("invalid boolean accepted")
	}
}
