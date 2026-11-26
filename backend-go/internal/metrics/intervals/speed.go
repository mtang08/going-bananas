package intervals

import (
	"cmp"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/recording"
	"math"
	"slices"
)

type speedData struct {
	status                                    string
	reasons                                   []string
	mean, coverage, targetValid, targetIn, hr *float64
	inTarget                                  *bool
	eligible, valid                           float64
}

func ptr[T any](v T) *T       { return &v }
func numeric(v *float64) bool { return v != nil && !math.IsNaN(*v) && !math.IsInf(*v, 0) }
func get(a []*float64, i int, lo, hi float64) *float64 {
	if i >= 0 && i < len(a) && numeric(a[i]) && *a[i] >= lo && *a[i] <= hi {
		return a[i]
	}
	return nil
}
func bounds(l lap, all []lap) (float64, string) {
	switch {
	case numeric(l.elapsed):
		return l.start + *l.elapsed, ""
	case numeric(l.end):
		return *l.end, ""
	default:
		next := math.Inf(1)
		for _, x := range all {
			if x.start > l.start {
				next = min(next, x.start)
			}
		}
		if math.IsInf(next, 1) {
			return 0, "LAP_END_UNKNOWN"
		}
		return next, ""
	}
}
func hrMedian(s *recording.Stream, timer []recording.Span) (*float64, error) {
	var selected []recording.Span
	skip := 60.
	for _, span := range timer {
		used := min(skip, span[1]-span[0])
		skip -= used
		if span[0]+used < span[1] {
			selected = append(selected, recording.Span{span[0] + used, span[1]})
		}
	}
	pieces, err := recording.Integrate(s.Times, selected)
	if err != nil {
		return nil, err
	}
	var values [][2]float64
	var sum float64
	for _, p := range pieces {
		if x := get(s.HR, p.Index, 30, 230); x != nil {
			values = append(values, [2]float64{*x, p.Seconds})
			sum += p.Seconds
		}
	}
	slices.SortFunc(values, func(a, b [2]float64) int { return cmp.Compare(a[0], b[0]) })
	cur := 0.
	for i, x := range values {
		cur += x[1]
		if cur == sum/2 && i+1 < len(values) {
			return ptr((x[0] + values[i+1][0]) / 2), nil
		}
		if cur >= sum/2 {
			return ptr(x[0]), nil
		}
	}
	return nil, nil
}
func confirmed(laps []lap) *float64 {
	var timer, dist float64
	for _, l := range laps {
		if !numeric(l.timer) || *l.timer <= 0 {
			return nil
		}
		switch {
		case numeric(l.pace) && *l.pace > 0:
			dist += *l.timer * 1609.344 / *l.pace
		case numeric(l.speed) && *l.speed >= 0 && *l.speed <= 10:
			dist += *l.timer * *l.speed
		case numeric(l.distance) && *l.distance >= 0:
			dist += *l.distance
		default:
			return nil
		}
		timer += *l.timer
	}
	if timer == 0 {
		return nil
	}
	return ptr(dist / timer)
}
func speed(s *recording.Stream, laps, all []lap, p repPlan, lapTimer *float64) (speedData, error) {
	d := speedData{status: "not_assessable", reasons: []string{}}
	if len(laps) == 0 {
		d.status = "missing"
		return d, nil
	}
	if s == nil {
		d.reasons = []string{"NO_STREAM"}
		return d, nil
	}
	for _, f := range []string{"TIMER_EVENTS_MISSING", "TIMER_EVENTS_AMBIGUOUS", "TIMER_MISMATCH"} {
		if slices.Contains(s.Flags, f) {
			d.reasons = []string{f}
			return d, nil
		}
	}
	var clips []recording.Span
	for _, l := range laps {
		end, issue := bounds(l, all)
		if issue == "" && end <= l.start {
			issue = "LAP_BOUNDS_INVALID"
		}
		if issue != "" {
			d.reasons = []string{issue}
			return d, nil
		}
		for _, t := range s.Timer {
			left, right := max(t[0], l.start), min(t[1], end)
			if left < right {
				clips = append(clips, recording.Span{left, right})
			}
		}
	}
	full, err := recording.Union(s.Timer)
	if err != nil {
		return d, err
	}
	if _, err := recording.Integrate(s.Times, full); err != nil {
		return d, err
	}
	clips, err = recording.Union(clips)
	if err != nil {
		return d, err
	}
	pieces, err := recording.Integrate(s.Times, clips)
	if err != nil {
		return d, err
	}
	var weighted, target float64
	for _, v := range pieces {
		d.eligible += v.Seconds
		if x := get(s.Speed, v.Index, 0, 10); x != nil {
			d.valid += v.Seconds
			weighted += *x * v.Seconds
			if p.required() && *x >= *p.Target.Low && *x <= *p.Target.High {
				target += v.Seconds
			}
		}
	}
	if d.eligible == 0 {
		d.reasons = []string{"NO_TIMER_ON_DATA"}
	} else {
		d.coverage = ptr(d.valid / d.eligible)
		if d.valid == 0 {
			d.reasons = []string{"NO_SPEED_SAMPLES"}
		} else {
			d.mean = ptr(weighted / d.valid)
			d.status = "available"
			if *d.coverage < .9 {
				d.status = "partial"
				d.reasons = []string{"LOW_COVERAGE"}
			}
			if p.required() {
				d.targetValid = ptr(d.valid)
				d.targetIn = ptr(target)
				d.inTarget = ptr(*p.Target.Low <= *d.mean && *d.mean <= *p.Target.High)
			}
		}
	}
	if numeric(lapTimer) && *lapTimer >= 180 {
		d.hr, err = hrMedian(s, clips)
	}
	return d, err
}
