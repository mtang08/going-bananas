// Package recording provides the shared FIT timer and workout-step semantics used by activity metrics.
package recording

import (
	"cmp"
	"errors"
	"slices"
	"strings"
)

type Span [2]float64
type Piece struct {
	Index   int
	Seconds float64
}

func Union(input []Span) ([]Span, error) {
	spans := slices.Clone(input)
	slices.SortFunc(spans, func(a, b Span) int { return cmp.Or(cmp.Compare(a[0], b[0]), cmp.Compare(a[1], b[1])) })
	var out []Span
	for _, s := range spans {
		if s[1] < s[0] {
			return nil, errors.New("invalid_timer")
		}
		if s[1] == s[0] {
			continue
		}
		if n := len(out); n != 0 && s[0] <= out[n-1][1] {
			out[n-1][1] = max(out[n-1][1], s[1])
		} else {
			out = append(out, s)
		}
	}
	return out, nil
}
func Integrate(times []int, spans []Span) ([]Piece, error) {
	for i, t := range times {
		if t < 0 || (i > 0 && times[i-1] >= t) {
			return nil, errors.New("invalid_stream_order")
		}
	}
	var out []Piece
	for _, s := range spans {
		if s[0] < 0 {
			return nil, errors.New("invalid_timer")
		}
		cur := s[0]
		for i, t := range times[:max(0, len(times)-1)] {
			left, right := float64(t), float64(times[i+1])
			if right <= cur {
				continue
			}
			if left >= s[1] {
				break
			}
			if cur < left {
				out = append(out, Piece{-1, left - cur})
				cur = left
			}
			end := min(right, s[1])
			if end > cur {
				idx := i
				if right-left > 10 {
					idx = -1
				}
				out = append(out, Piece{idx, end - cur})
				cur = end
			}
		}
		if cur < s[1] {
			out = append(out, Piece{-1, s[1] - cur})
		}
	}
	return out, nil
}

type FitStep struct {
	Index                   int
	Duration, Intensity     string
	Value                   *float64
	Target                  *string
	Low, High               *float64
	RepeatFrom, RepeatCount *int
}

func Expand(steps []FitStep) ([]FitStep, error) {
	steps = slices.Clone(steps)
	slices.SortFunc(steps, func(a, b FitStep) int { return cmp.Compare(a.Index, b.Index) })
	starts := map[int]int{}
	var expanded []FitStep
	for i, s := range steps {
		if i > 0 && s.Index == steps[i-1].Index {
			return nil, errors.New("MALFORMED_REPEAT")
		}
		if strings.HasPrefix(s.Duration, "repeat") {
			if s.Duration != "repeat_until_steps_cmplt" {
				return nil, errors.New("UNSUPPORTED_REPEAT")
			}
			if s.RepeatFrom == nil || s.RepeatCount == nil || *s.RepeatCount < 2 {
				return nil, errors.New("MALFORMED_REPEAT")
			}
			start, ok := starts[*s.RepeatFrom]
			if !ok {
				return nil, errors.New("MALFORMED_REPEAT")
			}
			repeat := slices.Clone(expanded[start:])
			if *s.RepeatCount-1 > (100-len(expanded))/len(repeat) {
				return nil, errors.New("UNSUPPORTED_REPEAT")
			}
			for range *s.RepeatCount - 1 {
				expanded = append(expanded, repeat...)
			}
		} else {
			starts[s.Index] = len(expanded)
			expanded = append(expanded, s)
			if len(expanded) > 100 {
				return nil, errors.New("UNSUPPORTED_REPEAT")
			}
		}
	}
	return expanded, nil
}
