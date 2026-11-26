package calendar

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"maps"
	"reflect"
	"regexp"
	"slices"
	"strings"
	"time"
	"unicode/utf8"
)

type PlanEdit struct {
	ChangeID   string
	Op         string
	SessionUID *uuid.UUID
	Fields     json.RawMessage
}
type EditBatch struct {
	Head                       int
	Kind, Actor, Reason, Today string
	ProposalID, BlockVersionID *uuid.UUID
	Edits                      []PlanEdit
}
type AppliedEdits struct {
	Version  int
	Created  map[string]uuid.UUID
	PlanUIDs []uuid.UUID
	Dates    []string
	Stale    []uuid.UUID
}

// CheckPrescription validates exercise structure and athlete-specific limits on
// the resultant session inside the planning transaction.
type CheckPrescription func(before, after json.RawMessage, legacy bool) error

var optionalFields = map[string]any{"slot": float64(0), "recipe_id": nil, "custom": false, "placeholder": false, "planned_duration_s": nil, "planned_distance_m": nil, "structure": nil, "strength_slot_id": nil, "notes": nil, "brief": nil, "locked": false}
var recipePattern = regexp.MustCompile(`^REC(00[1-9]|010)$`)

type revisionRow struct {
	uid                uuid.UUID
	revision           int
	fields             map[string]any
	deleted, protected bool
}

func sessionFields(supplied, base map[string]any, legacy bool, actor string) (map[string]any, error) {
	fail := func(msg string) (map[string]any, error) { return nil, &Problem{"invalid_session_fields", msg} }
	fields := maps.Clone(optionalFields)
	maps.Copy(fields, base)
	for key, v := range supplied {
		_, ok := optionalFields[key]
		if !ok && key != "local_date" && key != "kind" && key != "intent" || key == "notes" && actor == "coach" || key == "brief" && actor != "coach" {
			return fail("Unexpected session field")
		}
		fields[key] = v
	}
	day, _ := fields["local_date"].(string)
	slot, ok := fields["slot"].(float64)
	if _, err := time.Parse(time.DateOnly, day); err != nil || !ok || slot < 0 || slot != float64(int(slot)) {
		return fail("Invalid date or slot")
	}
	kind, _ := fields["kind"].(string)
	if !slices.Contains([]string{"run", "strength", "cross", "rest", "mobility", "rehab"}, kind) {
		return fail("Invalid session kind")
	}
	intent, ok := fields["intent"].(string)
	if !ok || strings.TrimSpace(intent) == "" || utf8.RuneCountInString(intent) > 200 {
		return fail("Intent must be 1–200 characters")
	}
	for _, k := range []string{"locked", "custom", "placeholder"} {
		if _, ok := fields[k].(bool); !ok {
			return fail("Invalid session flag")
		}
	}
	for _, k := range []string{"planned_duration_s", "planned_distance_m"} {
		if v := fields[k]; v != nil {
			n, ok := v.(float64)
			if !ok || n <= 0 || n != float64(int(n)) {
				return fail("Duration and distance must be positive integers")
			}
		}
	}
	if kind == "rehab" && fields["planned_duration_s"] == nil {
		return fail("Rehab requires a planned duration")
	}
	if v := fields["recipe_id"]; v != nil {
		r, ok := v.(string)
		if !ok || !recipePattern.MatchString(r) {
			return fail("Unknown recipe ID")
		}
	}
	if v := fields["notes"]; v != nil {
		if _, ok := v.(string); !ok {
			return fail("Notes must be text")
		}
	}
	if v := fields["brief"]; v != nil {
		if _, ok := v.(map[string]any); !ok {
			return fail("Brief must be an object")
		}
	}
	if kind == "run" && fields["recipe_id"] == nil && fields["custom"] == false && fields["placeholder"] == false && !legacy {
		return fail("Run needs a recipe, custom flag, or placeholder")
	}
	if fields["placeholder"] == true && (fields["custom"] == true || fields["recipe_id"] != nil) {
		return fail("Placeholder cannot have a recipe or custom flag")
	}
	if v := fields["strength_slot_id"]; v != nil {
		val, _ := v.(string)
		id, err := uuid.Parse(val)
		if err != nil {
			return fail("Invalid strength slot ID")
		}
		fields["strength_slot_id"] = id.String()
	}
	if _, brief := supplied["brief"]; base != nil && (actor != "coach" || !brief) {
		for _, k := range []string{"kind", "recipe_id", "structure", "intent"} {
			if !reflect.DeepEqual(fields[k], base[k]) {
				fields["brief"] = nil
				break
			}
		}
	}
	return fields, nil
}

