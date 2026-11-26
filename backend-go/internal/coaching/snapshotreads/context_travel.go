package snapshotreads

import (
	"context"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"
)

type TravelContext struct {
	Trips []map[string]any `json:"trips"`
	Meta  map[string]any   `json:"travel_meta"`
}

func LoadTravel(ctx context.Context, tx pgx.Tx, asOf string, home *time.Location) (TravelContext, error) {
	var result TravelContext
	trips, err := contextRows(ctx, tx, `SELECT id::text AS trip_id,status,(status='confirmed') AS confirmed,
		start_date::text,end_date::text,destination_label AS destination,destination_tz AS destination_timezone,
		source,confidence,running_access,gym_access,day_availability AS days FROM trips
		WHERE status <> 'dismissed' AND start_date <= $1::date + 120
		AND (end_date >= $1::date - 7 OR (end_date IS NULL AND start_date >= $1::date - 37))
		ORDER BY start_date,id`, asOf)
	if err != nil {
		return result, err
	}
	byID := map[string]map[string]any{}
	days := map[string][]string{}
	ids := make([]string, 0, len(trips))
	for _, trip := range trips {
		id := trip["trip_id"].(string)
		ids = append(ids, id)
		byID[id] = trip
		trip["legs"] = []map[string]any{}
		days[id] = []string{}
	}
	rows, err := tx.Query(ctx, `SELECT l.trip_id::text,e.start_at,e.end_at,coalesce(e.start_tz,''),coalesce(e.end_tz,'')
		FROM trip_legs l JOIN gcal_events e ON e.id=l.gcal_event_id WHERE l.trip_id=ANY($1::uuid[])
		AND e.removed_at IS NULL AND e.category='flight' AND e.response_status IS DISTINCT FROM 'declined'
		AND e.start_at IS NOT NULL AND e.end_at IS NOT NULL ORDER BY l.trip_id,l.seq`, ids)
	if err != nil {
		return result, err
	}
	var id, from, to string
	var departure, arrival time.Time
	_, err = pgx.ForEachRow(rows, []any{&id, &departure, &arrival, &from, &to}, func() error {
		depZone, arrZone, basis := travelZones(from, to, home)
		depart, arrive := departure.In(depZone), arrival.In(arrZone)
		trip := byID[id]
		trip["legs"] = append(trip["legs"].([]map[string]any), map[string]any{
			"depart_local": travelInstant(depart), "arrive_local": travelInstant(arrive),
			"depart_timezone": depZone.String(), "arrive_timezone": arrZone.String(), "timezone_basis": basis,
		})
		days[id] = append(days[id], depart.Format(time.DateOnly), arrive.Format(time.DateOnly))
		return nil
	})
	if err != nil {
		return result, err
	}
	for id, dates := range days {
		slices.Sort(dates)
		byID[id]["travel_days"] = slices.Compact(dates)
	}
	result.Trips = trips
	meta, err := contextRows(ctx, tx, `SELECT max(finished_at) AS calendar_synced_at FROM import_batches
		WHERE source_kind='google_calendar' AND status='complete'`)
	if err != nil {
		return result, err
	}
	result.Meta = meta[0]
	result.Meta["home_timezone"] = home.String()
	return result, nil
}

func travelZones(from, to string, home *time.Location) (*time.Location, *time.Location, string) {
	zone := func(name string) *time.Location {
		if name == "" || name == "Local" {
			return nil
		}
		loc, err := time.LoadLocation(name)
		if err != nil {
			return nil
		}
		return loc
	}
	dep, arr := zone(from), zone(to)
	if dep == nil && arr == nil {
		return home, home, "fallback"
	}
	if dep == nil {
		return arr, arr, "fallback"
	}
	if arr == nil {
		return dep, dep, "fallback"
	}
	if from == to {
		return dep, arr, "calendar_display"
	}
	return dep, arr, "calendar_endpoints"
}

func travelInstant(t time.Time) string {
	layout := "2006-01-02T15:04:05"
	if t.Nanosecond() != 0 {
		layout += ".000000"
	}
	return t.Format(layout + "-07:00")
}
