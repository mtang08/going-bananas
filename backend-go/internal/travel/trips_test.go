package travel

import (
	"slices"
	"testing"
	"time"
)

func TestOpenTripBoundaryAcrossSpringDST(t *testing.T) {
	home, err := time.LoadLocation("America/New_York")
	if err != nil {
		t.Fatal(err)
	}
	// The departure is 30 civil dates later, even though the wall clocks differ.
	first := time.Date(2027, 2, 20, 0, 1, 0, 0, home)
	for _, tc := range []struct{ days, trips int }{{30, 1}, {31, 2}} {
		next := time.Date(2027, 2, 20+tc.days, 23, 58, 0, 0, home)
		legs := []flightLeg{
			{id: "second", depart: next, arrive: next.Add(time.Minute), from: home, to: home, confidence: "low"},
			{id: "first", depart: first, arrive: first.Add(time.Minute), from: home, to: home, confidence: "low"},
		}
		trips := detectTrips(legs, home)
		if len(trips) != tc.trips || trips[0].legs[0].id != "first" || (trips[0].End == nil) != (tc.trips == 2) {
			t.Fatalf("gap of %d dates: %+v", tc.days, trips)
		}
	}
}

func TestSelectDuplicateFlights(t *testing.T) {
	ny, la, code := "America/New_York", "America/Los_Angeles", "ZZ 721"
	home, err := time.LoadLocation(ny)
	if err != nil {
		t.Fatal(err)
	}
	endpoints := calendarFlight{id: "a", code: &code, startZone: &ny, endZone: &la, active: true, eventType: "default"}
	display := endpoints
	display.id, display.eventType, display.endZone = "b", "fromGmail", &ny
	removed := endpoints
	removed.id, removed.active, removed.eventType = "c", false, "fromGmail"
	got := selectLegs([]calendarFlight{endpoints, display, removed}, home)
	if len(got) != 1 || got[0].id != "a" || !slices.Equal(got[0].aliases, []string{"b", "c"}) {
		t.Fatalf("representative and aliases: %+v", got)
	}
	display.eventType = "default"
	if got := selectLegs([]calendarFlight{endpoints, display}, home); len(got) != 2 {
		t.Fatalf("same-type legs: %+v", got)
	}
}

func TestDismissedOwnerCanClaimMultipleCandidates(t *testing.T) {
	dismissed := &storedTrip{id: "b", status: "dismissed", start: "2027-02-01", claimed: true}
	open := &storedTrip{id: "a", status: "pending", start: "2027-01-01"}
	owners := map[string]*storedTrip{"prior": dismissed, "active": open}
	legs := []flightLeg{{id: "active"}, {id: "replacement", aliases: []string{"prior"}}}
	if got := preferredOwner(legs, owners); got != dismissed {
		t.Fatalf("preferred trip = %+v", got)
	}
}
