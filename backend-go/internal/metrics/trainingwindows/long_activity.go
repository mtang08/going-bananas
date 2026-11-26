package trainingwindows

import (
	"context"
	"errors"
	"slices"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
)

func planLink(ctx context.Context, tx pgx.Tx, r *metrics.Run, refs object) (*uuid.UUID, bool, *string, error) {
	var a metrics.CompletionAssociation
	var head int
	var pid *uuid.UUID
	var deleted *bool
	var kind, recipe *string
	var raw []byte
	err := tx.QueryRow(ctx, `SELECT c.session_uid,c.activity_id,c.strong_workout_id,c.manual_session_id,c.match_method,c.modification_reason,c.reason_note,c.input_version,s.calendar_head_version,p.id,p.kind,p.recipe_id,p.deleted,p.structure
 FROM session_completions c JOIN app_state s ON s.id=1 LEFT JOIN LATERAL(SELECT * FROM calendar_session_revisions WHERE session_uid=c.session_uid AND calendar_version_number<=s.calendar_head_version ORDER BY calendar_version_number DESC,revision DESC LIMIT 1)p ON true WHERE c.activity_id=$1`, r.ID).Scan(&a.SessionUID, &a.ActivityID, &a.StrongWorkoutID, &a.ManualSessionID, &a.MatchMethod, &a.ModificationReason, &a.ReasonNote, &a.InputVersion, &head, &pid, &kind, &recipe, &deleted, &raw)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, false, nil, nil
	}
	if err != nil {
		return nil, false, nil, err
	}
	assoc, err := a.Hash()
	if err != nil {
		return nil, false, nil, err
	}
	refs["completion_association_hash"] = assoc
	if pid == nil || *deleted {
		return &a.SessionUID, false, nil, nil
	}
	v, err := metrics.JSONValue(raw)
	if err != nil {
		return nil, false, nil, err
	}
	hash, err := metrics.Digest(v)
	if err != nil {
		return nil, false, nil, err
	}
	refs["plan"] = object{"session_uid": a.SessionUID, "revision_id": pid, "calendar_version": head, "structure_hash": hash}
	if *kind != "run" {
		return &a.SessionUID, false, nil, nil
	}
	return &a.SessionUID, true, recipe, nil
}

func usable(v *float64) *float64 {
	if finite(v) && *v >= 0 {
		return v
	}
	return nil
}
func proportion(n, d *float64) *float64 {
	if n == nil || d == nil || *d <= 0 {
		return nil
	}
	v := round(*n / *d, 3)
	return &v
}
func roundedValue(n *float64) any {
	if n == nil {
		return nil
	}
	return round(*n, 1)
}

type comparisonMeasure struct {
	max, sum *float64
	maxSport string
}

func (m *comparisonMeasure) prior(value *float64, sport string) {
	if v := usable(value); v != nil && (m.max == nil || *v > *m.max) {
		m.max = v
		m.maxSport = sport
	}
}
func (m *comparisonMeasure) week(value *float64) {
	if v := usable(value); v != nil {
		if m.sum == nil {
			m.sum = new(float64)
		}
		*m.sum += *v
	}
}

