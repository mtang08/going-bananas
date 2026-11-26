package aerobic

import (
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/recording"
	"math"
	"slices"
	"strconv"
)

type obj = map[string]any
type stream = recording.Stream
type sample struct {
	i         int
	s         float64
	first     bool
	speed, hr *float64
}
type outcome struct {
	status, quality string
	reasons, flags  []string
	value           obj
}

func early(status, r string) outcome {
	return outcome{status: status, reasons: []string{r}, flags: []string{}}
}
func round(v float64, d int) float64 {
	n, _ := strconv.ParseFloat(strconv.FormatFloat(v, 'f', d, 64), 64)
	return n
}
func at(a []*float64, i int) *float64 {
	if i < 0 || i >= len(a) {
		return nil
	}
	return a[i]
}
func rangeValue(v *float64, lo, hi float64) *float64 {
	if v != nil && *v >= lo && *v <= hi {
		return v
	}
	return nil
}
func coverage(p, total float64) string {
	if total <= 0 || p/total < .7 {
		return "insufficient"
	}
	if p/total < .9 {
		return "limited"
	}
	return "good"
}
func trim(spans []recording.Span) ([]recording.Span, int, error) {
	merged, err := recording.Union(spans)
	if err != nil {
		return nil, 0, err
	}
	var out []recording.Span
	warm := 600.
	pauses := 0
	for i, s := range merged {
		used := min(warm, s[1]-s[0])
		warm -= used
		start := s[0] + used
		resume := min(s[0]+60, s[1])
		if i > 0 && start < resume {
			start = resume
			pauses++
		}
		if start < s[1] {
			out = append(out, recording.Span{start, s[1]})
		}
	}
	return out, pauses, nil
}

type stats struct{ moving, paired, hr, speed float64 }

