package fit

import (
	"cmp"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"maps"
	"math"
	"slices"
	"strconv"
	"strings"
	"time"
)

const fitEpoch = 631065600 // Unix seconds at 1989-12-31T00:00:00Z.

func number(value any) *float64 {
	n, ok := value.(float64)
	if !ok || math.IsNaN(n) || math.IsInf(n, 0) {
		return nil
	}
	return &n
}

func integer(value any) *int {
	n := number(value)
	if n == nil || float64(int(*n)) != *n {
		return nil
	}
	i := int(*n)
	return &i
}

func textValue(value any) *string {
	s, ok := value.(string)
	if !ok {
		return nil
	}
	return &s
}

func enumValue(value any) *EnumValue {
	if s, ok := value.(string); ok {
		return &EnumValue{Name: s}
	}
	if code := integer(value); code != nil {
		return &EnumValue{UnknownCode: code}
	}
	return nil
}

func enumText(value any, fallback string) string {
	if s, ok := value.(string); ok {
		return s
	}
	if n := integer(value); n != nil {
		return strconv.Itoa(*n)
	}
	return fallback
}

func instant(value any) *time.Time {
	n := number(value)
	if n == nil {
		return nil
	}
	seconds, fraction := math.Modf(*n)
	t := time.Unix(int64(seconds)+fitEpoch, int64(math.RoundToEven(fraction*1e6))*1000).UTC()
	return &t
}

func channel(row map[string]any, enhanced, fallback string) *float64 {
	if v := row[enhanced]; v != nil {
		return number(v)
	}
	return number(row[fallback])
}

func sessionFrom(rows []map[string]any) (DecodedSession, error) {
	var s DecodedSession
	if len(rows) == 0 {
		return s, decodeError("missing_session")
	}
	if len(rows) > 1 {
		return s, decodeError("ambiguous_session")
	}
	row := rows[0]
	start := instant(row["start_time"])
	if start == nil {
		return s, decodeError("missing_start")
	}
	s.StartAt = *start
	s.Sport = enumText(row["sport"], "unknown")
	sub, _ := row["sub_sport"].(string)
	switch sub {
	case "running", "trail_running", "treadmill_running":
		s.Sport = sub
	case "trail":
		if s.Sport == "running" {
			s.Sport = "trail_running"
		}
	case "treadmill", "indoor_running":
		if s.Sport == "running" {
			s.Sport = "treadmill_running"
		}
	}
	s.ElapsedS = number(row["total_elapsed_time"])
	s.TimerS = number(row["total_timer_time"])
	s.DistanceM = number(row["total_distance"])
	if rpe := number(row["workout_rpe"]); rpe != nil && *rpe >= 0 && *rpe <= 100 {
		*rpe /= 10
		s.WorkoutRPE = rpe
	}
	if feel := integer(row["workout_feel"]); feel != nil && *feel >= 0 && *feel <= 100 {
		s.WorkoutFeel = feel
	}
	return s, nil
}

func lapsFrom(rows []map[string]any, flags map[string]bool) []DecodedLap {
	laps := make([]DecodedLap, 0, len(rows))
	for _, row := range rows {
		start, end := instant(row["start_time"]), instant(row["timestamp"])
		elapsed := number(row["total_elapsed_time"])
		if start == nil {
			if end == nil || elapsed == nil {
				flags["LAP_START_MISSING"] = true
				continue
			}
			t := end.Add(-time.Duration(math.RoundToEven(*elapsed*1e6)) * time.Microsecond)
			start = &t
		}
		lap := DecodedLap{
			LapIndex:     len(laps),
			StartAt:      *start,
			EndAt:        end,
			ElapsedS:     elapsed,
			TimerS:       number(row["total_timer_time"]),
			DistanceM:    number(row["total_distance"]),
			AvgSpeedMPS:  channel(row, "enhanced_avg_speed", "avg_speed"),
			AvgHRBPM:     number(row["avg_heart_rate"]),
			MaxHRBPM:     number(row["max_heart_rate"]),
			LapTrigger:   enumValue(row["lap_trigger"]),
			WktStepIndex: integer(row["wkt_step_index"]),
		}
		if intensity, ok := row["intensity"].(string); ok {
			switch intensity {
			case "active", "rest", "warmup", "cooldown", "recovery", "interval", "other":
				lap.Intensity = &intensity
			}
		}
		laps = append(laps, lap)
	}
	return laps
}

func stepsFrom(rows []map[string]any) ([]DecodedStep, error) {
	steps := make([]DecodedStep, 0, len(rows))
	for _, row := range rows {
		index := integer(row["message_index"])
		if index == nil {
			return nil, decodeError("decode_failed")
		}
		step := DecodedStep{
			MessageIndex:  *index,
			StepName:      textValue(row["wkt_step_name"]),
			Intensity:     enumValue(row["intensity"]),
			DurationType:  enumText(row["duration_type"], ""),
			DurationValue: number(row["duration_value"]),
			TargetType:    enumValue(row["target_type"]),
			TargetLow:     number(row["custom_target_value_low"]),
			TargetHigh:    number(row["custom_target_value_high"]),
		}
		if strings.HasPrefix(step.DurationType, "repeat_") {
			step.RepeatFrom = integer(row["duration_value"])
			step.RepeatCount = integer(row["target_value"])
		}
		if d := step.DurationValue; d != nil {
			switch step.DurationType {
			case "time":
				*d /= 1000
			case "distance":
				*d /= 100
			}
		}
		if t := step.TargetType; t != nil {
			step.TargetLow = targetBound(t.Name, step.TargetLow)
			step.TargetHigh = targetBound(t.Name, step.TargetHigh)
		}
		steps = append(steps, step)
	}
	slices.SortStableFunc(steps, func(a, b DecodedStep) int { return cmp.Compare(a.MessageIndex, b.MessageIndex) })
	return steps, nil
}

func targetBound(kind string, n *float64) *float64 {
	if n == nil {
		return nil
	}
	switch kind {
	case "open":
		return nil
	case "speed":
		*n /= 1000
	case "heart_rate":
		if *n <= 100 {
			return nil
		}
		*n -= 100
	}
	return n
}

func (p *projectedMessages) normalize(payload []byte) (*DecodedFit, error) {
	messages := p.rows
	if err := mergeHeartRates(messages, p.fields["record_mesgs"]); err != nil {
		return nil, err
	}
	session, err := sessionFrom(messages["session_mesgs"])
	if err != nil {
		return nil, err
	}
	flags := make(map[string]bool)
	laps := lapsFrom(messages["lap_mesgs"], flags)
	steps, err := stepsFrom(messages["workout_step_mesgs"])
	if err != nil {
		return nil, err
	}
	stream, err := streamFrom(messages["record_mesgs"], messages["event_mesgs"], session, flags)
	if err != nil {
		return nil, err
	}
	hash := sha256.Sum256(payload)
	// Device info takes precedence over file ID even when it appeared earlier on the wire.
	maps.Copy(p.fileID, p.device)
	return &DecodedFit{
		FITSHA256:        hex.EncodeToString(hash[:]),
		ProfileVersion:   strconv.Itoa(int(binary.LittleEndian.Uint16(payload[2:4]))),
		SDKVersion:       SDKVersion,
		Session:          session,
		Laps:             laps,
		Steps:            steps,
		Stream:           stream,
		MessageInventory: p.inventory,
		FieldNames:       p.fieldNames(),
		Device:           p.fileID,
	}, nil
}
