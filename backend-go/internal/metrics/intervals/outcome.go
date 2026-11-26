package intervals

import (
	"cmp"
	"github.com/mtang08/going-bananas/backend-go/internal/calendarstructure"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/recording"
	"math"
	"slices"
	"strconv"
)

type obj = map[string]any
type repPlan struct {
	calendarstructure.Step
	effective float64
}

func (p repPlan) required() bool {
	return p.Target != nil && p.Target.Modality == "speed" && numeric(p.Target.Low) && numeric(p.Target.High) && *p.Target.Low <= *p.Target.High
}
func (p repPlan) complete(v float64) bool {
	if p.DurationType == "time" {
		return v >= p.effective-min(1, .005*p.effective)
	}
	return v/p.effective >= .99
}
func rounded(v float64, d int) float64 {
	x, _ := strconv.ParseFloat(strconv.FormatFloat(v, 'f', d, 64), 64)
	return x
}
func opt(v *float64, d int) any {
	if !numeric(v) {
		return nil
	}
	return rounded(*v, d)
}
func sum(laps []lap, timer bool) *float64 {
	if len(laps) == 0 {
		return nil
	}
	n := 0.
	for _, l := range laps {
		x := l.distance
		if timer {
			x = l.timer
		}
		if !numeric(x) {
			return nil
		}
		n += *x
	}
	return &n
}
func set(v []string) []string {
	if v == nil {
		return []string{}
	}
	slices.Sort(v)
	return slices.Compact(v)
}

type outcome struct {
	status, quality string
	flags, reasons  []string
	value           obj
}

func early(status, reason string) outcome {
	return outcome{status: status, reasons: []string{reason}, flags: []string{}}
}

type rep struct {
	value           obj
	speed           speedData
	timer, distance *float64
	done, observed  bool
	reasons, flags  []string
}