const editHeadRows = `WITH latest AS (SELECT DISTINCT ON(session_uid) * FROM calendar_session_revisions WHERE calendar_version_number <= $1 ORDER BY session_uid,calendar_version_number DESC,revision DESC)
 SELECT l.session_uid,l.revision,to_jsonb(l)-ARRAY['id','session_uid','revision','calendar_version_number','deleted','certainty'],l.deleted,
 l.locked OR l.local_date<$2::date OR EXISTS(SELECT 1 FROM session_completions c WHERE c.session_uid=l.session_uid AND (c.status IN ('skipped','completed_as_planned') OR c.activity_id IS NOT NULL OR c.strong_workout_id IS NOT NULL OR c.manual_session_id IS NOT NULL))
 FROM latest l`

func readEditHead(ctx context.Context, tx pgx.Tx, b EditBatch) (map[uuid.UUID]revisionRow, error) {
	rows, err := tx.Query(ctx, editHeadRows, b.Head, b.Today)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[uuid.UUID]revisionRow{}
	for rows.Next() {
		var r revisionRow
		if err := rows.Scan(&r.uid, &r.revision, &r.fields, &r.deleted, &r.protected); err != nil {
			return nil, err
		}
		out[r.uid] = r
	}
	return out, rows.Err()
}
func prepareEdit(b EditBatch, e PlanEdit, head map[uuid.UUID]revisionRow, check CheckPrescription) (revisionRow, error) {
	var row revisionRow
	problem := func(code, msg string) (revisionRow, error) { return row, &Problem{code, msg} }
	if e.Op == "add" {
		if e.SessionUID != nil {
			return problem("invalid_calendar_edit", "New session UID is server assigned")
		}
		row.uid = uuid.New()
	} else {
		if e.SessionUID == nil {
			return problem("invalid_calendar_edit", "Invalid session UID")
		}
		var ok bool
		row, ok = head[*e.SessionUID]
		if !ok || row.deleted {
			return problem("session_not_found", "Session not found")
		}
		if row.protected {
			return problem("protected_session", "Historical, locked, or completed session cannot change")
		}
	}
	row.revision++
	var supplied map[string]any
	if len(e.Fields) > 0 {
		if err := json.Unmarshal(e.Fields, &supplied); err != nil {
			return problem("invalid_calendar_edit", "Fields required")
		}
	}
	if e.Op == "delete" {
		if len(supplied) > 0 {
			return problem("invalid_calendar_edit", "Delete cannot contain fields")
		}
		row.deleted = true
		return row, nil
	}
	if !slices.Contains([]string{"add", "modify", "move"}, e.Op) {
		return problem("invalid_calendar_edit", "Unknown calendar edit")
	}
	if supplied == nil {
		return problem("invalid_calendar_edit", "Fields required")
	}
	if _, ok := supplied["local_date"]; e.Op == "move" && !ok {
		return problem("invalid_calendar_edit", "Move requires local date")
	}
	base := maps.Clone(row.fields)
	legacy, _ := base["legacy_unstructured"].(bool)
	legacyPayload := base["legacy_payload"]
	delete(base, "legacy_unstructured")
	delete(base, "legacy_payload")
	merged, err := sessionFields(supplied, base, legacy, b.Actor)
	if err != nil {
		return row, err
	}
	before, err := json.Marshal(base)
	if err != nil {
		return row, err
	}
	after, err := json.Marshal(merged)
	if err != nil {
		return row, err
	}
	if err := check(before, after, legacy); err != nil {
		return row, err
	}
	if base != nil && reflect.DeepEqual(merged, base) {
		return problem("edit_no_change", "Session is unchanged")
	}
	if merged["local_date"].(string) < b.Today {
		return problem("protected_session", "Historical session cannot change")
	}
	merged["legacy_unstructured"] = legacy
	merged["legacy_payload"] = legacyPayload
	row.fields = merged
	return row, nil
}

