package travel

import (
	"cmp"
	"context"
	"errors"
	"slices"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

var (
	ErrTripNotFound  = errors.New("trip_not_found")
	ErrEventNotFound = errors.New("event_not_found")
	ErrTripConflict  = errors.New("trip_version_conflict")
	ErrEventConflict = errors.New("event_version_conflict")
	ErrInvalidTrip   = errors.New("invalid_trip")
)

// Optional distinguishes JSON null from an omitted edit.
type Optional[T any] struct {
	Set   bool
	Value *T
}
type Availability struct {
	Date         string `json:"date"`
	Availability string `json:"availability"`
}
type TripEdit struct {
	ExpectedVersion                               int
	AcceptDetected                                bool
	Status, Start, End, Label, Zone, Running, Gym Optional[string]
	Days                                          Optional[[]Availability]
}

func applyOptional[T any](field Optional[T], value *T) *T {
	if field.Set {
		return field.Value
	}
	return value
}

func availability(days []Availability, start string, end *string) ([]Availability, error) {
	last := ""
	if end != nil {
		last = *end
	} else {
		d, err := time.Parse(time.DateOnly, start)
		if err != nil {
			return nil, ErrInvalidTrip
		}
		last = d.AddDate(0, 0, 30).Format(time.DateOnly)
	}
	if last < start {
		return nil, ErrInvalidTrip
	}
	kept := make([]Availability, 0, len(days))
	seen := make(map[string]bool)
	for _, day := range days {
		if day.Date < start || day.Date > last {
			continue
		}
		if seen[day.Date] || len(kept) >= 60 {
			return nil, ErrInvalidTrip
		}
		seen[day.Date] = true
		kept = append(kept, day)
	}
	slices.SortFunc(kept, func(a, b Availability) int { return cmp.Compare(a.Date, b.Date) })
	return kept, nil
}

// CreateManualTrip inserts a confirmed itinerary without source legs.
func CreateManualTrip(ctx context.Context, tx pgx.Tx, e TripEdit, now time.Time) (uuid.UUID, error) {
	if e.Start.Value == nil || e.End.Value == nil || e.Zone.Value == nil {
		return uuid.Nil, ErrInvalidTrip
	}
	var days []Availability
	if e.Days.Value != nil {
		days = *e.Days.Value
	}
	kept, err := availability(days, *e.Start.Value, e.End.Value)
	if err != nil || len(kept) != len(days) {
		return uuid.Nil, ErrInvalidTrip
	}
	id := uuid.New()
	_, err = tx.Exec(ctx, `INSERT INTO trips(id,status,start_date,end_date,destination_label,destination_tz,source,edited,detected,
		running_access,gym_access,day_availability,created_at,updated_at) VALUES ($1,'confirmed',$2::text::date,$3::text::date,
		$4,$5,'manual',true,'{}',$6,$7,$8::jsonb,$9,$9)`, id, e.Start.Value, e.End.Value, e.Label.Value, e.Zone.Value, e.Running.Value, e.Gym.Value, kept, now)
	return id, err
}

func PatchTrip(ctx context.Context, tx pgx.Tx, id uuid.UUID, e TripEdit, now time.Time) error {
	var version int
	var source, status, start, zone string
	var end, label, running, gym, confidence, reason *string
	var days []Availability
	var detected detectedTrip
	var edited bool
	err := tx.QueryRow(ctx, `SELECT version,source,status,to_char(start_date,'YYYY-MM-DD'),to_char(end_date,'YYYY-MM-DD'),
		destination_label,destination_tz,running_access,gym_access,day_availability,detected,confidence,review_reason,edited
		FROM trips WHERE id=$1 FOR UPDATE`, id).Scan(&version, &source, &status, &start, &end, &label, &zone, &running, &gym, &days, &detected, &confidence, &reason, &edited)
	if errors.Is(err, pgx.ErrNoRows) {
		return ErrTripNotFound
	}
	if err != nil {
		return err
	}
	if version != e.ExpectedVersion {
		return ErrTripConflict
	}
	if source == "manual" && (e.AcceptDetected || e.Status.Value != nil && *e.Status.Value == "pending" || e.End.Set && e.End.Value == nil) {
		return ErrInvalidTrip
	}
	if e.Start.Set && e.Start.Value == nil || e.Zone.Set && e.Zone.Value == nil || e.Status.Set && e.Status.Value == nil || e.Days.Set && e.Days.Value == nil {
		return ErrInvalidTrip
	}
	if e.AcceptDetected {
		if detected.Start == "" {
			return ErrInvalidTrip
		}
		start, end, label, zone, confidence = detected.Start, detected.End, detected.Label, detected.Zone, &detected.Confidence
	}
	start, zone = *applyOptional(e.Start, &start), *applyOptional(e.Zone, &zone)
	end, label, running, gym = applyOptional(e.End, end), applyOptional(e.Label, label), applyOptional(e.Running, running), applyOptional(e.Gym, gym)
	days, err = availability(*applyOptional(e.Days, &days), start, end)
	if err != nil {
		return err
	}
	if e.Status.Set {
		status = *e.Status.Value
		reason = nil
	}
	edited = edited || e.Start.Set || e.End.Set || e.Label.Set || e.Zone.Set || e.Running.Set || e.Gym.Set || e.Days.Set
	_, err = tx.Exec(ctx, `UPDATE trips SET start_date=$2::text::date,end_date=$3::text::date,destination_label=$4,destination_tz=$5,
		running_access=$6,gym_access=$7,day_availability=$8::jsonb,status=$9,review_reason=$10,edited=$11,confidence=$12,
		updated_at=$13,version=version+1 WHERE id=$1`, id, start, end, label, zone, running, gym, days, status, reason, edited, confidence, now)
	return err
}

func PatchEventCategory(ctx context.Context, tx pgx.Tx, id uuid.UUID, version int, category *string, home *time.Location) (TripCounts, error) {
	var current int
	err := tx.QueryRow(ctx, `SELECT version FROM gcal_events WHERE id=$1 FOR UPDATE`, id).Scan(&current)
	if errors.Is(err, pgx.ErrNoRows) {
		return TripCounts{}, ErrEventNotFound
	}
	if err != nil {
		return TripCounts{}, err
	}
	if version != current {
		return TripCounts{}, ErrEventConflict
	}
	_, err = tx.Exec(ctx, `UPDATE gcal_events SET category=coalesce($2::text,auto_category),category_source=CASE WHEN $2::text IS NULL THEN 'auto' ELSE 'athlete' END,version=version+1 WHERE id=$1`, id, category)
	if err != nil {
		return TripCounts{}, err
	}
	return reconcileTrips(ctx, tx, home)
}
