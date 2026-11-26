package aerobic

import "math"

func elevation(s *stream, samples []sample, treadmill bool) obj {
	r := obj{"status": "missing", "gain_m": nil, "loss_m": nil, "gain_m_per_km": nil, "half_grade_diff_pct": nil}
	if treadmill {
		r["status"] = "not_applicable"
		return r
	}
	levels := make([]*float64, len(s.Times))
	lo, hi, n := 0, 0, 0
	sum := 0.
	for i, t := range s.Times {
		for hi < len(s.Times) && s.Times[hi] <= t+15 {
			if v := at(s.Altitude, hi); v != nil && !(math.IsInf(*v, 0) || math.IsNaN(*v)) {
				sum += *v
				n++
			}
			hi++
		}
		for s.Times[lo] < t-15 {
			if v := at(s.Altitude, lo); v != nil && !(math.IsInf(*v, 0) || math.IsNaN(*v)) {
				sum -= *v
				n--
			}
			lo++
		}
		if n > 0 {
			x := sum / float64(n)
			levels[i] = &x
		}
	}
	type profile struct {
		meters, first, last float64
		count               int
	}
	var halves [2]profile
	var elapsed, next, gain, loss, last float64
	count := 0
	for _, p := range samples {
		h := &halves[1]
		if p.first {
			h = &halves[0]
		}
		if p.speed != nil && *p.speed >= 1.5 {
			h.meters += *p.speed * p.s
		}
		level := at(levels, p.i)
		elapsed += p.s
		for next < elapsed {
			if level != nil {
				if count > 0 {
					gain += max(0, *level-last)
					loss += max(0, last-*level)
				}
				last = *level
				count++
				if h.count == 0 {
					h.first = *level
				}
				h.last = *level
				h.count++
			}
			next += 30
		}
	}
	meters := halves[0].meters + halves[1].meters
	if count < 2 || meters <= 0 {
		return r
	}
	r["status"] = "available"
	r["gain_m"] = gain
	r["loss_m"] = loss
	r["gain_m_per_km"] = 1000 * gain / meters
	a, b := halves[0], halves[1]
	if a.count >= 2 && b.count >= 2 && a.meters > 0 && b.meters > 0 {
		r["half_grade_diff_pct"] = 100*(b.last-b.first)/b.meters - 100*(a.last-a.first)/a.meters
	}
	return r
}
