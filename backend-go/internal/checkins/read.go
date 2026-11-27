package checkins

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

const viewSelect = `SELECT c.id,c.idempotency_key,c.version,c.kind,c.observed_at,c.recorded_at,c.fatigue,c.illness,c.gait_change,
	c.pain_reported,c.context_tags,c.activity_id,c.prompt_id,c.note,c.schema_version,
	coalesce((SELECT jsonb_agg(jsonb_build_object('id',s.id,'site',s.site,'side',s.side,'severity',s.severity,'timing',s.timing)
		ORDER BY s.id) FROM symptom_reports s WHERE s.checkin_id=c.id),'[]') FROM checkins_v2 c`

func scanView(row pgx.Row) (View, error) {
	var v View
	var observed, recorded time.Time
	err := row.Scan(&v.ID, &v.IdempotencyKey, &v.Version, &v.Kind, &observed, &recorded, &v.Fatigue, &v.Illness, &v.GaitChange, &v.PainReported,
		&v.ContextTags, &v.ActivityID, &v.PromptID, &v.Note, &v.SchemaVersion, &v.Symptoms)
	v.ObservedAt, v.RecordedAt = wireInstant(observed), wireInstant(recorded)
	return v, err
}

func get(ctx context.Context, tx pgx.Tx, id uuid.UUID) (View, error) {
	return scanView(tx.QueryRow(ctx, viewSelect+" WHERE c.id=$1", id))
}

func List(ctx context.Context, tx pgx.Tx, start, end *time.Time) ([]View, error) {
	zone, err := db.New(tx).CalendarTimezone(ctx)
	if err != nil {
		return nil, err
	}
	if zone == "" {
		zone = "America/New_York"
	}
	var lo, hi *string
	if start != nil {
		s := start.Format(time.DateOnly)
		lo = &s
	}
	if end != nil {
		s := end.Format(time.DateOnly)
		hi = &s
	}
	rows, err := tx.Query(ctx, viewSelect+` WHERE ($1::text IS NULL OR (c.observed_at AT TIME ZONE $3)::date >= $1::text::date)
		AND ($2::text IS NULL OR (c.observed_at AT TIME ZONE $3)::date <= $2::text::date) ORDER BY c.observed_at DESC,c.id DESC`, lo, hi, zone)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (View, error) { return scanView(row) })
}
