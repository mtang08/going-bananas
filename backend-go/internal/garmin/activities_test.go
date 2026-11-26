package garmin

import (
	"encoding/json"
	"fmt"
	"net/http"
	"slices"
	"strconv"
	"testing"
	"time"
)

func TestActivityPaging(t *testing.T) {
	first := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	last := first.AddDate(0, 0, 1)
	for _, tc := range []struct {
		name      string
		responses []string
		expected  []int
		failure   string
		max       int
	}{
		{"end", []string{`[{"activityId":9007199254740993}]`, `[]`}, []int{0, 1}, "", 3},
		{"repeated", []string{`[{"activityId":7}]`, `[{"activityId":"7"}]`}, []int{0}, "repeated_activity_page", 3},
		{"cap", []string{`[{"activityId":7}]`}, []int{0}, "activity_page_limit", 1},
		{"null", []string{"null"}, nil, "invalid_activity_page_shape", 3},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var count int
			f := setup(t, func(w http.ResponseWriter, r *http.Request) {
				query := r.URL.Query()
				if r.URL.Path != "/activitylist-service/activities/search/activities" || query.Get("start") != strconv.Itoa(count) || query.Get("limit") != "1" || query.Get("startDate") != "2026-01-01" || query.Get("endDate") != "2026-01-02" {
					t.Error("incorrect activity search")
				}
				if count >= len(tc.responses) {
					t.Error("extra page requested")
					http.Error(w, "", 500)
					return
				}
				_, _ = fmt.Fprint(w, tc.responses[count])
				count++
			})
			c := f.open(t)
			var offsets []int
			var failure string
			for p, err := range c.Pages(t.Context(), first, last, 1, tc.max) {
				if err != nil {
					failure = err.Error()
					break
				}
				offsets = append(offsets, p.Offset)
				if tc.name == "end" && p.Offset == 0 && p.Records[0]["activityId"] != json.Number("9007199254740993") {
					t.Error("activity ID lost precision")
				}
			}
			if failure != tc.failure || !slices.Equal(offsets, tc.expected) {
				t.Fatalf("pages %v error %q", offsets, failure)
			}
		})
	}
}

func TestDatasetRequests(t *testing.T) {
	first := time.Date(2026, 3, 7, 0, 0, 0, 0, time.UTC)
	last := first.AddDate(0, 0, 1)
	f := setup(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Accept") != "application/json" {
			t.Error("wrong media type")
		}
		switch r.URL.Path {
		case "/sleep-service/sleep/dailySleepSummariesByDate":
			if r.URL.Query().Get("startDate") != "2026-03-07" || r.URL.Query().Get("endDate") != "2026-03-08" {
				t.Error("wrong sleep range")
			}
			_, _ = fmt.Fprint(w, `[{"sleepTimeSeconds":24000}]`)
		case "/hrv-service/hrv/daily/2026-03-07/2026-03-08":
			_, _ = fmt.Fprint(w, `{"userProfilePk":123,"hrvSummaries":[{"calendarDate":"2026-03-07"}]}`)
		case "/wellness-service/wellness/dailyHeartRate":
			_, _ = fmt.Fprintf(w, `{"date":%q}`, r.URL.Query().Get("date"))
		case "/activity-service/activity/7":
			_, _ = fmt.Fprint(w, `{"activityId":7}`)
		case "/activity-service/activity/7/workouts":
			_, _ = fmt.Fprint(w, `[]`)
		default:
			t.Errorf("unexpected endpoint %s", r.URL.Path)
		}
	})
	c := f.open(t)
	for _, ds := range []string{"sleep", "hrv", "resting_hr"} {
		rows, err := c.FetchRecovery(t.Context(), ds, first, last)
		if err != nil {
			t.Fatal(err)
		}
		switch ds {
		case "sleep":
			if len(rows) != 1 || rows[0]["sleepTimeSeconds"] != json.Number("24000") {
				t.Error("sleep response")
			}
		case "hrv":
			if len(rows) != 1 || rows[0]["userProfilePk"] != json.Number("123") {
				t.Error("HRV owner")
			}
		case "resting_hr":
			if len(rows) != 2 || rows[0]["date"] != "2026-03-07" || rows[1]["date"] != "2026-03-08" {
				t.Error("resting HR dates")
			}
		}
	}
	if _, err := c.ActivityDetail(t.Context(), "7"); err != nil {
		t.Fatal(err)
	}
	if _, err := c.ActivityWorkouts(t.Context(), "7"); err != nil {
		t.Fatal(err)
	}
}
