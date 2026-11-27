package intervals

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/calendarstructure"
	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/recording"
	"os"
	"slices"
	"strconv"
	"time"
)

const ID = "work_interval_execution"
const Version = "v2"

//go:embed config.json
var rawConfig []byte
var Config = func() obj {
	v, err := metrics.JSONValue(rawConfig)
	if err != nil {
		panic(err)
	}
	return v.(obj)
}()

func stamp(t *time.Time) string {
	if t == nil {
		return ""
	}
	layout := "2006-01-02T15:04:05-07:00"
	if t.Nanosecond() != 0 {
		layout = "2006-01-02T15:04:05.000000-07:00"
	}
	return t.UTC().Format(layout)
}
func pyFloat(v *float64) string {
	if v == nil {
		return "None"
	}
	b, _ := canonicaljson.Metric(*v)
	return string(b)
}

// LapIdentity survives FIT replay, which recreates the database lap rows.
func LapIdentity(start time.Time, end *time.Time, elapsed, timer *float64, step *int) string {
	ref := "None"
	if step != nil {
		ref = strconv.Itoa(*step)
	}
	return fmt.Sprintf("%s|%s|%s|%s|%s", stamp(&start), stamp(end), pyFloat(elapsed), pyFloat(timer), ref)
}
func loadLaps(ctx context.Context, tx pgx.Tx, r *metrics.Run) ([]lap, map[string]any, error) {
	var saved map[string]struct {
		Identity string      `json:"lap_identity"`
		Pace     json.Number `json:"pace_s_per_mile"`
	}
	if r.Sport == "treadmill_running" {
		if err := tx.QueryRow(ctx, "SELECT treadmill_interval_paces FROM activities WHERE id=$1", r.ID).Scan(&saved); err != nil {
			return nil, nil, err
		}
	}
	rows, err := tx.Query(ctx, `SELECT lap_index,start_at,end_at,elapsed_s,timer_s,distance_m,wkt_step_index,intensity,avg_speed_mps FROM activity_laps WHERE activity_id=$1 ORDER BY lap_index`, r.ID)
	if err != nil {
		return nil, nil, err
	}
	paces := map[string]any{}
	laps, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (lap, error) {
		var l lap
		var start time.Time
		var end *time.Time
		if err := row.Scan(&l.index, &start, &end, &l.elapsed, &l.timer, &l.distance, &l.ref, &l.intensity, &l.speed); err != nil {
			return l, err
		}
		l.start = start.Sub(r.Start).Seconds()
		if end != nil {
			l.end = ptr(end.Sub(r.Start).Seconds())
		}
		key := strconv.Itoa(l.index)
		if p, ok := saved[key]; ok {
			if p.Identity == LapIdentity(start, end, l.elapsed, l.timer, l.ref) {
				v, err := p.Pace.Float64()
				if err != nil {
					return l, err
				}
				l.pace = &v
				paces[key] = p.Pace
			}
		}
		return l, nil
	})
	return laps, paces, err
}
func calculate(ctx context.Context, tx pgx.Tx, r *metrics.Run, plan *recording.Plan, refs obj) (outcome, error) {
	if !r.Eligible {
		return early("not_applicable", "ACTIVITY_EXCLUDED"), nil
	}
	if plan == nil || plan.Kind != "run" {
		return early("not_applicable", "NO_PLAN_LINK"), nil
	}
	if len(plan.Structure) == 0 || string(plan.Structure) == "null" {
		return early("not_applicable", "NO_STRUCTURED_PLAN"), nil
	}
	steps, ok := calendarstructure.Expand(plan.Structure)
	if !ok {
		return outcome{}, errors.New("invalid_structure")
	}
	if !slices.ContainsFunc(steps, func(s calendarstructure.Step) bool { return s.Type == "work" }) {
		return early("not_applicable", "NO_WORK_STEPS"), nil
	}
	fit, err := recording.Steps(ctx, tx, r.ID)
	if err != nil {
		return outcome{}, err
	}
	if len(fit) == 0 {
		return early("not_assessable", "NO_WATCH_WORKOUT"), nil
	}
	laps, paces, err := loadLaps(ctx, tx, r)
	if err != nil {
		return outcome{}, err
	}
	if len(paces) > 0 {
		refs["treadmill_interval_paces"] = paces
	}
	stream, err := recording.LoadStream(ctx, tx, r.ID)
	if err != nil {
		return outcome{}, err
	}
	out, err := execute(steps, fit, laps, stream, r.Sport == "treadmill_running")
	if err != nil || out.value == nil {
		return out, err
	}
	out.value["calendar_version"] = plan.Head
	out.value["session_uid"] = plan.UID.String()
	if r.Refs["fit_status"] == "decoded" && (r.FIT["raw_object_id"] == nil || r.FIT["zip_sha256"] == nil || r.FIT["fit_sha256"] == nil) {
		synthetic := false
		if mode := os.Getenv("APP_MODE"); mode == "test" || mode == "demo" {
			err := tx.QueryRow(ctx, `SELECT coalesce(bool_and(coalesce(s.source_kind='demo_fixture' AND s.payload_hash ~ '^[0-9a-f]{64}$' AND s.payload_hash=o.sha256 AND o.media_type='application/json',false)),false)
   FROM activity_sources l JOIN source_records s ON s.id=l.source_record_id LEFT JOIN raw_objects o ON o.id=s.raw_object_id WHERE l.activity_id=$1`, r.ID).Scan(&synthetic)
			if err != nil {
				return outcome{}, err
			}
		}
		if !synthetic {
			return early("invalid", "INPUT_PROVENANCE_MISSING"), nil
		}
		out.flags = set(append(out.flags, "SYNTHETIC_PROVENANCE"))
	}
	return out, nil
}
func Calculate(ctx context.Context, tx pgx.Tx, id uuid.UUID) (*metrics.Result, error) {
	z, err := db.New(tx).CalendarTimezone(ctx)
	if err != nil {
		return nil, err
	}
	r, err := metrics.LoadRun(ctx, tx, id, z)
	if err != nil || r == nil {
		return nil, err
	}
	if !slices.Contains([]string{"running", "trail_running", "treadmill_running"}, r.Sport) {
		return nil, nil
	}
	refs, p, err := recording.Sources(ctx, tx, r)
	if err != nil {
		return nil, err
	}
	o, err := calculate(ctx, tx, r, p, refs)
	if err != nil {
		return nil, err
	}
	return &metrics.Result{MetricID: ID, MethodVersion: Version, SubjectType: "activity", SubjectKey: id.String(), Status: o.status, QualityStatus: o.quality, Value: o.value, ReasonCodes: o.reasons, QualityFlags: o.flags, Timezone: z, Config: Config, SourceRefs: refs}, nil
}

func Refresh(ctx context.Context, tx pgx.Tx, id uuid.UUID, now time.Time) (uuid.UUID, error) {
	r, err := Calculate(ctx, tx, id)
	if err != nil || r == nil {
		return uuid.Nil, err
	}
	return metrics.StoreResult(ctx, tx, *r, now)
}
