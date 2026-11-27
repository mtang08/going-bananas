package googlecalendar

import (
	"context"
	"encoding/json"
	"fmt"
	"maps"
	"math"
	"net/url"
	"regexp"
	"slices"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/mtang08/going-bananas/backend-go/internal/travel"
)

var flightNumber = regexp.MustCompile(`[A-Z0-9]{2}[\s\p{Z}\x0b]?[\p{Nd}]{1,4}`)
var titlePiece = regexp.MustCompile(`\x00|[\p{L}\p{Nl}\p{No}]+(?:-[\p{L}\p{Nl}\p{No}]+)*|\p{Nd}+|.`)
var iata = regexp.MustCompile(`^[A-Z]{3}$`)
var privateWords = regexp.MustCompile(`<X>(?:\s*<X>)+`)

func maskFlight(s string) string {
	var b strings.Builder
	last := 0
	word := func(r rune) bool { return unicode.IsLetter(r) || unicode.IsNumber(r) || r == '_' }
	for _, pair := range flightNumber.FindAllStringIndex(s, -1) {
		before, _ := utf8.DecodeLastRuneInString(s[:pair[0]])
		after, _ := utf8.DecodeRuneInString(s[pair[1]:])
		if word(before) || word(after) {
			continue
		}
		b.WriteString(s[last:pair[0]])
		b.WriteByte(0)
		last = pair[1]
	}
	b.WriteString(s[last:])
	return b.String()
}
func maskPiece(s string) string {
	switch s {
	case "\x00":
		return "<AA> <N>"
	case "Flight", "to", "from", "Stay", "at", "Hotel", "Check-in", "Checkout", "Train", "Bus", "Reservation", "Rental", "Car", "Out", "of", "office", "(", ")", "-", ":", ",", "→", "/":
		return s
	}
	if iata.MatchString(s) {
		return "<IATA>"
	}
	r, _ := utf8.DecodeRuneInString(s)
	if unicode.IsDigit(r) {
		return "<N>"
	}
	if unicode.IsLetter(r) {
		return "<X>"
	}
	return ""
}
func maskTitle(s string) string {
	if strings.TrimSpace(s) == "" {
		return "-"
	}
	if strings.Contains(strings.ToLower(s), "flight") {
		s = maskFlight(s)
	}
	var words []string
	for _, word := range strings.Fields(s) {
		low := strings.ToLower(word)
		if strings.Contains(low, "@") || strings.Contains(low, "http") || strings.Contains(low, "www") {
			words = append(words, "<X>")
			continue
		}
		masked := titlePiece.ReplaceAllStringFunc(word, maskPiece)
		if masked != "" {
			words = append(words, masked)
		}
	}
	return privateWords.ReplaceAllString(strings.Join(words, " "), "<X>")
}
func textOr(s *string, fallback string) string {
	if s != nil {
		return *s
	}
	return fallback
}
func zoneName(s *string) string {
	if s == nil || *s == "" || *s == "Local" {
		return "-"
	}
	if _, err := time.LoadLocation(*s); err != nil {
		return "-"
	}
	return *s
}
func probeLines(calendars []map[string]any, pages []json.RawMessage) ([]string, error) {
	lines := make([]string, 0, len(calendars)+len(pages)+1)
	for _, cal := range calendars {
		primary := cal["primary"] == true
		name := "<X>"
		title, _ := cal["summary"].(string)
		if primary {
			name = "<primary>"
		} else if strings.Contains(title, "@") {
			name = "<email>"
		}
		role, _ := cal["accessRole"].(string)
		switch role {
		case "freeBusyReader", "reader", "writer", "owner":
		default:
			role = "-"
		}
		lines = append(lines, fmt.Sprintf("calendar name=%s access_role=%s primary=%t", name, role, primary))
	}
	counts := map[string]int{}
	var diff, missing, total int
	for _, raw := range pages {
		var page struct{ Items []map[string]any }
		if err := json.Unmarshal(raw, &page); err != nil {
			return nil, failure("gcal_invalid_response")
		}
		for _, row := range page.Items {
			r, err := travel.NormalizeEvent(row)
			if err != nil {
				return nil, failure("gcal_invalid_response")
			}
			if r == nil {
				continue
			}
			typ := r.EventType
			switch typ {
			case "default", "fromGmail", "outOfOffice", "focusTime", "workingLocation", "birthday":
			default:
				typ = "unknown"
			}
			counts[typ]++
			total++
			from, to := zoneName(r.StartTZ), zoneName(r.EndTZ)
			kind := "timed"
			var hours float64
			if r.AllDay {
				kind = "all_day"
				a, _ := time.Parse(time.DateOnly, *r.StartDate)
				b, _ := time.Parse(time.DateOnly, *r.EndDate)
				hours = float64(b.Unix()-a.Unix()) / 3600
			} else {
				hours = float64(r.EndAt.UnixMicro()-r.StartAt.UnixMicro()) / 3.6e9
				if from == "-" || to == "-" {
					missing++
				} else if from != to {
					diff++
				}
			}
			location, _ := row["location"].(string)
			lines = append(lines, fmt.Sprintf("event type=%s kind=%s start_tz=%s end_tz=%s transparency=%s response=%s dur_h=%.1f title=\"%s\" location=\"%s\"", typ, kind, from, to, r.Transparency, textOr(r.ResponseStatus, "-"), math.RoundToEven(hours*2)/2, maskTitle(textOr(r.Summary, "")), maskTitle(location)))
		}
	}
	var end strings.Builder
	fmt.Fprintf(&end, "summary events=%d", total)
	for _, key := range slices.Sorted(maps.Keys(counts)) {
		fmt.Fprintf(&end, " %s=%d", key, counts[key])
	}
	fmt.Fprintf(&end, " tz_differs=%d tz_missing=%d", diff, missing)
	return append(lines, end.String()), nil
}

// Probe requests calendar metadata and emits only the redacted diagnostic report.
func (c *Client) Probe(ctx context.Context, days int) ([]string, error) {
	if days < 1 || days > 180 {
		return nil, failure("invalid_date_window")
	}
	creds, err := c.authorize(ctx)
	if err != nil {
		return nil, err
	}
	u, err := url.Parse(c.config.CalendarsURL)
	if err != nil {
		return nil, failure("gcal_remote_error")
	}
	u.RawQuery = url.Values{"fields": {"items(summary,accessRole,primary)"}, "maxResults": {"250"}}.Encode()
	body, err := c.get(ctx, u.String(), &creds)
	if err != nil {
		return nil, err
	}
	parsed, err := pageBody(body, "")
	if err != nil {
		return nil, err
	}
	calendars := make([]map[string]any, len(parsed.Items))
	for i, item := range parsed.Items {
		if err = json.Unmarshal(item, &calendars[i]); err != nil {
			return nil, failure("gcal_invalid_response")
		}
	}
	now := c.config.Now().UTC()
	pages, err := c.Fetch(ctx, travel.Window{From: now, Until: now.AddDate(0, 0, days)})
	if err != nil {
		return nil, err
	}
	return probeLines(calendars, pages)
}
