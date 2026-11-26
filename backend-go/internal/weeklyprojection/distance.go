package weeklyprojection

import (
	"encoding/json"
	"math"

	"github.com/mtang08/going-bananas/backend-go/internal/calendarstructure"
)

func positive(x *float64) bool { return x != nil && *x > 0 && !math.IsInf(*x, 0) }

func PlannedDuration(duration *float64, structure json.RawMessage) *float64 {
	if positive(duration) {
		return duration
	}
	steps, ok := calendarstructure.Expand(structure)
	if !ok {
		return nil
	}
	total := 0.0
	for _, step := range steps {
		if step.DurationType != "time" {
			return nil
		}
		total += step.DurationValue
	}
	return &total
}

// PlannedDistance reports metres and whether any speed assumption was used.
func PlannedDistance(distance, duration *float64, structure json.RawMessage, pace *float64) (*float64, bool) {
	if positive(distance) {
		return distance, false
	}
	if len(structure) == 0 || string(structure) == "null" {
		if !positive(duration) || pace == nil {
			return nil, false
		}
		m := *duration * *pace
		return &m, true
	}
	steps, ok := calendarstructure.Expand(structure)
	if !ok {
		return nil, false
	}
	total, elapsed := 0.0, 0.0
	allTime, estimated := true, false
	for _, step := range steps {
		if step.DurationType == "distance" {
			total += step.DurationValue
			allTime = false
			continue
		}
		speed := pace
		if t := step.Target; t != nil && t.Modality == "speed" {
			mid := (*t.Low + *t.High) / 2
			speed = &mid
		}
		if speed == nil {
			return nil, false
		}
		elapsed += step.DurationValue
		total += step.DurationValue * *speed
		estimated = true
	}
	if allTime && positive(duration) && *duration > elapsed {
		if pace == nil {
			return nil, false
		}
		total += (*duration - elapsed) * *pace
		estimated = true
	}
	return &total, estimated
}
