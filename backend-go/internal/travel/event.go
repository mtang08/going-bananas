// Package travel projects Google Calendar events and reconciles trips.
package travel

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"regexp"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
)

// Record contains only the provider fields used for calendar reconciliation.
type Record struct {
	GoogleEventID, EventType, GoogleStatus string
	Summary                                *string
	LocationCodes                          []string
	AllDay                                 bool
	StartAt, EndAt                         *time.Time
	StartDate, EndDate, StartTZ, EndTZ     *string
	Transparency                           string
	ResponseStatus                         *string
	Busy                                   bool
	GoogleUpdatedAt                        *string // Original provider timestamp; excluded from content_hash.
	UpdatedAt                              *time.Time
	ContentHash                            string
}

var errInvalidEvent = errors.New("gcal_invalid_response")

func optionalText(value any, max int) (*string, error) {
	if value == nil {
		return nil, nil
	}
	s, ok := value.(string)
	if !ok || (max > 0 && utf8.RuneCountInString(s) > max) {
		return nil, errInvalidEvent
	}
	return &s, nil
}

func truncateText(s string, limit int) string {
	for i := range s {
		if limit == 0 {
			return s[:i]
		}
		limit--
	}
	return s
}

func instant(value any) (*time.Time, error) {
	s, ok := value.(string)
	if !ok {
		return nil, errInvalidEvent
	}
	t, err := time.Parse(time.RFC3339Nano, s)
	_, offset := t.Zone()
	if err != nil || offset <= -24*3600 || offset >= 24*3600 || t.Year() < 1 || t.UTC().Year() < 1 || t.UTC().Year() > 9999 {
		return nil, errInvalidEvent
	}
	t = t.UTC().Truncate(time.Microsecond)
	return &t, nil
}

func eventDate(value any) (*string, error) {
	s, ok := value.(string)
	if !ok {
		return nil, errInvalidEvent
	}
	for _, layout := range []string{time.DateOnly, "20060102"} {
		t, err := time.Parse(layout, s)
		if err == nil && t.Year() > 0 {
			date := t.Format(time.DateOnly)
			return &date, nil
		}
	}
	return nil, errInvalidEvent
}

func selfResponse(value any) (*string, error) {
	if value == nil {
		return nil, nil
	}
	attendees, ok := value.([]any)
	if !ok {
		return nil, errInvalidEvent
	}
	var first map[string]any
	for _, entry := range attendees {
		a, ok := entry.(map[string]any)
		if !ok {
			return nil, errInvalidEvent
		}
		if first == nil && a["self"] == true {
			first = a
		}
	}
	s, _ := first["responseStatus"].(string)
	switch s {
	case "needsAction", "declined", "tentative", "accepted":
		return &s, nil
	}
	return nil, nil
}

var iata = regexp.MustCompile(`[A-Z]{3}`)

// Python word boundaries include Unicode letters, numbers and underscore.
func wordRune(r rune) bool { return r == '_' || unicode.IsLetter(r) || unicode.IsNumber(r) }

func bounded(s string, lo, hi int) bool {
	before, _ := utf8.DecodeLastRuneInString(s[:lo])
	after, _ := utf8.DecodeRuneInString(s[hi:])
	return !wordRune(before) && !wordRune(after)
}

func locationCodes(value any) []string {
	s, _ := value.(string)
	codes := []string{}
	for _, match := range iata.FindAllStringIndex(s, -1) {
		if bounded(s, match[0], match[1]) {
			codes = append(codes, s[match[0]:match[1]])
			if len(codes) == 4 {
				break
			}
		}
	}
	return codes
}

// NormalizeEvent skips cancelled events and incomplete endpoint pairs. Malformed
// provider fields return the same redacted failure code as the Python adapter.
func NormalizeEvent(raw map[string]any) (*Record, error) {
	id, ok := raw["id"].(string)
	if !ok || id == "" {
		return nil, errInvalidEvent
	}
	if raw["status"] == "cancelled" || raw["start"] == nil || raw["end"] == nil {
		return nil, nil
	}
	start, ok := raw["start"].(map[string]any)
	end, okEnd := raw["end"].(map[string]any)
	if !ok || !okEnd {
		return nil, errInvalidEvent
	}
	r := Record{GoogleEventID: id, GoogleStatus: "confirmed", EventType: "default", Transparency: "opaque"}
	var err error
	if updated := raw["updated"]; updated != nil {
		r.UpdatedAt, err = instant(updated)
		if err != nil {
			return nil, err
		}
		s := updated.(string)
		r.GoogleUpdatedAt = &s
	}
	_, startDate := start["date"]
	_, endDate := end["date"]
	_, startAt := start["dateTime"]
	_, endAt := end["dateTime"]
	switch {
	case startDate && endDate:
		r.AllDay = true
		r.StartDate, err = eventDate(start["date"])
		if err == nil {
			r.EndDate, err = eventDate(end["date"])
		}
	case startAt && endAt:
		r.StartAt, err = instant(start["dateTime"])
		if err == nil {
			r.EndAt, err = instant(end["dateTime"])
		}
	default:
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	r.ResponseStatus, err = selfResponse(raw["attendees"])
	if err != nil {
		return nil, err
	}
	eventType, err := optionalText(raw["eventType"], 0)
	if err != nil {
		return nil, err
	}
	if eventType != nil && *eventType != "" {
		r.EventType = truncateText(*eventType, 32)
	}
	r.StartTZ, err = optionalText(start["timeZone"], 64)
	if err != nil {
		return nil, err
	}
	r.EndTZ, err = optionalText(end["timeZone"], 64)
	if err != nil {
		return nil, err
	}
	if summary, ok := raw["summary"].(string); ok {
		r.Summary = &summary
	}
	if raw["status"] == "tentative" {
		r.GoogleStatus = "tentative"
	}
	if raw["transparency"] == "transparent" {
		r.Transparency = "transparent"
	}
	r.LocationCodes = locationCodes(raw["location"])
	r.Busy = r.Transparency != "transparent" && (r.ResponseStatus == nil || *r.ResponseStatus != "declined")
	body, err := canonicaljson.Coaching(r.hashFields())
	if err != nil {
		return nil, errInvalidEvent
	}
	sum := sha256.Sum256(body)
	r.ContentHash = hex.EncodeToString(sum[:])
	return &r, nil
}

func (r Record) hashFields() map[string]any {
	return map[string]any{
		"google_event_id": r.GoogleEventID, "event_type": r.EventType, "google_status": r.GoogleStatus,
		"summary": r.Summary, "location_codes": r.LocationCodes, "all_day": r.AllDay,
		"start_at": r.StartAt, "end_at": r.EndAt, "start_date": r.StartDate, "end_date": r.EndDate,
		"start_tz": r.StartTZ, "end_tz": r.EndTZ, "transparency": r.Transparency, "response_status": r.ResponseStatus, "busy": r.Busy,
	}
}