// ApplyEdits appends a version and revisions within the caller's transaction.
// The caller consumes affected days and UIDs for the same transaction's refresh.
func ApplyEdits(ctx context.Context, tx pgx.Tx, b EditBatch, check CheckPrescription) (AppliedEdits, error) {
	out := AppliedEdits{Created: map[string]uuid.UUID{}, Stale: []uuid.UUID{}}
	if check == nil {
		return out, errors.New("calendar prescription validator required")
	}
	if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
		return out, err
	}
	var head int
	if err := tx.QueryRow(ctx, "SELECT calendar_head_version FROM app_state WHERE id=1 FOR UPDATE").Scan(&head); err != nil {
		return out, err
	}
	if head != b.Head {
		return out, &Problem{"calendar_head_moved", "Calendar changed; reload before editing"}
	}
	if len(b.Edits) == 0 {
		return out, &Problem{"edit_no_change", "No calendar changes supplied"}
	}
	rows, err := readEditHead(ctx, tx, b)
	if err != nil {
		return out, err
	}
	prepared := make([]revisionRow, 0, len(b.Edits))
	seen := map[uuid.UUID]bool{}
	for _, e := range b.Edits {
		r, err := prepareEdit(b, e, rows, check)
		if err != nil {
			return out, err
		}
		if seen[r.uid] {
			return out, &Problem{"duplicate_session_edit", "Session edited more than once"}
		}
		seen[r.uid] = true
		prepared = append(prepared, r)
		if e.Op == "add" {
			out.Created[e.ChangeID] = r.uid
		}
	}
	for _, r := range prepared {
		rows[r.uid] = r
	}
	rehab := map[string]float64{}
	for _, r := range rows {
		if !r.deleted && r.fields["kind"] == "rehab" {
			day := r.fields["local_date"].(string)
			n, _ := r.fields["planned_duration_s"].(float64)
			rehab[day] += n
			if rehab[day] > 900 {
				return out, &Problem{"rehab_daily_limit", "Rehab sessions cannot exceed 15 minutes per day"}
			}
		}
	}
	out.Version = head + 1
	_, err = tx.Exec(ctx, `INSERT INTO calendar_versions(id,number,parent_number,kind,actor,reason,proposal_id,block_version_id) VALUES($1,$2,nullif($3,0),$4,$5,$6,$7,$8)`, uuid.New(), out.Version, head, b.Kind, b.Actor, b.Reason, b.ProposalID, b.BlockVersionID)
	if err != nil {
		return out, err
	}
	for _, r := range prepared {
		_, err = tx.Exec(ctx, `INSERT INTO calendar_session_revisions(id,session_uid,revision,calendar_version_number,deleted,local_date,slot,kind,recipe_id,custom,locked,legacy_unstructured,legacy_payload,placeholder,intent,certainty,planned_duration_s,planned_distance_m,structure,strength_slot_id,notes,brief)
   SELECT $1,$2,$3,$4,$5,f.local_date,f.slot,f.kind,f.recipe_id,f.custom,f.locked,f.legacy_unstructured,f.legacy_payload,f.placeholder,f.intent,
   CASE WHEN f.local_date<=$6::date+6 THEN 'committed' ELSE 'provisional' END,f.planned_duration_s,f.planned_distance_m,f.structure,f.strength_slot_id,f.notes,f.brief FROM jsonb_populate_record(NULL::calendar_session_revisions,$7::jsonb) f`, uuid.New(), r.uid, r.revision, out.Version, r.deleted, b.Today, r.fields)
		if err != nil {
			return out, err
		}
		out.PlanUIDs = append(out.PlanUIDs, r.uid)
		out.Dates = append(out.Dates, r.fields["local_date"].(string))
	}
	_, err = tx.Exec(ctx, "UPDATE app_state SET calendar_head_version=$1 WHERE id=1", out.Version)
	if err != nil {
		return out, err
	}
	pending, err := tx.Query(ctx, "UPDATE coach_proposals SET status='stale' WHERE status='pending' RETURNING id")
	if err != nil {
		return out, err
	}
	defer pending.Close()
	for pending.Next() {
		var id uuid.UUID
		if err := pending.Scan(&id); err != nil {
			return out, err
		}
		out.Stale = append(out.Stale, id)
	}
	return out, pending.Err()
}