func longActivity(ctx context.Context, tx pgx.Tx, r *metrics.Run, facts []checkin, zone *time.Location) (*metrics.Result, error) {
	refs := runRefs(r)
	out := metrics.Result{MetricID: "long_run_exposure", MethodVersion: "v1", SubjectType: "activity", SubjectKey: r.ID.String(), WindowStart: &r.Start, WindowEnd: r.End, WindowLabel: r.Day, Config: longConfig, SourceRefs: refs, Timezone: zone.String()}
	if !r.Eligible {
		out.Status = "not_applicable"
		out.ReasonCodes = []string{"ACTIVITY_EXCLUDED"}
		return &out, nil
	}
	day, err := time.ParseInLocation(time.DateOnly, r.Day, zone)
	if err != nil {
		return nil, err
	}
	start, week, end := day.AddDate(0, 0, -30), day.AddDate(0, 0, -6), day.AddDate(0, 0, 1)
	history, err := runsBetween(ctx, tx, start, end)
	if err != nil {
		return nil, err
	}
	weekCoverage, err := covered(ctx, tx, week, end)
	if err != nil {
		return nil, err
	}
	compCoverage, err := covered(ctx, tx, start, end)
	if err != nil {
		return nil, err
	}
	uid, linked, recipe, err := planLink(ctx, tx, r, refs)
	if err != nil {
		return nil, err
	}
	ids, checkins := checkinRefs(facts, false)
	delayed := "unknown"
	for _, c := range facts {
		if c.kind == "delayed_followup" {
			if delayed == "unknown" {
				delayed = "none_reported"
			}
			for _, rep := range c.reports {
				if rep.severity > 0 {
					delayed = "reported"
				}
			}
		}
	}
	priorIDs := []uuid.UUID{r.ID}
	later := []uuid.UUID{}
	hist := []object{}
	timers := []float64{}
	recent := false
	partialComp, partialWeek := !compCoverage, !weekCoverage
	var timer, distance comparisonMeasure
	for _, h := range history {
		hist = append(hist, object{"activity_id": h.ID, "source_revision": h.SourceRevision, "source_refs": h.Refs})
		valid := usable(h.Timer) != nil && usable(h.Distance) != nil
		if h.Day >= week.Format(time.DateOnly) {
			timer.week(h.Timer)
			distance.week(h.Distance)
			partialWeek = partialWeek || !valid
		}
		if h.ID == r.ID {
			continue
		}
		if h.Day >= day.AddDate(0, 0, -14).Format(time.DateOnly) && h.Day < r.Day {
			recent = true
		}
		if h.Start.Before(r.Start) {
			priorIDs = append(priorIDs, h.ID)
			timer.prior(h.Timer, h.Sport)
			distance.prior(h.Distance, h.Sport)
			partialComp = partialComp || !valid
			if h.Day >= day.AddDate(0, 0, -28).Format(time.DateOnly) && usable(h.Timer) != nil {
				timers = append(timers, *h.Timer)
			}
		} else if h.Day >= week.Format(time.DateOnly) {
			later = append(later, h.ID)
		}
	}
	refs["activity_ids"], refs["weekly_other_activity_ids"], refs["history"] = priorIDs, later, hist
	refs["session_uid"], refs["plan_linked"], refs["plan_recipe"] = uid, linked, recipe
	refs["checkin_ids"], refs["checkins"] = ids, checkins
	refs["coverage_complete_week"], refs["coverage_complete_comparator"] = weekCoverage, compCoverage
	hash, err := metrics.Digest(object{"history": hist, "plan": refs["plan"], "completion_association_hash": refs["completion_association_hash"], "checkins": checkins, "coverage_complete_week": weekCoverage, "coverage_complete_comparator": compCoverage})
	if err != nil {
		return nil, err
	}
	refs["input_hash"] = hash
	classification, source, confidence := "not_long", "long_rule", "low"
	switch {
	case linked:
		source, confidence = "plan_link", "high"
		if recipe != nil && *recipe == "REC002" {
			classification = "long"
		}
	case r.Label != nil:
		source, confidence = "manual", "high"
		if *r.Label == "long" {
			classification = "long"
		}
	case usable(r.Timer) == nil || len(timers) < 4:
		classification = "unknown"
	default:
		slices.Sort(timers)
		m := len(timers) / 2
		median := timers[m]
		if len(timers)%2 == 0 {
			median = (timers[m-1] + median) / 2
		}
		if *r.Timer >= 1.33*median {
			classification = "long"
		}
	}
	v := object{"activity_id": r.ID, "local_date": r.Day, "timer_s": usable(r.Timer), "distance_m": usable(r.Distance), "classification": classification, "classification_source": source, "classification_confidence": confidence, "delayed_symptom_status": delayed, "linked_checkin_ids": ids}
	out.Value = v
	switch classification {
	case "not_long":
		out.Status = "not_applicable"
		out.ReasonCodes = []string{"NOT_LONG_RUN"}
	case "unknown":
		out.Status = "not_assessable"
		out.ReasonCodes = []string{"CLASSIFICATION_UNKNOWN"}
		if len(timers) < 4 {
			out.ReasonCodes = append(out.ReasonCodes, "INSUFFICIENT_HISTORY")
		}
		if usable(r.Timer) == nil {
			out.ReasonCodes = append(out.ReasonCodes, "TIMER_MISSING")
		}
	case "long":
		rt, rd := proportion(usable(r.Timer), timer.max), proportion(usable(r.Distance), distance.max)
		wt, wd := proportion(usable(r.Timer), timer.sum), proportion(usable(r.Distance), distance.sum)
		v["prior_max_timer_s"], v["prior_max_distance_m"], v["week_timer_s"], v["week_distance_m"] = roundedValue(timer.max), roundedValue(distance.max), roundedValue(timer.sum), roundedValue(distance.sum)
		v["duration_ratio_to_recent_max"], v["distance_ratio_to_recent_max"], v["weekly_share_duration"], v["weekly_share_distance"] = rt, rd, wt, wd
		v["comparator_window"] = object{"start_date": start.Format(time.DateOnly), "end_date": r.Day}
		v["weekly_window"] = object{"start_date": week.Format(time.DateOnly), "end_date": r.Day}
		if len(priorIDs) == 1 {
			out.ReasonCodes = append(out.ReasonCodes, "INSUFFICIENT_HISTORY")
		}
		if usable(r.Timer) == nil {
			out.ReasonCodes = append(out.ReasonCodes, "TIMER_MISSING")
		}
		if usable(r.Distance) == nil {
			out.ReasonCodes = append(out.ReasonCodes, "DISTANCE_MISSING")
		}
		if !recent {
			out.QualityFlags = append(out.QualityFlags, "RETURN_FROM_BREAK")
		}
		if (timer.max != nil && timer.maxSport != r.Sport) || (distance.max != nil && distance.maxSport != r.Sport) {
			out.QualityFlags = append(out.QualityFlags, "SURFACE_NOT_COMPARABLE")
		}
		if partialComp {
			out.QualityFlags = append(out.QualityFlags, "PARTIAL_COMPARATOR")
		}
		if partialWeek {
			out.QualityFlags = append(out.QualityFlags, "PARTIAL_WEEK")
		}
		if !weekCoverage {
			out.QualityFlags = append(out.QualityFlags, "SYNC_COVERAGE_INCOMPLETE")
		}
		if source == "long_rule" {
			out.QualityFlags = append(out.QualityFlags, "LOW_CONFIDENCE_CLASSIFICATION")
		}
		out.Status, out.QualityStatus = "available", "good"
		if rt == nil || rd == nil || wt == nil || wd == nil {
			out.Status = "partial"
		}
		if out.Status == "partial" || len(out.QualityFlags) > 0 {
			out.QualityStatus = "limited"
		}
	}
	return &out, nil
}

