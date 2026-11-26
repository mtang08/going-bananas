// Package spacing computes time ranges between planned and observed hard sessions.
package spacing

import (
	"slices"
	"strconv"
	"time"
)

var hardClasses = []string{"quality", "long", "lower_body_strength"}

type exposure struct {
	Key                                  string
	Day                                  string
	UID, Activity                        *string
	Source                               string
	Classes                              []string
	StartLow, StartHigh, EndLow, EndHigh time.Time
}
type object = map[string]any

func decimalHour(duration time.Duration) float64 {
	value, _ := strconv.ParseFloat(strconv.FormatFloat(duration.Hours(), 'f', 1, 64), 64)
	return value
}

func gap(left, right exposure) object {
	confidence := "low"
	if left.EndLow.Equal(left.EndHigh) && right.StartLow.Equal(right.StartHigh) {
		confidence = "high"
	}
	return object{"low": decimalHour(right.StartLow.Sub(left.EndHigh)), "high": decimalHour(right.StartHigh.Sub(left.EndLow)), "confidence": confidence}
}

func timestamp(t time.Time) string {
	layout := "2006-01-02T15:04:05"
	if t.Nanosecond() != 0 {
		layout += ".000000"
	}
	return t.UTC().Format(layout + "-07:00")
}

func orderedExposures(entries []exposure) []exposure {
	byKey := map[string]exposure{}
	for _, e := range entries {
		if len(e.Classes) == 0 {
			continue
		}
		classes := slices.Clone(e.Classes)
		if first, ok := byKey[e.Key]; ok {
			classes = append(classes, first.Classes...)
			e = first
		}
		slices.Sort(classes)
		e.Classes = slices.Compact(classes)
		byKey[e.Key] = e
	}
	ordered := make([]exposure, 0, len(byKey))
	for _, e := range byKey {
		ordered = append(ordered, e)
	}
	slices.SortFunc(ordered, func(a, b exposure) int {
		if cmp := a.StartLow.Compare(b.StartLow); cmp != 0 {
			return cmp
		}
		if a.Key < b.Key {
			return -1
		}
		if a.Key > b.Key {
			return 1
		}
		return 0
	})
	return ordered
}

func nearest(ordered []exposure, index, direction int) object {
	found := object{}
	for i := index + direction; i >= 0 && i < len(ordered) && len(found) < len(hardClasses); i += direction {
		for _, class := range ordered[i].Classes {
			if _, ok := found[class]; ok {
				continue
			}
			if direction < 0 {
				found[class] = gap(ordered[i], ordered[index])
			} else {
				found[class] = gap(ordered[index], ordered[i])
			}
		}
	}
	return found
}

func outcome(entries []exposure, asOf time.Time) object {
	ordered := orderedExposures(entries)
	first, last := asOf.AddDate(0, 0, -7).Format(time.DateOnly), asOf.AddDate(0, 0, 6).Format(time.DateOnly)
	inside := func(e exposure) bool { return first <= e.Day && e.Day <= last }
	sessions, sequence, gaps := []object{}, []object{}, []object{}
	for index, e := range ordered {
		if inside(e) {
			sessions = append(sessions, object{"session_uid": e.UID, "subject_key": e.Key, "local_date": e.Day, "hours_since": nearest(ordered, index, -1), "hours_until": nearest(ordered, index, 1)})
			sequence = append(sequence, object{"session_uid": e.UID, "activity_id": e.Activity, "subject_key": e.Key, "local_date": e.Day, "source": e.Source, "classes": e.Classes, "start_low": timestamp(e.StartLow), "start_high": timestamp(e.StartHigh), "end_low": timestamp(e.EndLow), "end_high": timestamp(e.EndHigh)})
		}
		if index == 0 || (!inside(e) && !inside(ordered[index-1])) {
			continue
		}
		left := ordered[index-1]
		g := gap(left, e)
		for _, from := range hardClasses {
			if slices.Contains(left.Classes, from) {
				for _, to := range hardClasses {
					if slices.Contains(e.Classes, to) {
						gaps = append(gaps, object{"from_class": from, "to_class": to, "from_date": left.Day, "to_date": e.Day, "hours_min": g["low"], "hours_max": g["high"], "confidence": g["confidence"]})
					}
				}
			}
		}
	}
	return object{"sessions": sessions, "sequence": sequence, "gaps": gaps}
}
