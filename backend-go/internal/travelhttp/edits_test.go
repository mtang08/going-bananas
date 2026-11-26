package travelhttp

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"testing"
)

// Cases exercised through the FastAPI routes; field order and JSON parse errors
// are part of the response consumed by the dashboard.
func TestTravelEditValidation(t *testing.T) {
	h := Handler{}
	cases := []struct {
		method, path, key, id, body string
		want                        []Field
	}{
		{"PATCH", "/trips/not-a-uuid", "trip_id", "not-a-uuid", `{"day_availability":[{"availability":"slow","x":1},5],"status":"bogus","y":1}`, []Field{
			{"path.trip_id", "Input should be a valid UUID, invalid character: found `n` at 0"},
			{"body.expected_version", "Field required"}, {"body.status", "Value error, Status must be confirmed, dismissed, or pending"},
			{"body.day_availability.0.date", "Field required"}, {"body.day_availability.0.availability", "Value error, Unknown availability"},
			{"body.day_availability.0.x", "Extra inputs are not permitted"}, {"body.day_availability.1", "Input should be a valid dictionary or object to extract fields from"},
			{"body.y", "Extra inputs are not permitted"},
		}},
		{"PATCH", "/trips/not-a-uuid", "trip_id", "not-a-uuid", "{", []Field{{"body.1", "JSON decode error"}}},
		{"POST", "/trips", "", "", `{"start_date":true,"end_date":"not-a-day","destination_tz":"Unknown/Local","running_access":"xx","day_availability":null}`, []Field{
			{"body.start_date", "Input should be a valid date"}, {"body.end_date", "Input should be a valid date or datetime, input is too short"},
			{"body.destination_tz", "Value error, Unknown timezone"}, {"body.running_access", "Value error, Unknown running access"}, {"body.day_availability", "Input should be a valid list"},
		}},
		{"PATCH", "/google-calendar/events/abc", "event_id", "abc", `{"expected_version":1.5,"category":"x"}`, []Field{
			{"path.event_id", "Input should be a valid UUID, invalid length: found 3"},
			{"body.expected_version", "Input should be a valid integer, got a number with a fractional part"}, {"body.category", "Value error, Unknown category"},
		}},
	}
	for _, tc := range cases {
		t.Run(tc.path, func(t *testing.T) {
			r := httptest.NewRequest(tc.method, tc.path, strings.NewReader(tc.body))
			w := httptest.NewRecorder()
			if tc.key != "" {
				r.SetPathValue(tc.key, tc.id)
			}
			switch tc.key {
			case "trip_id":
				h.patchTrip(w, r)
			case "event_id":
				h.patchEvent(w, r)
			default:
				h.createTrip(w, r)
			}
			var result struct {
				Error struct {
					Fields []Field
					Code   string
				}
			}
			if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil || w.Code != http.StatusUnprocessableEntity || result.Error.Code != "validation_error" || !slices.Equal(result.Error.Fields, tc.want) {
				t.Fatalf("status %d, body %s", w.Code, w.Body.String())
			}
		})
	}
}

func TestEditNullAndOmitted(t *testing.T) {
	req, fields := readEdit(strings.NewReader(`{"expected_version":"1.0","end_date":null,"day_availability":[],"start_date":"2026-11-25T00:00:00+03:00"}`), "patchTrip")
	p := req.trip
	if len(fields) > 0 || !p.End.Set || p.End.Value != nil || p.Label.Set || p.Days.Value == nil || len(*p.Days.Value) != 0 || p.Start.Value == nil || *p.Start.Value != "2026-11-25" || p.ExpectedVersion != 1 {
		t.Fatalf("%+v, %+v", p, fields)
	}
}
