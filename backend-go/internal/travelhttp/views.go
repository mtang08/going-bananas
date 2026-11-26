package travelhttp

import (
	"context"
	"encoding/json"
	"slices"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/travel"
)

type EventView struct {
	ID               uuid.UUID  `json:"id"`
	EventType        string     `json:"event_type"`
	Summary          *string    `json:"summary"`
	AllDay           bool       `json:"all_day"`
	StartAt          *string    `json:"start_at"`
	EndAt            *string    `json:"end_at"`
	StartDate        *string    `json:"start_date"`
	EndDate          *string    `json:"end_date"`
	StartTZ          *string    `json:"start_tz"`
	EndTZ            *string    `json:"end_tz"`
	LocalDate        string     `json:"local_date"`
	Busy             bool       `json:"busy"`
	ResponseStatus   *string    `json:"response_status"`
	Category         string     `json:"category"`
	CategorySource   string     `json:"category_source"`
	AutoCategory     string     `json:"auto_category"`
	FlightCode       *string    `json:"flight_code"`
	DestinationLabel *string    `json:"destination_label"`
	LocationCodes    []string   `json:"location_codes"`
	Removed          bool       `json:"removed"`
	TripID           *uuid.UUID `json:"trip_id"`
	Version          int        `json:"version"`
}

type LegView struct {
	EventID       uuid.UUID `json:"event_id"`
	Seq           int       `json:"seq"`
	Summary       *string   `json:"summary"`
	FlightCode    *string   `json:"flight_code"`
	DepartAt      *string   `json:"depart_at"`
	ArriveAt      *string   `json:"arrive_at"`
	DepartTZ      string    `json:"depart_tz"`
	ArriveTZ      string    `json:"arrive_tz"`
	TimezoneBasis string    `json:"timezone_basis"`
	DepartLocal   *string   `json:"depart_local"`
	ArriveLocal   *string   `json:"arrive_local"`
	Removed       bool      `json:"removed"`
}

type TripView struct {
	ID               uuid.UUID       `json:"id"`
	Status           string          `json:"status"`
	StartDate        string          `json:"start_date"`
	EndDate          *string         `json:"end_date"`
	DestinationLabel *string         `json:"destination_label"`
	DestinationTZ    string          `json:"destination_tz"`
	Source           string          `json:"source"`
	Confidence       *string         `json:"confidence"`
	Edited           bool            `json:"edited"`
	ReviewReason     *string         `json:"review_reason"`
	Detected         json.RawMessage `json:"detected"`
	RunningAccess    *string         `json:"running_access"`
	GymAccess        *string         `json:"gym_access"`
	DayAvailability  json.RawMessage `json:"day_availability"`
	TravelDays       []string        `json:"travel_days"`
	Legs             []LegView       `json:"legs"`
	Version          int             `json:"version"`
}

func athleteHome(ctx context.Context, q db.DBTX) (*time.Location, error) {
	name, err := db.New(q).CalendarTimezone(ctx)
	if err != nil {
		return nil, err
	}
	if name == "" {
		name = "America/New_York"
	}
	return time.LoadLocation(name)
}

// Event and itinerary views use Python isoformat(), including six fractional
// digits for a nonzero microsecond and an explicit offset even in UTC.
func isoTime(t *time.Time, z *time.Location) *string {
	if t == nil {
		return nil
	}
	layout := "2006-01-02T15:04:05"
	if t.Nanosecond() != 0 {
		layout += ".000000"
	}
	s := t.In(z).Format(layout + "-07:00")
	return &s
}

const eventSelect = `SELECT e.id,e.event_type,e.summary,e.all_day,e.start_at,e.end_at,e.start_date::text,e.end_date::text,
	e.start_tz,e.end_tz,e.busy,e.response_status,e.category,e.category_source,e.auto_category,e.flight_code,
	e.destination_label,e.location_codes,e.removed_at IS NOT NULL,l.trip_id,e.version
	FROM gcal_events e LEFT JOIN trip_legs l ON l.gcal_event_id=e.id`