func (s *stats) add(v sample) {
	s.moving += v.s
	if v.speed != nil && v.hr != nil {
		s.paired += v.s
		s.hr += *v.hr * v.s
		s.speed += *v.speed * v.s
	}
}
func (s stats) ef() float64 { return 60 * (s.speed / s.paired) / (s.hr / s.paired) }
func cv(samples []sample) *float64 {
	var bins []float64
	var total, weight float64
	for _, s := range samples {
		if s.hr == nil || s.speed == nil || *s.speed < 1.5 {
			continue
		}
		secs := s.s
		for secs >= 60-weight {
			need := 60 - weight
			bins = append(bins, (total+*s.speed*need)/60)
			secs -= need
			total = 0
			weight = 0
		}
		total += *s.speed * secs
		weight += secs
	}
	if len(bins) < 2 {
		return nil
	}
	var mean float64
	for _, b := range bins {
		mean += b
	}
	mean /= float64(len(bins))
	var dev float64
	for _, b := range bins {
		dev += (b - mean) * (b - mean)
	}
	v := 100 * math.Sqrt(dev/float64(len(bins)-1)) / mean
	return &v
}
func decoupling(halves [2]stats, secs float64) obj {
	d := obj{"status": "not_assessable", "reason_codes": []string{}, "pct": nil, "first_ef_m_per_beat": nil, "second_ef_m_per_beat": nil, "first_mean_hr_bpm": nil, "second_mean_hr_bpm": nil, "first_mean_speed_mps": nil, "second_mean_speed_mps": nil, "half_s": round(secs/2, 1)}
	if secs < 2400 {
		d["reason_codes"] = []string{"DECOUPLING_TOO_SHORT"}
		return d
	}
	limited := false
	for i, p := range []string{"first", "second"} {
		s := halves[i]
		q := coverage(s.paired, s.moving)
		if q == "insufficient" {
			d["reason_codes"] = []string{"HALF_LOW_COVERAGE"}
			return d
		}
		limited = limited || q == "limited"
		d[p+"_ef_m_per_beat"] = round(s.ef(), 3)
		d[p+"_mean_hr_bpm"] = round(s.hr/s.paired, 1)
		d[p+"_mean_speed_mps"] = round(s.speed/s.paired, 3)
	}
	d["status"] = "available"
	if limited {
		d["status"] = "partial"
		d["reason_codes"] = []string{"HALF_LOW_COVERAGE"}
	}
	d["pct"] = round(100*(halves[0].ef()-halves[1].ef())/halves[0].ef(), 2)
	return d
}
func calculate(s *stream, treadmill bool) (outcome, error) {
	if s == nil {
		return early("not_assessable", "NO_STREAM"), nil
	}
	for _, f := range []string{"TIMER_EVENTS_MISSING", "TIMER_EVENTS_AMBIGUOUS", "TIMER_MISMATCH"} {
		if slices.Contains(s.Flags, f) {
			return early("not_assessable", f), nil
		}
	}
	present := func(v *float64) bool { return v != nil }
	if !slices.ContainsFunc(s.HR, present) {
		return early("not_assessable", "HR_NOT_RECORDED"), nil
	}
	if !slices.ContainsFunc(s.Speed, present) {
		return early("not_assessable", "SPEED_NOT_RECORDED"), nil
	}
	spans, pauses, err := trim(s.Timer)
	if err != nil {
		return outcome{}, err
	}
	if len(spans) == 0 {
		return early("not_assessable", "TOO_SHORT"), nil
	}
	pieces, err := recording.Integrate(s.Times, spans)
	if err != nil {
		return outcome{}, err
	}
	var secs float64
	for _, p := range pieces {
		secs += p.Seconds
	}
	if secs < 1200 {
		return early("not_assessable", "TOO_SHORT"), nil
	}
	var samples []sample
	var elapsed, stopped float64
	var whole stats
	var halves [2]stats
	for _, p := range pieces {
		first := min(p.Seconds, max(0, secs/2-elapsed))
		for half, weight := range [2]float64{first, p.Seconds - first} {
			if weight <= 0 {
				continue
			}
			v := sample{p.Index, weight, half == 0, rangeValue(at(s.Speed, p.Index), 0, 10), rangeValue(at(s.HR, p.Index), 30, 230)}
			samples = append(samples, v)
			if v.speed != nil && *v.speed < 1.5 {
				stopped += weight
			} else {
				whole.add(v)
				halves[half].add(v)
			}
		}
		elapsed += p.Seconds
	}
	if stopped/secs > .1 {
		return early("not_assessable", "TOO_MANY_STOPS"), nil
	}
	moving := secs - stopped
	q := coverage(whole.paired, moving)
	if q == "insufficient" {
		return early("not_assessable", "LOW_COVERAGE"), nil
	}
	speedCV := cv(samples)
	var roundedCV any
	if speedCV != nil {
		if *speedCV > 15 {
			return early("not_assessable", "PACE_NOT_STEADY"), nil
		}
		roundedCV = round(*speedCV, 2)
	}
	flags := []string{}
	if stopped > 0 {
		flags = append(flags, "STOPS_EXCLUDED")
	}
	if pauses > 0 {
		flags = append(flags, "PAUSES_TRIMMED")
	}
	el := elevation(s, samples, treadmill)
	de := decoupling(halves, secs)
	if diff, ok := el["half_grade_diff_pct"].(float64); ok && math.Abs(diff) > 1 && de["pct"] != nil {
		de["status"] = "not_assessable"
		de["reason_codes"] = []string{"HALF_GRADE_DIFFERS"}
		de["pct"] = nil
	}
	if treadmill {
		flags = append(flags, "TREADMILL")
	}
	if el["status"] == "missing" {
		flags = append(flags, "ELEVATION_UNKNOWN")
	}
	if gain, ok := el["gain_m_per_km"].(float64); ok && gain > 15 {
		flags = append(flags, "HILLY_ROUTE")
	}
	for k, d := range map[string]int{"gain_m": 1, "loss_m": 1, "gain_m_per_km": 2, "half_grade_diff_pct": 2} {
		if x, ok := el[k].(float64); ok {
			el[k] = round(x, d)
		}
	}
	slices.Sort(flags)
	status := "available"
	reasons := []string{}
	if q != "good" {
		status = "partial"
		reasons = append(reasons, "LOW_COVERAGE")
	}
	return outcome{status, q, reasons, flags, obj{"analysis_s": round(secs, 1), "moving_s": round(moving, 1), "paired_s": round(whole.paired, 1), "stopped_s": round(stopped, 1), "coverage": round(whole.paired/moving, 3), "mean_speed_mps": round(whole.speed/whole.paired, 3), "mean_hr_bpm": round(whole.hr/whole.paired, 1), "ef_m_per_beat": round(whole.ef(), 3), "speed_cv_pct": roundedCV, "pauses_trimmed": pauses, "decoupling": de, "elevation": el}}, nil
}
