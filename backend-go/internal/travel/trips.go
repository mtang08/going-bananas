package travel

import (
	"cmp"
	"slices"
	"time"
)

type flightLeg struct {
	id, hash, confidence string
	depart, arrive       time.Time
	from, to             *time.Location
	label                *string
	aliases              []string
}

type tripStop struct {
	Label   *string `json:"label"`
	Zone    string  `json:"tz"`
	Arrival string  `json:"arrive_date"`
}

type detectedTrip struct {
	Start      string     `json:"start_date"`
	End        *string    `json:"end_date"`
	Label      *string    `json:"destination_label"`
	Zone       string     `json:"destination_tz"`
	Confidence string     `json:"confidence"`
	Stops      []tripStop `json:"stops"`
}

type tripCandidate struct {
	detectedTrip
	legs []flightLeg
}

// Compare civil days across DST without treating a calendar day as 24 local hours.
func civilDay(instant time.Time, zone *time.Location) time.Time {
	y, m, d := instant.In(zone).Date()
	return time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
}

func away(at time.Time, zone, home *time.Location) bool {
	_, there := at.In(zone).Zone()
	_, here := at.In(home).Zone()
	return there != here
}

func (l flightLeg) arrivesAway(home *time.Location) bool {
	return l.from.String() != l.to.String() && away(l.arrive, l.to, home)
}

func (l flightLeg) stop() tripStop {
	return tripStop{l.label, l.to.String(), l.arrive.In(l.to).Format(time.DateOnly)}
}

func journeys(legs []flightLeg) [][]flightLeg {
	ordered := slices.Clone(legs)
	slices.SortFunc(ordered, func(a, b flightLeg) int {
		if c := a.depart.Compare(b.depart); c != 0 {
			return c
		}
		return cmp.Compare(a.id, b.id)
	})
	var groups [][]flightLeg
	for _, leg := range ordered {
		if n := len(groups); n > 0 {
			last := groups[n-1]
			if gap := leg.depart.Sub(last[len(last)-1].arrive); gap >= 0 && gap <= 24*time.Hour {
				groups[n-1] = append(last, leg)
				continue
			}
		}
		groups = append(groups, []flightLeg{leg})
	}
	return groups
}

func candidate(legs []flightLeg, stops []tripStop, home *time.Location, closed bool) tripCandidate {
	first, last := legs[0], legs[len(legs)-1]
	d := detectedTrip{Start: first.depart.In(first.from).Format(time.DateOnly), Label: stops[0].Label, Zone: stops[0].Zone, Confidence: "high", Stops: stops}
	hasAway := false
	for _, leg := range legs {
		hasAway = hasAway || leg.arrivesAway(home)
		if leg.confidence == "low" || leg.from.String() == leg.to.String() {
			d.Confidence = "low"
		} else if leg.confidence == "medium" && d.Confidence == "high" {
			d.Confidence = "medium"
		}
	}
	if closed {
		end := max(d.Start, last.arrive.In(last.to).Format(time.DateOnly))
		d.End = &end
		if !hasAway && d.Confidence == "high" {
			d.Confidence = "medium"
		}
	} else {
		d.Confidence = "low"
	}
	return tripCandidate{d, legs}
}

func detectTrips(legs []flightLeg, home *time.Location) []tripCandidate {
	var result []tripCandidate
	var open []flightLeg
	var stops []tripStop
	for _, group := range journeys(legs) {
		first, last := group[0], group[len(group)-1]
		if len(open) > 0 && civilDay(first.depart, home).After(civilDay(open[len(open)-1].arrive, home).AddDate(0, 0, 30)) {
			result = append(result, candidate(open, stops, home, false))
			open, stops = nil, nil
		}
		if len(open) > 0 {
			open = append(open, group...)
			if last.arrivesAway(home) {
				stops = append(stops, last.stop())
			} else {
				result = append(result, candidate(open, stops, home, true))
				open, stops = nil, nil
			}
			continue
		}
		if last.from.String() != last.to.String() && !last.arrivesAway(home) {
			if first.from.String() != first.to.String() && away(first.depart, first.from, home) {
				continue
			}
			var awayStops []tripStop
			for _, leg := range group[:len(group)-1] {
				if leg.arrivesAway(home) {
					awayStops = append(awayStops, leg.stop())
				}
			}
			if len(awayStops) > 0 {
				result = append(result, candidate(group, awayStops, home, true))
				continue
			}
		}
		open, stops = group, []tripStop{last.stop()}
	}
	if len(open) > 0 {
		result = append(result, candidate(open, stops, home, false))
	}
	return result
}
