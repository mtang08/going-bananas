package travel

import (
	"context"
	"maps"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"
)

type priorEvent struct {
	ID      string
	Hash    string
	Removed bool
}

func upsertEvents(ctx context.Context, tx pgx.Tx, records map[string]*Record, home *time.Location, window Window, now time.Time) (EventCounts, error) {
	counts := EventCounts{Fetched: len(records)}
	ids := slices.AppendSeq([]string{}, maps.Keys(records))
	rows, err := tx.Query(ctx, `SELECT google_event_id,content_hash,removed_at IS NOT NULL
		FROM gcal_events WHERE google_event_id=ANY($1::text[])`, ids)
	if err != nil {
		return counts, err
	}
	prior, err := pgx.CollectRows(rows, pgx.RowToStructByPos[priorEvent])
	if err != nil {
		return counts, err
	}
	existing := make(map[string]priorEvent, len(prior))
	for _, e := range prior {
		existing[e.ID] = e
	}
	for _, r := range records {
		old, exists := existing[r.GoogleEventID]
		switch {
		case !exists:
			counts.Created++
		case old.Removed:
			counts.Restored++
		case old.Hash == r.ContentHash:
			counts.Unchanged++
			continue
		default:
			counts.Changed++
		}
		if exists && old.Hash == r.ContentHash {
			// A pure restoration preserves the original changed_at and provider metadata.
			_, err = tx.Exec(ctx, "UPDATE gcal_events SET removed_at=NULL, version=version+1 WHERE google_event_id=$1", r.GoogleEventID)
		} else {
			err = writeEvent(ctx, tx, r, DeriveEvent(*r, home), now)
		}
		if err != nil {
			return counts, err
		}
	}
	tag, err := tx.Exec(ctx, `UPDATE gcal_events SET removed_at=$1, version=version+1
		WHERE removed_at IS NULL AND NOT (google_event_id=ANY($2::text[])) AND (
			(all_day AND end_date>$3::text::date AND start_date<=$4::text::date) OR
			(NOT all_day AND end_at>$5 AND start_at<$6))`, now, ids, window.Start, window.End, window.From, window.Until)
	counts.Removed = int(tag.RowsAffected())
	return counts, err
}

func writeEvent(ctx context.Context, tx pgx.Tx, r *Record, d DerivedEvent, now time.Time) error {
	_, err := tx.Exec(ctx, `INSERT INTO gcal_events(id, google_event_id, event_type, google_status, summary,
		location_codes, all_day, start_at, end_at, start_date, end_date, start_tz, end_tz, transparency,
		response_status, busy, google_updated_at, flight_code, destination_label, auto_category, flight_confidence,
		category, category_source, first_seen_at, changed_at, content_hash)
		VALUES(gen_random_uuid(),@id,@kind,@status,@summary,@locations,@allDay,@start,@end,@startDate::text::date,
			@endDate::text::date,@startTZ,@endTZ,@transparency,@response,@busy,@updated,@flight,@destination,
			@category,@confidence,@category,'auto',@now,@now,@hash)
		ON CONFLICT(google_event_id) DO UPDATE SET
			(event_type, google_status, summary, location_codes, all_day, start_at, end_at, start_date, end_date,
			 start_tz, end_tz, transparency, response_status, busy, google_updated_at, flight_code, destination_label,
			 auto_category, flight_confidence, changed_at, content_hash) =
			(EXCLUDED.event_type, EXCLUDED.google_status, EXCLUDED.summary, EXCLUDED.location_codes, EXCLUDED.all_day,
			 EXCLUDED.start_at, EXCLUDED.end_at, EXCLUDED.start_date, EXCLUDED.end_date, EXCLUDED.start_tz, EXCLUDED.end_tz,
			 EXCLUDED.transparency, EXCLUDED.response_status, EXCLUDED.busy, EXCLUDED.google_updated_at, EXCLUDED.flight_code,
			 EXCLUDED.destination_label, EXCLUDED.auto_category, EXCLUDED.flight_confidence, EXCLUDED.changed_at, EXCLUDED.content_hash),
			category=CASE WHEN gcal_events.category_source='auto' THEN EXCLUDED.auto_category ELSE gcal_events.category END,
			removed_at=NULL, version=gcal_events.version+1`, pgx.NamedArgs{
		"id": r.GoogleEventID, "kind": r.EventType, "status": r.GoogleStatus, "summary": r.Summary, "locations": r.LocationCodes,
		"allDay": r.AllDay, "start": r.StartAt, "end": r.EndAt, "startDate": r.StartDate, "endDate": r.EndDate, "startTZ": r.StartTZ,
		"endTZ": r.EndTZ, "transparency": r.Transparency, "response": r.ResponseStatus, "busy": r.Busy, "updated": r.UpdatedAt,
		"flight": d.FlightCode, "destination": d.DestinationLabel, "category": d.AutoCategory, "confidence": d.FlightConfidence, "now": now, "hash": r.ContentHash,
	})
	return err
}