func evaluate(p repPlan, n int, laps, all []lap, s *recording.Stream, treadmill bool) (rep, error) {
	r := rep{observed: len(laps) > 0, timer: sum(laps, true), distance: sum(laps, false)}
	actual := r.timer
	if p.DurationType != "time" {
		actual = r.distance
	}
	var ratio *float64
	if numeric(actual) {
		ratio = ptr(*actual / p.effective)
		r.done = p.complete(*actual)
		if r.done && *ratio < 1 {
			r.flags = append(r.flags, "COMPLETED_WITHIN_TOLERANCE")
		}
	}
	switch {
	case !r.observed:
		r.reasons = append(r.reasons, "WORK_STEP_NOT_RECORDED")
	case ratio == nil:
		r.reasons = append(r.reasons, "COMPLETION_VALUE_MISSING")
	case !r.done:
		r.reasons = append(r.reasons, "INCOMPLETE_WORK_STEP")
	}
	d, err := speed(s, laps, all, p, r.timer)
	if err != nil {
		return r, err
	}
	if r.observed {
		if r.timer == nil {
			r.flags = append(r.flags, "HR_TIMER_UNKNOWN")
		} else if *r.timer < 180 {
			r.flags = append(r.flags, "HR_NOT_REPORTED_SHORT_STEP")
		}
	}
	if treadmill && slices.ContainsFunc(laps, func(l lap) bool { return l.pace != nil }) {
		d.mean = confirmed(laps)
		d.status = "available"
		d.reasons = []string{}
		if d.mean == nil {
			d.status = "not_assessable"
			d.reasons = []string{"LAP_SPEED_MISSING"}
		}
		d.coverage, d.targetValid, d.targetIn, d.inTarget = nil, nil, nil, nil
		d.eligible, d.valid = 0, 0
		if p.required() && d.mean != nil {
			d.inTarget = ptr(*p.Target.Low <= *d.mean && *d.mean <= *p.Target.High)
		}
		r.flags = append(r.flags, "TREADMILL_PACE_CONFIRMED")
	}
	modality := "effort"
	var low, high *float64
	if p.Target != nil {
		modality = p.Target.Modality
		low, high = p.Target.Low, p.Target.High
	}
	if modality == "hr" {
		r.flags = append(r.flags, "HR_TARGET_NOT_SCORED")
	}
	if p.required() && r.observed {
		switch d.status {
		case "not_assessable":
			r.reasons = append(r.reasons, "COMPONENT_NOT_ASSESSABLE")
		case "partial":
			r.reasons = append(r.reasons, "LOW_COVERAGE")
		}
	}
	status := "available"
	if !r.observed {
		status = "missing"
	} else if len(r.reasons) > 0 {
		status = "partial"
	}
	indexes := make([]int, len(laps))
	for i, l := range laps {
		indexes[i] = l.index
	}
	r.speed = d
	r.value = obj{"rep": n, "planned_step": p.ExpandedStep, "step_path": p.StepPath, "repeat_index": p.RepeatIndex, "lap_indexes": indexes, "observed": r.observed, "fully_completed": r.done, "status": status, "reason_codes": set(r.reasons), "planned_duration_type": p.DurationType, "planned_value": p.DurationValue, "actual_timer_s": opt(r.timer, 1), "actual_distance_m": opt(r.distance, 1), "completion_ratio": opt(ratio, 3), "mean_speed_mps": opt(d.mean, 3), "speed_status": d.status, "speed_reason_codes": set(d.reasons), "speed_coverage": opt(d.coverage, 3), "target_modality": modality, "target_low": low, "target_high": high, "target_valid_s": opt(d.targetValid, 1), "target_in_range_s": opt(d.targetIn, 1), "in_target": d.inTarget, "hr_median_bpm": opt(d.hr, 1), "flags": set(r.flags)}
	return r, nil
}
func execute(plans []calendarstructure.Step, fit []recording.FitStep, laps []lap, s *recording.Stream, treadmill bool) (outcome, error) {
	var work []calendarstructure.Step
	for _, p := range plans {
		if p.Type == "work" {
			work = append(work, p)
		}
	}
	if len(work) == 0 {
		return early("not_applicable", "NO_WORK_STEPS"), nil
	}
	watch, err := recording.Expand(fit)
	if err != nil {
		return early("not_assessable", err.Error()), nil
	}
	var positions []int
	for i, w := range watch {
		if w.Intensity == "active" || w.Intensity == "interval" {
			positions = append(positions, i)
		}
	}
	if len(positions) != len(work) {
		return early("not_assessable", "WATCH_WORKOUT_MISMATCH"), nil
	}
	out := outcome{}
	paired := map[int]repPlan{}
	for i, pos := range positions {
		w, p := watch[pos], work[i]
		if p.DurationType != w.Duration {
			return early("not_assessable", "WATCH_WORKOUT_MISMATCH"), nil
		}
		eff := p.DurationValue
		if numeric(w.Value) && *w.Value > 0 {
			diff := math.Abs(*w.Value-eff) / eff
			if diff > .5 {
				return early("not_assessable", "WATCH_WORKOUT_MISMATCH"), nil
			}
			if diff <= .01 {
				eff = min(eff, *w.Value)
			} else {
				out.reasons = append(out.reasons, "WATCH_PLAN_DURATION_DIFFERS")
			}
		}
		paired[pos] = repPlan{p, eff}
	}
	laps = slices.Clone(laps)
	slices.SortFunc(laps, func(a, b lap) int { return cmp.Compare(a.index, b.index) })
	for i := 1; i < len(laps); i++ {
		if laps[i-1].index == laps[i].index {
			return early("not_assessable", "LAP_STEP_ORDER_MISMATCH"), nil
		}
	}
	a := align(watch, paired, laps)
	if a.err != "" {
		return early("not_assessable", a.err), nil
	}
	out.flags = append(out.flags, a.flags...)
	for pos, assigned := range a.assigned {
		_, w := paired[pos]
		for _, idx := range assigned {
			l := laps[idx]
			if l.intensity != nil && (*l.intensity == "active" || *l.intensity == "interval") != w {
				out.flags = append(out.flags, "LAP_INTENSITY_DISAGREES")
			}
		}
	}
	for _, pos := range a.omitted {
		if _, ok := paired[pos]; ok {
			out.reasons = append(out.reasons, "WORK_STEP_SKIPPED")
		}
	}
	for _, pos := range a.tail {
		if _, ok := paired[pos]; ok {
			out.reasons = append(out.reasons, "WORKOUT_ENDED_EARLY")
		}
	}
	var eligible, valid, targetValid, targetIn, secs, meters, plannedSec, plannedM float64
	var observed, done, hasTimer, hasM, secPlans int
	var bad bool
	var valids []float64
	var reps []rep
	values := make([]obj, 0, len(positions))
	for i, pos := range positions {
		p := paired[pos]
		part := make([]lap, 0, len(a.assigned[pos]))
		for _, idx := range a.assigned[pos] {
			part = append(part, laps[idx])
		}
		r, err := evaluate(p, i+1, part, laps, s, treadmill)
		if err != nil {
			return out, err
		}
		reps = append(reps, r)
		values = append(values, r.value)
		out.flags = append(out.flags, r.flags...)
		out.reasons = append(out.reasons, r.reasons...)
		if r.observed {
			observed++
		}
		if r.done {
			done++
			if r.speed.status == "available" && r.speed.mean != nil {
				valids = append(valids, *r.speed.mean)
			}
		}
		if p.DurationType == "time" {
			secPlans++
			plannedSec += p.DurationValue
		} else {
			plannedM += p.DurationValue
		}
		if r.timer != nil {
			secs += *r.timer
			hasTimer++
		}
		if r.distance != nil {
			meters += *r.distance
			hasM++
		}
		if p.required() && r.observed {
			d := r.speed
			bad = bad || d.status == "not_assessable"
			eligible += d.eligible
			valid += d.valid
			if d.targetValid != nil && d.targetIn != nil {
				targetValid += *d.targetValid
				targetIn += *d.targetIn
			}
		}
	}
	total := len(reps)
	if done < total {
		out.reasons = append(out.reasons, "INCOMPLETE_WORK_STEPS")
	}
	subtotal := func(amount float64, n int, flag string) any {
		if observed == 0 {
			return 0.
		}
		if n < observed {
			out.reasons = append(out.reasons, "WORK_MEASUREMENT_MISSING")
			if n > 0 {
				out.flags = append(out.flags, flag)
			}
		}
		if n == 0 {
			return nil
		}
		return rounded(amount, 1)
	}
	v := obj{"reps": values, "n_planned": total, "n_observed": observed, "n_completed": done, "step_completion_ratio": rounded(float64(done)/float64(total), 3), "cv_speed": nil, "last_first_change_pct": nil, "completed_work_s": subtotal(secs, hasTimer, "PARTIAL_WORK_TIMER"), "completed_work_m": subtotal(meters, hasM, "PARTIAL_WORK_DISTANCE"), "planned_work_s": nil, "planned_work_m": nil, "target_coverage": nil}
	if secPlans == total {
		v["planned_work_s"] = rounded(plannedSec, 1)
	}
	if secPlans == 0 {
		v["planned_work_m"] = rounded(plannedM, 1)
	}
	if targetValid > 0 {
		v["target_coverage"] = rounded(targetIn/targetValid, 3)
	}
	if len(valids) >= 2 {
		var avg, dev float64
		for _, x := range valids {
			avg += x
		}
		avg /= float64(len(valids))
		if avg > 0 {
			for _, x := range valids {
				dev += (x - avg) * (x - avg)
			}
			v["cv_speed"] = rounded(100*math.Sqrt(dev/float64(len(valids)-1))/avg, 3)
		} else {
			out.flags = append(out.flags, "ZERO_SPEED_DENOMINATOR")
		}
	}
	first, last := reps[0], reps[total-1]
	if first.done && last.done && first.speed.status == "available" && last.speed.status == "available" && first.speed.mean != nil && last.speed.mean != nil {
		if *first.speed.mean > 0 {
			v["last_first_change_pct"] = rounded(100*(*last.speed.mean-*first.speed.mean) / *first.speed.mean, 3)
		} else {
			out.flags = append(out.flags, "ZERO_SPEED_DENOMINATOR")
		}
	}
	if treadmill {
		out.flags = append(out.flags, "TREADMILL")
	}
	if eligible > 0 {
		out.quality = "good"
		if valid/eligible < .7 {
			out.quality = "insufficient"
		} else if valid/eligible < .9 || bad {
			out.quality = "limited"
		}
	}
	out.value = v
	out.status = "available"
	if len(out.reasons) > 0 {
		out.status = "partial"
	}
	out.flags = set(out.flags)
	out.reasons = set(out.reasons)
	return out, nil
}
