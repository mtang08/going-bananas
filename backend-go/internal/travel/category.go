package travel

import (
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

// DerivedEvent carries auto-classification and flight fields for persistence.
type DerivedEvent struct {
	AutoCategory                                   string
	FlightConfidence, FlightCode, DestinationLabel *string
}

func knownZone(name *string) *time.Location {
	if name == nil || *name == "" || *name == "Local" {
		return nil
	}
	zone, err := time.LoadLocation(*name)
	if err != nil {
		return nil
	}
	return zone
}

func zoneNames(start, end *string, home *time.Location) (string, string) {
	a, b, _ := LegZones(start, end, home)
	return a.String(), b.String()
}

func timezoneBasis(start, end *string) string {
	_, _, basis := LegZones(start, end, time.UTC)
	return basis
}

func differentOffsets(r Record) bool {
	// A missing endpoint takes the zone of its counterpart; both sides then agree.
	a, b := knownZone(r.StartTZ), knownZone(r.EndTZ)
	if a == nil || b == nil || a.String() == b.String() {
		return false
	}
	_, dep := r.StartAt.In(a).Zone()
	_, arr := r.EndAt.In(b).Zone()
	return dep != arr
}

var (
	flightRoute = regexp.MustCompile(`(?i)^flight:[\s\x0b]*([a-z0-9]{2})[\s\x0b]?([0-9]{1,4})[\s\x0b]+from[\s\x0b]+[a-z]{3}[\s\x0b]+to[\s\x0b]+([a-z]{3})\b`)
	flightCode  = regexp.MustCompile(`([A-Z0-9]{2})[\p{Z}\s\x0b\x1c-\x1f]?(\p{Nd}{1,4})`)
	flightTo    = regexp.MustCompile(`(?i)^flight to (.+?)(?:[\p{Z}\s\x0b\x1c-\x1f]*\(|$)`)
	lodging     = regexp.MustCompile(`(?i)stay at|hotel|inn|resort|suites?|airbnb|check-in`)
	ground      = regexp.MustCompile(`(?i)train|rail|amtrak|bus|ferry|car rental|rental car`)
)

func hasWord(re *regexp.Regexp, title string) bool {
	for _, m := range re.FindAllStringIndex(title, -1) {
		if bounded(title, m[0], m[1]) {
			return true
		}
	}
	return false
}

func parseFlight(title string) (code, label *string) {
	if m := flightRoute.FindStringSubmatch(title); m != nil && len(m[0]) == utf8.RuneCountInString(m[0]) {
		c, l := strings.ToUpper(m[1])+" "+m[2], strings.ToUpper(m[3])
		return &c, &l
	}
	for _, m := range flightCode.FindAllStringSubmatchIndex(title, -1) {
		if bounded(title, m[0], m[1]) {
			c := title[m[2]:m[3]] + " " + title[m[4]:m[5]]
			code = &c
			break
		}
	}
	if m := flightTo.FindStringSubmatch(title); m != nil {
		l := truncateText(strings.TrimSpace(m[1]), 120)
		if l != "" {
			label = &l
		}
	}
	return code, label
}

// DeriveEvent classifies a normalized record using its original endpoint zones.
func DeriveEvent(r Record, home *time.Location) DerivedEvent {
	title := ""
	if r.Summary != nil {
		title = strings.TrimSpace(*r.Summary)
	}
	gmail := r.EventType == "fromGmail"
	mentionsFlight := strings.Contains(strings.ToLower(title), "flight")
	out := DerivedEvent{AutoCategory: "other"}
	if mentionsFlight {
		out.FlightCode, out.DestinationLabel = parseFlight(title)
	}
	startsFlight := strings.HasPrefix(strings.ToLower(title), "flight") && bounded(title, 0, len("flight"))
	switch {
	case r.EventType == "outOfOffice":
		out.AutoCategory = "out_of_office"
	case gmail && !r.AllDay && (startsFlight || out.FlightCode != nil || r.Transparency == "transparent" && differentOffsets(r)):
		high := "high"
		out.AutoCategory, out.FlightConfidence = "flight", &high
	case gmail && hasWord(lodging, title) && (r.AllDay || r.EndAt.Sub(*r.StartAt) >= 20*time.Hour):
		out.AutoCategory = "lodging"
	case gmail && hasWord(ground, title):
		out.AutoCategory = "ground_travel"
	case gmail:
		out.AutoCategory = "reservation"
	case !r.AllDay && mentionsFlight && (out.FlightCode != nil || differentOffsets(r)):
		medium := "medium"
		out.AutoCategory, out.FlightConfidence = "flight", &medium
	}
	if out.AutoCategory == "flight" && !mentionsFlight {
		out.FlightCode, out.DestinationLabel = parseFlight(title)
	}
	return out
}

// LegZones resolves the display locations and describes the original calendar evidence.
func LegZones(start, end *string, home *time.Location) (departure, arrival *time.Location, basis string) {
	departure, arrival = knownZone(start), knownZone(end)
	basis = "fallback"
	if departure != nil && arrival != nil {
		basis = "calendar_endpoints"
		if departure.String() == arrival.String() {
			basis = "calendar_display"
		}
	}
	if departure == nil {
		departure = arrival
	}
	if departure == nil {
		departure = home
	}
	if arrival == nil {
		arrival = departure
	}
	return
}
