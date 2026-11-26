package travel

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

type calendarFlight struct {
	id, eventType, hash                         string
	code, startZone, endZone, label, confidence *string
	start, end                                  time.Time
	active                                      bool
}

func flightLegs(ctx context.Context, tx pgx.Tx, home *time.Location) ([]flightLeg, error) {
	rows, err := tx.Query(ctx, `SELECT id::text,event_type,content_hash,flight_code,start_tz,end_tz,destination_label,
		flight_confidence,start_at,end_at,
		(removed_at IS NULL AND category='flight' AND response_status IS DISTINCT FROM 'declined')
		FROM gcal_events WHERE (category='flight' OR auto_category='flight') AND start_at IS NOT NULL AND end_at IS NOT NULL ORDER BY id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var flights []calendarFlight
	for rows.Next() {
		var f calendarFlight
		if err := rows.Scan(&f.id, &f.eventType, &f.hash, &f.code, &f.startZone, &f.endZone, &f.label, &f.confidence, &f.start, &f.end, &f.active); err != nil {
			return nil, err
		}
		flights = append(flights, f)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return selectLegs(flights, home), nil
}

func preferFlight(a, b calendarFlight) bool {
	aEndpoints := timezoneBasis(a.startZone, a.endZone) == "calendar_endpoints"
	bEndpoints := timezoneBasis(b.startZone, b.endZone) == "calendar_endpoints"
	if aEndpoints != bEndpoints {
		return aEndpoints
	}
	if (a.eventType == "fromGmail") != (b.eventType == "fromGmail") {
		return a.eventType == "fromGmail"
	}
	return a.id < b.id
}

func (f calendarFlight) leg(home *time.Location) flightLeg {
	from, to := zoneNames(f.startZone, f.endZone, home)
	fromLoc, _ := time.LoadLocation(from)
	toLoc, _ := time.LoadLocation(to)
	if from == home.String() {
		fromLoc = home
	}
	if to == home.String() {
		toLoc = home
	}
	confidence := "medium"
	if from == to {
		confidence = "low"
	} else if f.confidence != nil {
		confidence = *f.confidence
	}
	return flightLeg{id: f.id, hash: f.hash, depart: f.start, arrive: f.end, from: fromLoc, to: toLoc, label: f.label, confidence: confidence}
}

// Only mixed event types are alternate calendar representations of one flight.
// Same-type overlapping events keep their independent identities.
func selectLegs(flights []calendarFlight, home *time.Location) []flightLeg {
	type flightKey struct {
		code, id   string
		start, end time.Time
	}
	groups := make(map[flightKey][]calendarFlight)
	for _, f := range flights {
		key := flightKey{id: f.id}
		if f.code != nil && *f.code != "" {
			key = flightKey{code: *f.code, start: f.start.UTC(), end: f.end.UTC()}
		}
		groups[key] = append(groups[key], f)
	}
	var legs []flightLeg
	for _, copies := range groups {
		mixed := false
		var preferred *calendarFlight
		for i := range copies {
			f := &copies[i]
			mixed = mixed || f.eventType != copies[0].eventType
			if f.active && (preferred == nil || preferFlight(*f, *preferred)) {
				preferred = f
			}
		}
		if preferred == nil {
			continue
		}
		if !mixed {
			for _, f := range copies {
				if f.active {
					legs = append(legs, f.leg(home))
				}
			}
			continue
		}
		leg := preferred.leg(home)
		for _, f := range copies {
			if f.id != preferred.id {
				leg.aliases = append(leg.aliases, f.id)
			}
		}
		legs = append(legs, leg)
	}
	return legs
}
