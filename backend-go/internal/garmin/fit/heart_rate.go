package fit

import "math"

// FIT HR messages can supply a finer-grained heart-rate series alongside records.
// Match the reference decoder's record windows and quarter-second carry-forward.
type heartBeat struct {
	second float64
	bpm    float64
}

func mergeHeartRates(messages map[string][]map[string]any, recordFields map[string]bool) error {
	rows, hasHR := messages["hr_mesgs"]
	if !hasHR {
		return nil
	}
	records, hasRecords := messages["record_mesgs"]
	if !hasRecords {
		return decodeError("decode_failed")
	}
	if len(rows) == 0 || len(records) == 0 {
		return nil
	}
	beats, err := expandHeartRates(rows)
	if err != nil {
		return err
	}
	index := 0
	var windowStart float64
	for i, record := range records {
		end := number(record["timestamp"])
		if end == nil {
			return decodeError("decode_failed")
		}
		if i == 0 || windowStart == *end {
			windowStart = *end - 1
			index = max(0, index-1)
		}
		var sum float64
		count := 0
		for index < len(beats) {
			b := beats[index]
			if b.second > *end {
				// The SDK finalizes a window when it encounters a later beat.
				if count > 0 {
					recordFields["heart_rate"] = true
					record["heart_rate"] = math.Trunc(sum/float64(count) + 0.5)
				}
				windowStart = *end
				break
			}
			if b.second > windowStart {
				sum += b.bpm
				count++
			}
			index++
		}
	}
	return nil
}

func series(value any) []any {
	if values, ok := value.([]any); ok {
		return values
	}
	return []any{value}
}

func expandHeartRates(rows []map[string]any) ([]heartBeat, error) {
	var beats []heartBeat
	var anchor *float64
	var anchorEvent float64
	for _, row := range rows {
		times, bpms := series(row["event_timestamp"]), series(row["filtered_bpm"])
		if len(times) != len(bpms) {
			return nil, decodeError("decode_failed")
		}
		if at := number(row["timestamp"]); at != nil {
			fraction := number(row["fractional_timestamp"])
			if fraction == nil || len(times) != 1 || number(times[0]) == nil {
				return nil, decodeError("decode_failed")
			}
			*at += *fraction
			anchor, anchorEvent = at, *number(times[0])
		}
		if anchor == nil {
			return nil, decodeError("decode_failed")
		}
		for i, v := range times {
			t, bpm := number(v), number(bpms[i])
			if t == nil || bpm == nil {
				return nil, decodeError("decode_failed")
			}
			delta := *t - anchorEvent
			if delta < 0 {
				if delta >= -0x400000 {
					return nil, decodeError("decode_failed")
				}
				delta += 0x400000
			}
			second := *anchor + delta
			if len(beats) != 0 {
				last := beats[len(beats)-1]
				gap := math.Abs(second - last.second)
				for step := 1; step <= 20 && float64(step)*0.25 < gap; step++ {
					beats = append(beats, heartBeat{last.second + float64(step)*0.25, last.bpm})
				}
			}
			beats = append(beats, heartBeat{second, *bpm})
		}
	}
	return beats, nil
}
