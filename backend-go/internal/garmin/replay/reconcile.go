package replay

import (
	"context"
	"errors"
	"maps"
	"slices"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

func sortedIDs[V any](values map[string]V) []string { return slices.Sorted(maps.Keys(values)) }

var canonicalFields = []string{"start_at", "original_start", "source_timezone", "local_date", "sport", "subtype", "distance_m", "elapsed_s", "moving_s", "avg_hr_bpm", "cadence_spm", "source_workout_label", "timer_s"}

type source struct {
	ID     uuid.UUID
	Kind   string
	Fields map[string]any
}
type provenance struct {
	ID    uuid.UUID `json:"source_record_id"`
	Kind  string    `json:"source_kind"`
	Field any       `json:"source_field"`
}

func reconcile(ctx context.Context, tx pgx.Tx, owner uuid.UUID, identity, remoteID string, effects *Result) (uuid.UUID, string, bool, error) {
	rows, err := tx.Query(ctx, `SELECT id,source_kind,fields FROM source_records
		WHERE source_account_id=$1 AND source_identity=$2 AND rejected_reason IS NULL
		ORDER BY source_modified_at DESC NULLS LAST,(source_kind='garmin_api') DESC,
		CASE WHEN source_kind='garmin_api' THEN fetched_at END DESC NULLS LAST,payload_hash DESC`, owner, identity)
	if err != nil {
		return uuid.Nil, "", false, err
	}
	sources, err := pgx.CollectRows(rows, pgx.RowToStructByPos[source])
	if err != nil {
		return uuid.Nil, "", false, err
	}
	fields := map[string]any{}
	lineage := map[string]provenance{}
	chosen := map[uuid.UUID][]string{}
	for _, key := range canonicalFields {
		for _, s := range sources {
			if value := s.Fields[key]; value != nil {
				fields[key] = value
				paths, _ := s.Fields["field_paths"].(map[string]any)
				lineage[key] = provenance{s.ID, s.Kind, paths[key]}
				chosen[s.ID] = append(chosen[s.ID], key)
				break
			}
		}
	}
	fields["field_provenance"] = lineage
	var id uuid.UUID
	var day string
	err = tx.QueryRow(ctx, upsertActivity, owner, identity, remoteID, fields).Scan(&id, &day)
	changed := err == nil
	if errors.Is(err, pgx.ErrNoRows) {
		err = tx.QueryRow(ctx, `SELECT id,local_date::text FROM activities WHERE source_account_id=$1 AND source_identity=$2`, owner, identity).Scan(&id, &day)
	}
	if err != nil {
		return id, day, false, err
	}
	for _, s := range sources {
		keys := chosen[s.ID]
		if keys == nil {
			keys = []string{}
		}
		_, err = tx.Exec(ctx, `INSERT INTO activity_sources(id,activity_id,source_record_id,selected_fields)
			VALUES(gen_random_uuid(),$1,$2,$3) ON CONFLICT(activity_id,source_record_id)
			DO UPDATE SET selected_fields=EXCLUDED.selected_fields
			WHERE activity_sources.selected_fields IS DISTINCT FROM EXCLUDED.selected_fields`, id, s.ID, keys)
		if err != nil {
			return id, day, false, err
		}
	}
	if changed {
		err = detectConflicts(ctx, tx, id, effects)
	}
	return id, day, changed, err
}

const upsertActivity = `
WITH fields AS (SELECT * FROM jsonb_populate_record(NULL::activities,$4::jsonb)),
fit_provenance AS (
	SELECT coalesce(jsonb_object_agg(p.key,p.value),'{}') AS retained
	FROM activities a CROSS JOIN LATERAL jsonb_each(a.field_provenance) p
	WHERE a.source_account_id=$1 AND a.source_identity=$2 AND a.fit_status='decoded' AND p.value->>'source_kind'='garmin_fit'
)
INSERT INTO activities(id,source_account_id,source_identity,garmin_id,canonical_revision,resolution_state,
	start_at,original_start,source_timezone,local_date,sport,subtype,distance_m,elapsed_s,moving_s,avg_hr_bpm,cadence_spm,source_workout_label,field_provenance)
SELECT gen_random_uuid(),$1,$2,nullif($3,''),1,'resolved',start_at,original_start,source_timezone,local_date,sport,subtype,
	distance_m,elapsed_s,moving_s,avg_hr_bpm,cadence_spm,source_workout_label,field_provenance || retained FROM fields,fit_provenance
ON CONFLICT(source_account_id,source_identity) DO UPDATE SET
	canonical_revision=activities.canonical_revision+1,
	start_at=EXCLUDED.start_at,original_start=EXCLUDED.original_start,source_timezone=EXCLUDED.source_timezone,
	local_date=EXCLUDED.local_date,sport=EXCLUDED.sport,subtype=EXCLUDED.subtype,distance_m=EXCLUDED.distance_m,
	elapsed_s=EXCLUDED.elapsed_s,moving_s=EXCLUDED.moving_s,avg_hr_bpm=EXCLUDED.avg_hr_bpm,cadence_spm=EXCLUDED.cadence_spm,
	source_workout_label=EXCLUDED.source_workout_label,field_provenance=EXCLUDED.field_provenance
WHERE (activities.start_at,activities.original_start,activities.source_timezone,activities.local_date,
	activities.sport,activities.subtype,activities.distance_m,activities.elapsed_s,activities.moving_s,
	activities.avg_hr_bpm,activities.cadence_spm,activities.source_workout_label,activities.field_provenance)
IS DISTINCT FROM (EXCLUDED.start_at,EXCLUDED.original_start,EXCLUDED.source_timezone,EXCLUDED.local_date,
	EXCLUDED.sport,EXCLUDED.subtype,EXCLUDED.distance_m,EXCLUDED.elapsed_s,EXCLUDED.moving_s,
	EXCLUDED.avg_hr_bpm,EXCLUDED.cadence_spm,EXCLUDED.source_workout_label,EXCLUDED.field_provenance)
RETURNING id,local_date::text`

func detectConflicts(ctx context.Context, tx pgx.Tx, id uuid.UUID, effects *Result) error {
	_, err := tx.Exec(ctx, `WITH neighbors AS (
		SELECT a.id, jsonb_build_array(least(a.id,b.id)::text,greatest(a.id,b.id)::text) ids
		FROM activities a JOIN activities b ON a.id<>b.id AND a.local_date=b.local_date AND a.sport=b.sport
		WHERE a.id=$1 AND a.garmin_id IS NULL AND b.resolution_state NOT IN ('merged','excluded')
		AND abs(extract(epoch from (a.start_at-b.start_at)))<=300
		AND (a.distance_m IS NULL OR b.distance_m IS NULL OR abs(a.distance_m-b.distance_m)<=greatest(50,b.distance_m*.02))
	), added AS (
		INSERT INTO conflicts(id,kind,status,activity_ids,details)
		SELECT gen_random_uuid(),'activity_overlap','open',ids,'{"reason":"close_time_and_distance","withheld_count":1}'
		FROM neighbors n WHERE NOT EXISTS(SELECT 1 FROM conflicts c WHERE c.kind='activity_overlap' AND c.activity_ids @> n.ids)
		RETURNING id
	) UPDATE activities SET resolution_state='pending' WHERE id=$1 AND EXISTS(SELECT FROM added)`, id)
	if err != nil {
		return err
	}
	rows, err := tx.Query(ctx, `WITH added AS (
		INSERT INTO conflicts(id,kind,status,activity_ids,manual_session_id,details)
		SELECT gen_random_uuid(),'manual_import_overlap','open',jsonb_build_array(a.id::text),m.id,'{"reason":"same_date_strength"}'
		FROM activities edited JOIN manual_sessions m ON m.date=edited.local_date AND m.kind='strength' AND m.linked_activity_id IS NULL
		JOIN activities a ON a.local_date=m.date AND a.sport='strength' AND a.resolution_state NOT IN ('merged','excluded')
		WHERE edited.id=$1 AND edited.sport='strength' AND NOT EXISTS(SELECT FROM conflicts c WHERE c.manual_session_id=m.id AND
			c.kind='manual_import_overlap' AND c.activity_ids ? a.id::text)
		RETURNING activity_ids
	) UPDATE activities SET resolution_state='pending' WHERE id IN(SELECT (activity_ids->>0)::uuid FROM added)
    AND resolution_state <> 'pending' RETURNING id,local_date::text`, id)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var held uuid.UUID
		var day string
		if err := rows.Scan(&held, &day); err != nil {
			return err
		}
		effects.Activities[held] = day
		effects.AffectedDates = append(effects.AffectedDates, day)
	}
	return rows.Err()
}
