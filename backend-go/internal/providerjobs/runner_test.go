package providerjobs

import (
	"context"
	"errors"
	"net/http"
	"testing"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
)

func TestRetryAfter(t *testing.T) {
	now := time.Date(2026, 2, 15, 12, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		header string
		delay  time.Duration
	}{{"37.5", 37500 * time.Millisecond}, {"-2", 0}, {now.Add(time.Minute).Format(http.TimeFormat), time.Minute}, {now.Add(-time.Minute).Format(http.TimeFormat), 0}} {
		d, ok := retryDelay(&garmin.RemoteError{StatusCode: 429, RetryAfter: tc.header}, 1, now)
		if !ok || d != tc.delay {
			t.Fatalf("header %q: %v, %v", tc.header, d, ok)
		}
	}
	for _, status := range []int{500, 502, 503, 504} {
		d, ok := retryDelay(&garmin.RemoteError{StatusCode: status, RetryAfter: "not a date"}, 3, now)
		if !ok || d < 8*time.Second || d > 9*time.Second {
			t.Fatalf("fallback: %s, retry=%v", d, ok)
		}
	}
	if _, ok := retryDelay(errors.New("garmin_transport_error"), 1, now); !ok {
		t.Fatal("redacted connection error must retry")
	}
	for _, status := range []int{400, 401, 403, 404, 501} {
		if _, ok := retryDelay(&garmin.RemoteError{StatusCode: status}, 1, now); ok {
			t.Errorf("retried %d", status)
		}
	}
}

func TestRetryBudgetSurvivesRestart(t *testing.T) {
	j := Job{Checkpoint: map[string]any{"attempts": float64(2)}}
	waits, requests := 0, 0
	r := Runner{Wait: func(_ context.Context, d time.Duration) error {
		waits++
		if d != 30*time.Second {
			t.Fatalf("delay %s", d)
		}
		return nil
	}}
	_, deferred, err := r.fetch(t.Context(), nil, &j, func() ([]garmin.Record, error) {
		requests++
		return nil, &garmin.RemoteError{StatusCode: 503, RetryAfter: "30"}
	})
	if err == nil || deferred || waits != 1 || requests != 2 {
		t.Fatalf("requests=%d waits=%d deferred=%v err=%v", requests, waits, deferred, err)
	}
}

func TestSafeFailureCodes(t *testing.T) {
	if got := failureCode(errors.New("sensitive response")); got != "remote_or_import_error" {
		t.Fatal(got)
	}
	if got := failureCode(&garmin.RemoteError{StatusCode: 403}); got != "credential_attention" {
		t.Fatal(got)
	}
	if got := failureCode(errors.New("repeated_activity_page")); got != "repeated_activity_page" {
		t.Fatal(got)
	}
}

func TestCatchupOverlapsLastCompleteDate(t *testing.T) {
	today := time.Date(2027, 1, 3, 0, 0, 0, 0, time.UTC)
	first, last := catchupWindow(today, nil, 14)
	if first.Format(time.DateOnly) != "2026-12-21" || !last.Equal(today) {
		t.Fatalf("%s..%s", first, last)
	}
	latest := today.AddDate(-2, 0, 0)
	first, last = catchupWindow(today, &latest, 7)
	if !first.Equal(latest) || !last.Equal(first.AddDate(0, 0, 365)) {
		t.Fatalf("%s..%s", first, last)
	}
}