func scanEvent(row pgx.Row, home *time.Location) (EventView, error) {
	var e EventView
	var start, end *time.Time
	err := row.Scan(&e.ID, &e.EventType, &e.Summary, &e.AllDay, &start, &end, &e.StartDate, &e.EndDate, &e.StartTZ, &e.EndTZ,
		&e.Busy, &e.ResponseStatus, &e.Category, &e.CategorySource, &e.AutoCategory, &e.FlightCode, &e.DestinationLabel, &e.LocationCodes, &e.Removed, &e.TripID, &e.Version)
	if err != nil {
		return e, err
	}
	e.StartAt, e.EndAt = isoTime(start, time.UTC), isoTime(end, time.UTC)
	if e.AllDay {
		e.LocalDate = *e.StartDate
	} else {
		e.LocalDate = start.In(home).Format(time.DateOnly)
	}
	return e, nil
}

func eventByID(ctx context.Context, q db.DBTX, id uuid.UUID, home *time.Location) (EventView, error) {
	return scanEvent(q.QueryRow(ctx, eventSelect+" WHERE e.id=$1", id), home)
}

const tripSelect = `SELECT id,status,start_date::text,end_date::text,destination_label,destination_tz,source,confidence,edited,review_reason,detected,
	running_access,gym_access,day_availability,version FROM trips`

func scanTrip(row pgx.Row) (TripView, error) {
	t := TripView{Legs: []LegView{}, TravelDays: []string{}}
	err := row.Scan(&t.ID, &t.Status, &t.StartDate, &t.EndDate, &t.DestinationLabel, &t.DestinationTZ, &t.Source, &t.Confidence, &t.Edited,
		&t.ReviewReason, &t.Detected, &t.RunningAccess, &t.GymAccess, &t.DayAvailability, &t.Version)
	return t, err
}

func tripByID(ctx context.Context, q db.DBTX, id uuid.UUID, home *time.Location) (TripView, error) {
	t, err := scanTrip(q.QueryRow(ctx, tripSelect+" WHERE id=$1", id))
	if err != nil {
		return t, err
	}
	items := []TripView{t}
	err = loadLegs(ctx, q, items, home)
	return items[0], err
}

func loadLegs(ctx context.Context, q db.DBTX, trips []TripView, home *time.Location) error {
	if len(trips) == 0 {
		return nil
	}
	ids := make([]uuid.UUID, len(trips))
	owners := make(map[uuid.UUID]*TripView, len(trips))
	for i := range trips {
		ids[i] = trips[i].ID
		owners[ids[i]] = &trips[i]
	}
	rows, err := q.Query(ctx, `SELECT l.trip_id,e.id,l.seq,e.summary,e.flight_code,e.start_at,e.end_at,e.start_tz,e.end_tz,
		e.removed_at IS NOT NULL OR e.category!='flight' OR e.response_status IS NOT DISTINCT FROM 'declined' OR e.start_at IS NULL OR e.end_at IS NULL
		FROM trip_legs l JOIN gcal_events e ON e.id=l.gcal_event_id WHERE l.trip_id=ANY($1::uuid[]) ORDER BY l.trip_id,l.seq`, ids)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var id uuid.UUID
		var leg LegView
		var start, end *time.Time
		var startTZ, endTZ *string
		if err := rows.Scan(&id, &leg.EventID, &leg.Seq, &leg.Summary, &leg.FlightCode, &start, &end, &startTZ, &endTZ, &leg.Removed); err != nil {
			return err
		}
		dep, arr, basis := travel.LegZones(startTZ, endTZ, home)
		leg.TimezoneBasis, leg.DepartTZ, leg.ArriveTZ = basis, dep.String(), arr.String()
		leg.DepartAt, leg.ArriveAt = isoTime(start, time.UTC), isoTime(end, time.UTC)
		leg.DepartLocal, leg.ArriveLocal = isoTime(start, dep), isoTime(end, arr)
		t := owners[id]
		t.Legs = append(t.Legs, leg)
		if !leg.Removed {
			t.TravelDays = append(t.TravelDays, start.In(dep).Format(time.DateOnly), end.In(arr).Format(time.DateOnly))
		}
	}
	if err := rows.Err(); err != nil {
		return err
	}
	for i := range trips {
		slices.Sort(trips[i].TravelDays)
		trips[i].TravelDays = slices.Compact(trips[i].TravelDays)
	}
	return nil
}
