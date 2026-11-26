package fit

import (
	"cmp"
	"maps"
	"math"
	"slices"
	"time"
)

func offset(value any, start time.Time) (int, bool) {
	t := instant(value)
	if t == nil || t.Before(start) {
		return 0, false
	}
	d := t.Sub(start)
	return int(d / time.Second), d%time.Second == 0
}

type sample struct {
	hr       *int
	speed    *float64
	distance *float64
	altitude *float64
	cadence  *float64
}

// Every record at an offset must agree on the channel, including missing values.
// Once two values disagree the channel stays nil for all later duplicates.
func mergeChannel[T comparable](prior **T, next *T, flags map[string]bool) {
	if *prior == next || (*prior != nil && next != nil && **prior == *next) {
		return
	}
	*prior = nil
	flags["DUPLICATE_RECORD_CONFLICT"] = true
}

func streamFrom(records, events []map[string]any, session DecodedSession, flags map[string]bool) (DecodedStream, error) {
	byTime := make(map[int]*sample, len(records))
	for _, row := range records {
		second, ok := offset(row["timestamp"], session.StartAt)
		if !ok {
			return DecodedStream{}, decodeError("invalid_stream_time")
		}
		s := sample{
			hr: integer(row["heart_rate"]), speed: channel(row, "enhanced_speed", "speed"), distance: number(row["distance"]),
			altitude: channel(row, "enhanced_altitude", "altitude"), cadence: number(row["cadence"]),
		}
		if prior := byTime[second]; prior != nil {
			mergeChannel(&prior.hr, s.hr, flags)
			mergeChannel(&prior.speed, s.speed, flags)
			mergeChannel(&prior.distance, s.distance, flags)
			mergeChannel(&prior.altitude, s.altitude, flags)
			mergeChannel(&prior.cadence, s.cadence, flags)
		} else {
			byTime[second] = &s
		}
	}
	n := len(byTime)
	stream := DecodedStream{
		TS: make([]int, 0, n), SampleCount: n,
		HRBPM: make([]*int, n), SpeedMPS: make([]*float64, n), DistanceM: make([]*float64, n),
		AltitudeM: make([]*float64, n), Cadence: make([]*float64, n),
		TimerOn:      timerIntervals(events, session, flags),
		QualityFlags: slices.AppendSeq([]string{}, maps.Keys(flags)),
	}
	stream.TS = slices.AppendSeq(stream.TS, maps.Keys(byTime))
	slices.Sort(stream.TS)
	slices.Sort(stream.QualityFlags)
	for i, second := range stream.TS {
		s := byTime[second]
		stream.HRBPM[i], stream.SpeedMPS[i], stream.DistanceM[i] = s.hr, s.speed, s.distance
		stream.AltitudeM[i], stream.Cadence[i] = s.altitude, s.cadence
		if i > 0 {
			stream.MaxGapS = max(stream.MaxGapS, second-stream.TS[i-1])
		}
	}
	return stream, nil
}

// Stops sort before starts at the same instant.
const (
	timerStop = iota
	timerStart
)

type timerEvent struct {
	second int
	action int
}

func timerIntervals(rows []map[string]any, session DecodedSession, flags map[string]bool) [][2]int {
	ambiguous := func() [][2]int {
		flags["TIMER_EVENTS_AMBIGUOUS"] = true
		return [][2]int{}
	}
	var events []timerEvent
	for _, row := range rows {
		event, _ := row["event"].(string)
		kind, _ := row["event_type"].(string)
		if event != "timer" || kind == "marker" {
			continue
		}
		second, ok := offset(row["timestamp"], session.StartAt)
		if !ok {
			return ambiguous()
		}
		var action int
		switch kind {
		case "stop", "stop_all", "stop_disable", "stop_disable_all":
			action = timerStop
		case "start":
			action = timerStart
		default:
			return ambiguous()
		}
		events = append(events, timerEvent{second, action})
	}
	if len(events) == 0 {
		flags["TIMER_EVENTS_MISSING"] = true
		return [][2]int{}
	}
	slices.SortStableFunc(events, func(a, b timerEvent) int {
		return cmp.Or(cmp.Compare(a.second, b.second), cmp.Compare(a.action, b.action))
	})
	segments := [][2]int{}
	start := -1
	for _, event := range events {
		if event.action == timerStart {
			if start >= 0 {
				return ambiguous()
			}
			start = event.second
			continue
		}
		if start < 0 {
			return ambiguous()
		}
		if event.second > start {
			segments = appendInterval(segments, start, event.second)
		}
		start = -1
	}
	if start >= 0 {
		elapsed := session.ElapsedS
		if elapsed == nil || math.Trunc(*elapsed) != *elapsed || *elapsed < float64(start) {
			return ambiguous()
		}
		segments = appendInterval(segments, start, int(*elapsed))
		flags["TIMER_END_INFERRED"] = true
	}
	if timer := session.TimerS; timer != nil {
		total := 0
		for _, segment := range segments {
			total += segment[1] - segment[0]
		}
		if math.Abs(float64(total)-*timer) > math.Max(1, *timer*0.01) {
			flags["TIMER_MISMATCH"] = true
		}
	}
	return segments
}

func appendInterval(segments [][2]int, start, end int) [][2]int {
	if i := len(segments) - 1; i >= 0 && segments[i][1] == start {
		segments[i][1] = end
		return segments
	}
	return append(segments, [2]int{start, end})
}
