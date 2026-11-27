package demoseed

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/travel"
)

func supplied[T any](v T) travel.Optional[T] {
	return travel.Optional[T]{Set: true, Value: &v}
}

func seedTravel(ctx context.Context, tx pgx.Tx, today, now time.Time) error {
	home := today.Location()
	chicago, err := time.LoadLocation("America/Chicago")
	if err != nil {
		return err
	}
	la, err := time.LoadLocation("America/Los_Angeles")
	if err != nil {
		return err
	}
	date := func(offset int) string { return today.AddDate(0, 0, offset).Format(time.DateOnly) }
	at := func(offset, hour, minute int, zone *time.Location) map[string]any {
		y, m, d := today.AddDate(0, 0, offset).Date()
		return map[string]any{"dateTime": time.Date(y, m, d, hour, minute, 0, 0, zone).Format(time.RFC3339), "timeZone": zone.String()}
	}
	items := []struct {
		id, summary, kind, transparency string
		start, end                      map[string]any
		location                        string
		declined                        bool
	}{
		{"demo-flight-past-out", "Flight to Chicago (ZZ 201)", "fromGmail", "opaque", at(-20, 7, 0, home), at(-20, 8, 45, chicago), "JFK", false},
		{"demo-flight-past-back", "Flight to New York (ZZ 202)", "fromGmail", "opaque", at(-17, 17, 0, chicago), at(-17, 20, 5, home), "ORD", false},
		{"demo-flight-out", "Flight to Los Angeles (ZZ 101)", "fromGmail", "opaque", at(10, 8, 5, home), at(10, 11, 30, la), "JFK", false},
		{"demo-flight-back", "Flight to New York (ZZ 102)", "fromGmail", "opaque", at(14, 13, 0, la), at(14, 21, 25, home), "LAX", false},
		{"demo-hotel", "Stay at Synthetic Hotel", "fromGmail", "transparent", map[string]any{"date": date(10)}, map[string]any{"date": date(14)}, "", false},
		{"demo-meeting", "Team sync", "default", "opaque", at(2, 10, 0, home), at(2, 11, 0, home), "", true},
		{"demo-focus", "Focus time", "focusTime", "transparent", at(3, 14, 0, home), at(3, 16, 0, home), "", false},
	}
	records := make(map[string]*travel.Record, len(items))
	for _, item := range items {
		raw := map[string]any{"id": item.id, "summary": item.summary, "eventType": item.kind, "transparency": item.transparency, "status": "confirmed", "updated": "2026-01-01T00:00:00Z", "start": item.start, "end": item.end}
		if item.location != "" {
			raw["location"] = item.location
		}
		if item.declined {
			raw["attendees"] = []any{map[string]any{"self": true, "responseStatus": "declined"}}
		}
		r, err := travel.NormalizeEvent(raw)
		if err != nil {
			return err
		}
		if r != nil {
			records[r.GoogleEventID] = r
		}
	}
	if _, _, err := travel.ReconcileWindow(ctx, tx, records, home, travel.SyncWindow(today, home), now); err != nil {
		return err
	}
	res, err := tx.Exec(ctx, "UPDATE trips SET status='confirmed' WHERE start_date=$1::text::date", date(-20))
	if err != nil {
		return err
	}
	if res.RowsAffected() != 1 {
		return fmt.Errorf("expected one past demo trip, found %d", res.RowsAffected())
	}
	_, err = travel.CreateManualTrip(ctx, tx, travel.TripEdit{Start: supplied(date(30)), End: supplied(date(33)), Zone: supplied(home.String()), Label: supplied("Family visit"), Gym: supplied("none"), Days: supplied([]travel.Availability{{Date: date(31), Availability: "unavailable"}})}, now)
	return err
}
