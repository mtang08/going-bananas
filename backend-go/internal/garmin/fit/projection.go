package fit

import (
	"maps"
	"regexp"
	"slices"
)

// The decoder broadcasts every FIT message. Collect metadata as it arrives so
// only fields needed for normalization survive the callback.
type projectedMessages struct {
	inventory map[string]int
	fields    map[string]map[string]bool
	rows      map[string][]map[string]any
	device    map[string]any
	fileID    map[string]any
}

func newProjection() projectedMessages {
	return projectedMessages{
		inventory: make(map[string]int), fields: make(map[string]map[string]bool),
		rows: make(map[string][]map[string]any), device: make(map[string]any), fileID: make(map[string]any),
	}
}

var observationFields = map[string][]string{
	"session_mesgs": {"start_time", "sport", "sub_sport", "workout_rpe", "workout_feel",
		"total_elapsed_time", "total_timer_time", "total_distance"},
	"lap_mesgs": {"start_time", "timestamp", "total_timer_time", "total_elapsed_time", "total_distance",
		"avg_speed", "enhanced_avg_speed", "avg_heart_rate", "max_heart_rate", "intensity", "lap_trigger", "wkt_step_index"},
	"workout_step_mesgs": {"message_index", "duration_type", "wkt_step_name", "intensity", "duration_value",
		"target_type", "custom_target_value_low", "custom_target_value_high", "target_value"},
	"record_mesgs": {"timestamp", "heart_rate", "enhanced_speed", "speed", "distance", "enhanced_altitude", "altitude", "cadence"},
	"event_mesgs":  {"event", "event_type", "timestamp"},
	"hr_mesgs":     {"timestamp", "fractional_timestamp", "event_timestamp", "filtered_bpm"},
}

func (p *projectedMessages) define(name string) {
	if p.fields[name] != nil {
		return
	}
	p.fields[name] = make(map[string]bool)
	p.inventory[name] = 0
	if _, ok := observationFields[name]; ok {
		p.rows[name] = nil
	}
}

func (p *projectedMessages) add(name string, row map[string]any) {
	p.inventory[name]++
	for key := range row {
		p.fields[name][key] = true
	}
	switch name {
	case "device_info_mesgs":
		keepDevice(p.device, row)
	case "file_id_mesgs":
		keepDevice(p.fileID, row)
	default:
		if keys, ok := observationFields[name]; ok {
			values := make(map[string]any, min(len(keys), len(row)))
			for _, key := range keys {
				if v := row[key]; v != nil {
					values[key] = v
				}
			}
			p.rows[name] = append(p.rows[name], values)
		}
	}
}

func keepDevice(device, row map[string]any) {
	for _, key := range []string{"manufacturer", "product", "software_version"} {
		if v := row[key]; v != nil {
			device[key] = v
		}
	}
}

var privateField = regexp.MustCompile("(?i)position|latitude|longitude|serial|token|secret|password|credential")

func (p *projectedMessages) fieldNames() map[string][]string {
	names := make(map[string][]string, len(p.fields))
	for name, fields := range p.fields {
		keys := slices.AppendSeq([]string{}, maps.Keys(fields))
		keys = slices.DeleteFunc(keys, privateField.MatchString)
		slices.Sort(keys)
		names[name] = keys
	}
	return names
}