// RefreshRun loads linked check-ins and refreshes symptoms, session RPE and long-run exposure for a recording.
func RefreshRun(ctx context.Context, tx pgx.Tx, id uuid.UUID, zone string, now time.Time) error {
	r, err := metrics.LoadRun(ctx, tx, id, zone)
	if err != nil {
		return err
	}
	if r == nil || !isRunning(r.Sport) {
		_, err := tx.Exec(ctx, `UPDATE metric_results SET is_current=false WHERE subject_key=$1 AND metric_id IN ('session_rpe_load','symptom_response_timeline','long_run_exposure') AND method_version='v1' AND is_current`, id.String())
		return err
	}
	facts, err := linkedCheckins(ctx, tx, id, zone)
	if err != nil {
		return err
	}
	loc, err := time.LoadLocation(zone)
	if err != nil {
		return err
	}
	symptoms, err := symptomActivity(ctx, tx, r, facts, zone)
	if err != nil {
		return err
	}
	if _, err := metrics.StoreResult(ctx, tx, *symptoms, now); err != nil {
		return err
	}
	if err := RefreshRunRPE(ctx, tx, id, zone, now); err != nil {
		return err
	}
	long, err := longActivity(ctx, tx, r, facts, loc)
	if err != nil {
		return err
	}
	_, err = metrics.StoreResult(ctx, tx, *long, now)
	return err
}
