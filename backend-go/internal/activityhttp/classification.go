package activityhttp

import (
	"math"
	"slices"
	"strconv"
	"time"
)

type activity struct {
	id, sport, state              string
	start                         time.Time
	day                           string
	distance, elapsed, moving, hr *float64
	manual, source                *string
	excluded                      bool
	data                          object
}

func eligible(a activity) bool {
	return !a.excluded && a.state == "resolved" && slices.Contains([]string{"running", "trail_running", "treadmill_running"}, a.sport)
}
func positive(x *float64) bool { return x != nil && *x > 0 && !math.IsInf(*x, 0) && !math.IsNaN(*x) }
func pace(a activity) *float64 {
	if !positive(a.moving) || !positive(a.distance) {
		return nil
	}
	p := *a.moving / *a.distance
	return &p
}
func ratio(v *float64, history []float64, need int) *float64 {
	if !positive(v) || len(history) < need {
		return nil
	}
	slices.Sort(history)
	i := len(history) / 2
	m := history[i]
	if len(history)%2 == 0 {
		m = (history[i-1] + m) / 2
	}
	r, _ := strconv.ParseFloat(strconv.FormatFloat(*v/m, 'f', 3, 64), 64)
	return &r
}
func classify(a activity, history []activity, longDays []int) object {
	var prior int
	var samples [4][]float64
	for _, b := range history {
		if !eligible(b) || !b.start.Before(a.start) || b.start.Before(a.start.Add(-84*24*time.Hour)) {
			continue
		}
		prior++
		for i, v := range []*float64{b.elapsed, b.distance, pace(b), b.hr} {
			if positive(v) {
				samples[i] = append(samples[i], *v)
			}
		}
	}
	duration, distance, pacing, hr := ratio(a.elapsed, samples[0], 6), ratio(a.distance, samples[1], 6), ratio(pace(a), samples[2], 4), ratio(a.hr, samples[3], 4)
	effort := "unavailable"
	if hr != nil {
		effort = "similar_average_hr"
		if *hr >= 1.08 {
			effort = "higher_average_hr"
		} else if *hr <= .93 {
			effort = "lower_average_hr"
		}
	}
	d, _ := time.Parse(time.DateOnly, a.day)
	long := slices.Contains(longDays, (int(d.Weekday())+6)%7)
	labels := []string{"easy", "quality", "long", "other"}
	var suggestion *string
	label, origin, confidence := "unknown", "unknown", "insufficient"
	var reasons []string
	switch {
	case a.manual != nil && slices.Contains(labels, *a.manual):
		label, origin, confidence = *a.manual, "manual", "confirmed"
		reasons = append(reasons, "Athlete correction takes precedence over source and relative suggestion.")
	case a.source != nil && slices.Contains(labels, *a.source):
		label, origin, confidence = *a.source, "source", "confirmed"
		reasons = append(reasons, "Explicit source workout label takes precedence over relative suggestion.")
	case prior < 6:
		reasons = append(reasons, "Fewer than six earlier runs in the preceding 12 weeks.")
	case long && duration != nil && distance != nil && *a.elapsed >= 2700 && *duration >= 1.25 && *distance >= 1.2:
		label, origin, confidence = "long", "heuristic", "medium"
		reasons = append(reasons, "Weekend run is longer in both time and distance than recent personal runs.")
	case hr != nil && pacing != nil && *hr >= 1.08 && *pacing <= .93:
		label, origin, confidence = "quality", "heuristic", "low"
		reasons = append(reasons, "Average heart rate is higher and moving pace faster than recent personal runs.")
	case hr != nil && pacing != nil && *hr <= .98 && *pacing >= .97:
		label, origin, confidence = "easy", "heuristic", "low"
		reasons = append(reasons, "Average heart rate is lower and moving pace is not notably faster than recent personal runs.")
	default:
		reasons = append(reasons, "Available relative measures do not jointly support a run-type suggestion.")
	}
	if origin == "heuristic" {
		suggestion = &label
	}
	if !long && label == "long" {
		reasons = append(reasons, "Explicit weekday long label is preserved; weekend restriction applies to suggestions.")
	}
	if hr == nil {
		reasons = append(reasons, "Average heart rate is missing or lacks enough prior comparable values.")
	}
	reasons = append(reasons, "Whole-run averages do not show intervals or heart-rate drift; route, weather, effort, and sensor differences are unmeasured.")
	return object{"method": "historical_relative_v1", "suggested_label": suggestion, "effective_label": label, "label_source": origin, "confidence": confidence, "reasons": reasons, "metrics": object{"window_days": 84, "prior_runs": prior, "duration_samples": len(samples[0]), "distance_samples": len(samples[1]), "pace_samples": len(samples[2]), "average_hr_samples": len(samples[3]), "relative_duration": duration, "relative_distance": distance, "relative_moving_pace": pacing, "relative_average_hr": hr, "effort_signal": effort}}
}
