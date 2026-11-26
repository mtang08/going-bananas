package spacing

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
)

var qualityRecipes = []string{"REC003", "REC004", "REC005", "REC006", "REC008", "REC009"}

type inputs struct {
	zone    *time.Location
	head    int
	entries []exposure
	sources []object
	refs    object
}
type plan struct {
	uid     uuid.UUID
	day     string
	classes []string
	ref     object
	status  string
	assoc   metrics.CompletionAssociation
}

func newExposure(key, day, source string, classes []string, uid, activity *string, start, end *time.Time, zone *time.Location) (exposure, error) {
	first, err := time.ParseInLocation(time.DateOnly, day, zone)
	if err != nil {
		return exposure{}, err
	}
	last := first.AddDate(0, 0, 1)
	e := exposure{Key: key, Day: day, Classes: classes, Source: source, UID: uid, Activity: activity, StartLow: first, StartHigh: last, EndLow: first, EndHigh: last}
	if start != nil {
		e.StartLow = *start
		e.StartHigh = *start
		e.EndLow = *start
	}
	if end != nil {
		e.EndLow = *end
		e.EndHigh = *end
	}
	return e, nil
}

func readPlans(ctx context.Context, tx pgx.Tx, head int) ([]plan, error) {
	rows, err := tx.Query(ctx, `WITH latest AS (SELECT DISTINCT ON(session_uid) * FROM calendar_session_revisions
 WHERE calendar_version_number<=$1 ORDER BY session_uid,calendar_version_number DESC,revision DESC)
 SELECT p.session_uid,p.local_date::text,p.kind,coalesce(p.recipe_id,''),p.id,p.revision,p.calendar_version_number,p.structure,
 s.id,s.version,s.lower_body_cost,s.active,coalesce(c.status,''),coalesce(c.match_method,''),c.activity_id,c.strong_workout_id,c.manual_session_id,
 c.modification_reason,c.reason_note,coalesce(c.input_version,0),p.recipe_id
 FROM latest p LEFT JOIN strength_routine_slots s ON s.id=p.strength_slot_id LEFT JOIN session_completions c ON c.session_uid=p.session_uid
 WHERE NOT p.deleted AND p.kind IN ('run','strength')`, head)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (plan, error) {
		var p plan
		var kind, recipe string
		var id uuid.UUID
		var revision, version int
		var raw []byte
		var slot *uuid.UUID
		var slotVersion *int
		var cost, recipeRef *string
		var active *bool
		a := &p.assoc
		err := row.Scan(&p.uid, &p.day, &kind, &recipe, &id, &revision, &version, &raw, &slot, &slotVersion, &cost, &active, &p.status, &a.MatchMethod, &a.ActivityID, &a.StrongWorkoutID, &a.ManualSessionID, &a.ModificationReason, &a.ReasonNote, &a.InputVersion, &recipeRef)
		if err != nil {
			return p, err
		}
		a.SessionUID = p.uid
		val, err := metrics.JSONValue(raw)
		if err != nil {
			return p, err
		}
		structureHash, err := metrics.Digest(val)
		if err != nil {
			return p, err
		}
		p.ref = object{"plan_revision_id": id, "revision": revision, "calendar_version": version, "structure_hash": structureHash, "recipe_id": recipeRef, "session_uid": p.uid, "completion_association_hash": nil, "strength_slot": nil}
		if slot != nil {
			p.ref["strength_slot"] = object{"id": slot, "version": slotVersion, "lower_body_cost": cost, "active": active}
		}
		if p.status != "" {
			hash, err := a.Hash()
			if err != nil {
				return p, err
			}
			p.ref["completion_association_hash"] = hash
		}
		switch {
		case kind == "run" && slices.Contains(qualityRecipes, recipe):
			p.classes = []string{"quality"}
		case kind == "run" && recipe == "REC002":
			p.classes = []string{"long"}
		case kind == "strength" && cost != nil && (*cost == "moderate" || *cost == "high"):
			p.classes = []string{"lower_body_strength"}
		}
		return p, nil
	})
}

func (in *inputs) add(e exposure, ref object, err error) error {
	if err != nil {
		return err
	}
	in.entries = append(in.entries, e)
	in.sources = append(in.sources, ref)
	return nil
}

