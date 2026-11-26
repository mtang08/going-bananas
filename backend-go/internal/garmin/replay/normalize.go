package replay

import (
	"encoding/json"
	"errors"
	"math"
	"strconv"
	"strings"
	"time"
)

type Normalized struct {
	ProviderID string
	Fields     map[string]any
}

func stringID(v any) (string, bool) {
	switch x := v.(type) {
	case json.Number:
		s := string(x)
		if strings.ContainsAny(s, ".eE") || !json.Valid([]byte(s)) {
			return "", false
		}
		return s, true
	case int:
		return strconv.Itoa(x), true
	case int32:
		return strconv.FormatInt(int64(x), 10), true
	case int64:
		return strconv.FormatInt(x, 10), true
	case uint64:
		return strconv.FormatUint(x, 10), true
	}
	return "", false
}

func numeric(v any) (float64, bool) {
	switch x := v.(type) {
	case json.Number:
		n, err := x.Float64()
		return n, err == nil
	case float64:
		return x, true
	case float32:
		return float64(x), true
	default:
		s, ok := stringID(v)
		if !ok {
			return 0, false
		}
		n, err := strconv.ParseFloat(s, 64)
		return n, err == nil
	}
}

func nonnegative(v any, code string) (float64, error) {
	n, ok := numeric(v)
	if !ok || n < 0 || math.IsNaN(n) || math.IsInf(n, 0) {
		return 0, errors.New(code)
	}
	return n, nil
}

func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case map[string]any:
		return len(x) > 0
	case []any:
		return len(x) > 0
	default:
		n, ok := numeric(v)
		return !ok || n != 0
	}
}

func firstTruthy(x, y any) any {
	if truthy(x) {
		return x
	}
	return y
}

var sports = map[string]string{
	"running": "running", "trail_running": "trail_running", "treadmill_running": "treadmill_running",
	"indoor_running": "treadmill_running", "street_running": "running", "virtual_run": "running",
	"ultra_run": "running", "obstacle_run": "running", "track_running": "running", "run": "running",
	"indoor_rowing": "rowing", "rowing": "rowing", "strength_training": "strength", "strength": "strength",
	"walking": "walking", "walk": "walking", "hiking": "hiking", "hike": "hiking", "cycling": "cycling",
	"indoor_cycling": "cycling", "elliptical": "elliptical", "swimming": "swimming", "pool_swimming": "swimming",
	"open_water_swimming": "swimming",
}

func utcISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond() != 0 {
		return t.Format("2006-01-02T15:04:05.000000+00:00")
	}
	return t.Format("2006-01-02T15:04:05+00:00")
}

func activityTime(record map[string]any) (time.Time, string, string, error) {
	for _, key := range []string{"startTimeGMT", "startTimeGmt", "start_at"} {
		value, ok := record[key].(string)
		if !ok || value == "" {
			continue
		}
		start, offset, ok := parseISO(value)
		if !ok {
			return time.Time{}, "", "", errors.New("invalid_start_time")
		}
		assumption := "source_offset"
		if !offset {
			if key == "start_at" {
				return time.Time{}, "", "", errors.New("ambiguous_start_time")
			}
			assumption = "garmin_GMT_field"
		}
		return start.UTC().Truncate(time.Microsecond), value, assumption, nil
	}
	if record["startTimeLocal"] != nil {
		return time.Time{}, "", "", errors.New("ambiguous_start_time")
	}
	return time.Time{}, "", "", errors.New("missing_start_time")
}

// Garmin supplies ISO local GMT or explicitly offset timestamps. Python accepts
// the basic and extended forms, and a space as well as T between date and time.
func parseISO(value string) (time.Time, bool, bool) {
	for _, dateLayout := range []string{"2006-01-02", "20060102"} {
		if len(value) < len(dateLayout) {
			continue
		}
		date, err := time.Parse(dateLayout, value[:len(dateLayout)])
		if err != nil {
			continue
		}
		if len(value) == len(dateLayout) {
			return date, false, true
		}
		clock := []rune(value[len(dateLayout):])
		if len(clock) < 2 {
			continue
		}
		clockText := string(clock[1:])
		for _, zone := range []string{"Z07:00", "Z0700", "Z07:00:00", "Z07", ""} {
			for _, layout := range []string{"15:04:05", "150405", "15:04", "1504", "15"} {
				t, err := time.Parse("2006-01-02T"+layout+zone, date.Format(time.DateOnly)+"T"+clockText)
				if err == nil {
					return t, zone != "", true
				}
			}
		}
	}
	return time.Time{}, false, false
}

func Normalize(record map[string]any, zone *time.Location) (Normalized, error) {
	if record == nil {
		return Normalized{}, errors.New("invalid_record_shape")
	}
	if zone == nil {
		return Normalized{}, errors.New("invalid_timezone")
	}
	start, original, assumption, err := activityTime(record)
	if err != nil {
		return Normalized{}, err
	}
	raw := firstTruthy(record["activityType"], record["activityTypeDTO"])
	if fields, ok := raw.(map[string]any); ok {
		raw = firstTruthy(fields["typeKey"], fields["sportTypeKey"])
	}
	if raw == nil {
		raw = record["sport"]
	}
	subtype, ok := raw.(string)
	if !ok {
		return Normalized{}, errors.New("missing_sport")
	}
	subtype = strings.ToLower(strings.TrimSpace(subtype))
	sport, ok := sports[subtype]
	if !ok {
		sport = "other"
	}
	id := firstTruthy(record["activityId"], record["id"])
	providerID := ""
	if id != nil {
		providerID, ok = id.(string)
		if !ok {
			providerID, ok = stringID(id)
		}
		if !ok || providerID == "" {
			return Normalized{}, errors.New("invalid_activity_id")
		}
	}
	data, prefix := record, ""
	if summary, ok := record["summaryDTO"].(map[string]any); ok {
		data, prefix = summary, "summaryDTO."
	}
	paths := map[string]string{}
	fields := map[string]any{"start_at": utcISO(start), "original_start": original, "source_timezone": assumption,
		"local_date": start.In(zone).Format(time.DateOnly), "sport": sport, "subtype": subtype,
		"source_workout_label": nil, "field_paths": paths}
	for _, metric := range []struct{ source, field, path, code string }{
		{"distance", "distance_m", "distance_m", "invalid_distance"},
		{"elapsedDuration", "elapsed_s", "elapsed_s", "invalid_elapsed_duration"},
		{"movingDuration", "moving_s", "moving_s", "invalid_moving_duration"},
		{"averageHR", "avg_hr_bpm", "average_hr", "invalid_average_hr"},
		{"averageRunningCadenceInStepsPerMinute", "cadence_spm", "average_cadence", "invalid_average_cadence"},
	} {
		fields[metric.field] = nil
		if v := data[metric.source]; v != nil {
			n, err := nonnegative(v, metric.code)
			if err != nil {
				return Normalized{}, err
			}
			fields[metric.field] = n
			paths[metric.path] = prefix + metric.source
		}
	}
	return Normalized{ProviderID: providerID, Fields: fields}, nil
}