func (in *inputs) strength(ctx context.Context, tx pgx.Tx, p plan) error {
	var id uuid.UUID
	var clock *string
	var day, source string
	var duration *float64
	ref := object{"plan": p.ref}
	if p.assoc.StrongWorkoutID != nil {
		source = "strong"
		id = *p.assoc.StrongWorkoutID
		var payload string
		var record, raw uuid.UUID
		var sourceHash, parser, rawHash *string
		err := tx.QueryRow(ctx, `SELECT w.local_date::text,w.local_start,w.duration_s,w.payload_hash,w.source_record_id,w.raw_object_id,s.payload_hash,s.parser_version,r.sha256
 FROM strong_workouts w LEFT JOIN source_records s ON s.id=w.source_record_id LEFT JOIN raw_objects r ON r.id=w.raw_object_id WHERE w.id=$1 AND w.resolution_state='resolved'`, id).Scan(&day, &clock, &duration, &payload, &record, &raw, &sourceHash, &parser, &rawHash)
		if errors.Is(err, pgx.ErrNoRows) {
			return nil
		}
		if err != nil {
			return err
		}
		ref["strong_workout_id"] = id
		ref["payload_hash"] = payload
		ref["source_record_id"] = record
		ref["source_payload_hash"] = sourceHash
		ref["source_parser_version"] = parser
		ref["raw_object_id"] = raw
		ref["raw_sha256"] = rawHash
	} else {
		source = "manual"
		id = *p.assoc.ManualSessionID
		var version int
		err := tx.QueryRow(ctx, `SELECT date::text,date::text || 'T' || time::text,duration_s,version FROM manual_sessions WHERE id=$1 AND kind='strength'`, id).Scan(&day, &clock, &duration, &version)
		if errors.Is(err, pgx.ErrNoRows) {
			return nil
		}
		if err != nil {
			return err
		}
		ref["manual_session_id"] = id
		ref["version"] = version
		ref["duration_s"] = duration
	}
	var start, end *time.Time
	if clock != nil {
		for _, layout := range []string{"2006-01-02T15:04:05", "2006-01-02 15:04:05"} {
			t, err := time.ParseInLocation(layout, *clock, in.zone)
			if err == nil {
				start = &t
				break
			}
		}
	}
	if start != nil && duration != nil {
		t := start.Add(time.Duration(*duration*1e6) * time.Microsecond)
		end = &t
	}
	uid := p.uid.String()
	e, err := newExposure(source+":"+id.String(), day, source, p.classes, &uid, nil, start, end, in.zone)
	return in.add(e, ref, err)
}

func (in *inputs) runs(ctx context.Context, tx pgx.Tx, plans map[uuid.UUID]plan) error {
	rows, err := tx.Query(ctx, `SELECT a.id,c.session_uid,m.id,m.dependency_hash,m.value FROM activities a
 LEFT JOIN session_completions c ON c.activity_id=a.id AND c.status<>'skipped'
 LEFT JOIN metric_results m ON m.metric_id='long_run_exposure' AND m.method_version='v1' AND m.subject_key=a.id::text AND m.is_current
 WHERE a.resolution_state='resolved' AND a.sport IN ('running','trail_running','treadmill_running') ORDER BY a.start_at,a.id`)
	if err != nil {
		return err
	}
	type row struct {
		id          uuid.UUID
		uid, metric *uuid.UUID
		dep         *string
		value       []byte
	}
	records, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (row, error) {
		var v row
		err := r.Scan(&v.id, &v.uid, &v.metric, &v.dep, &v.value)
		return v, err
	})
	if err != nil {
		return err
	}
	for _, r := range records {
		run, err := metrics.LoadRun(ctx, tx, r.id, in.zone.String())
		if err != nil {
			return err
		}
		if run == nil || !run.Eligible {
			continue
		}
		var p plan
		var uid *string
		if r.uid != nil {
			p = plans[*r.uid]
			s := r.uid.String()
			uid = &s
		}
		classes := slices.Clone(p.classes)
		isLong := p.ref == nil && run.Label != nil && *run.Label == "long"
		val, err := metrics.JSONValue(r.value)
		if err != nil {
			return err
		}
		if obj, ok := val.(map[string]any); ok {
			isLong = obj["classification"] == "long"
		}
		if isLong && !slices.Contains(classes, "long") {
			classes = append(classes, "long")
		}
		if len(classes) == 0 {
			continue
		}
		id := r.id.String()
		e, err := newExposure(id, run.Day, "activity", classes, uid, &id, &run.Start, run.End, in.zone)
		ref := object{"activity_id": r.id, "source_revision": run.SourceRevision, "source_refs": run.Refs, "plan": p.ref, "long_metric_id": r.metric, "long_dependency_hash": r.dep}
		if err := in.add(e, ref, err); err != nil {
			return err
		}
	}
	return nil
}

func loadInputs(ctx context.Context, tx pgx.Tx, zone *time.Location, head int, plans []plan) (inputs, error) {
	in := inputs{zone: zone, head: head, sources: []object{}}
	byUID := map[uuid.UUID]plan{}
	for _, p := range plans {
		byUID[p.uid] = p
		if len(p.classes) == 0 || p.status == "skipped" {
			continue
		}
		a := p.assoc
		if a.StrongWorkoutID != nil || a.ManualSessionID != nil {
			if slices.Contains(p.classes, "lower_body_strength") {
				if err := in.strength(ctx, tx, p); err != nil {
					return in, err
				}
			}
			continue
		}
		if a.ActivityID != nil {
			continue
		}
		uid := p.uid.String()
		e, err := newExposure(uid, p.day, "plan", p.classes, &uid, nil, nil, nil, zone)
		ref := object{}
		for k, v := range p.ref {
			ref[k] = v
		}
		ref["classes"] = p.classes
		if err := in.add(e, ref, err); err != nil {
			return in, err
		}
	}
	if err := in.runs(ctx, tx, byUID); err != nil {
		return in, err
	}
	type keyed struct {
		key string
		ref object
	}
	ordered := make([]keyed, 0, len(in.sources))
	for _, ref := range in.sources {
		key, err := metrics.Digest(ref)
		if err != nil {
			return in, err
		}
		ordered = append(ordered, keyed{key, ref})
	}
	slices.SortFunc(ordered, func(a, b keyed) int {
		if a.key < b.key {
			return -1
		}
		if a.key > b.key {
			return 1
		}
		return 0
	})
	for i, r := range ordered {
		in.sources[i] = r.ref
	}
	in.refs = object{"sources": in.sources, "calendar_head": head}
	h, err := metrics.Digest(in.refs)
	if err != nil {
		return in, fmt.Errorf("hash spacing inputs: %w", err)
	}
	in.refs["input_hash"] = h
	return in, nil
}
