package fit

import (
	"math"
	"reflect"
	"strconv"
	"strings"

	"github.com/muktihari/fit/profile"
	"github.com/muktihari/fit/profile/factory"
	"github.com/muktihari/fit/profile/typedef"
	"github.com/muktihari/fit/proto"
)

// Keep main-field components but disable the decoder's automatic selection of
// subfield-specific components, matching expand_sub_fields=False.
func (r *messageRows) CreateField(m typedef.MesgNum, num byte) proto.Field {
	f := factory.CreateField(m, num)
	packedRecord := m == typedef.MesgNumRecord && f.Name == "compressed_speed_distance"
	arrayDistance := r.distanceArray && m == typedef.MesgNumRecord && f.Name == "distance"
	if len(f.SubFields) != 0 || packedRecord || arrayDistance {
		base := *f.FieldBase
		base.SubFields = nil
		if arrayDistance {
			base.Array = true
		}
		if packedRecord {
			base.Components = nil
		}
		f.FieldBase = &base
	}
	return f
}

type messageRows struct {
	projectedMessages
	invalid        bool
	developerIDs   [256]bool
	packedDistance uint64
	distanceArray  bool
}

func messageKey(m typedef.MesgNum) string {
	name := m.String()
	if strings.Contains(name, "(") {
		return strconv.Itoa(int(m))
	}
	return name + "_mesgs"
}

func (r *messageRows) OnMesgDef(def proto.MessageDefinition) {
	// Wire definitions may encode an array even for a nominally scalar distance.
	if def.MesgNum == typedef.MesgNumRecord {
		for _, field := range def.FieldDefinitions {
			if field.Num == 5 && field.Size > 4 {
				r.distanceArray = true
			}
		}
	}
	r.define(messageKey(def.MesgNum))
}

func (r *messageRows) OnMesg(m proto.Message) {
	if m.Header&proto.MesgCompressedHeaderMask != 0 {
		r.invalid = true
		return
	}
	key := messageKey(m.Num)
	row := make(map[string]any, len(m.Fields))
	for _, f := range m.Fields {
		if !f.Value.Valid(f.BaseType) {
			continue
		}
		name := f.Name
		if name == factory.NameUnknown {
			name = strconv.Itoa(int(f.Num))
		}
		if key == "time_in_zone_mesgs" && name == "cadence_zone_high_boundary" {
			name = "cadence_zone_high_bondary"
		}
		if value := fieldValue(f); value != nil {
			row[name] = value
		}
	}
	// The native SDK expands through the destination integer's precision.
	// Preserve the source scale when projecting legacy fields into enhanced ones.
	if m.Num == typedef.MesgNumRecord {
		r.recordComponents(m, row)
	}
	if m.Num == typedef.MesgNumLap || m.Num == typedef.MesgNumSession {
		if speed, ok := row["avg_speed"].(float64); ok {
			row["enhanced_avg_speed"] = speed
		}
	}
	if m.Num == typedef.MesgNumFieldDescription || m.Num == typedef.MesgNumDeveloperDataId {
		index, ok := row["developer_data_index"].(float64)
		if !ok || index >= 256 {
			r.invalid = true
			return
		}
		if m.Num == typedef.MesgNumDeveloperDataId {
			r.developerIDs[uint8(index)] = true
		} else {
			row["key"] = float64(r.inventory[key])
			if r.developerIDs[uint8(index)] && (row["fit_base_type_id"] == nil || row["field_definition_number"] == nil) {
				r.invalid = true
				return
			}
		}
	}
	// Only the presence of developer data enters the normalized inventory.
	for _, field := range m.DeveloperFields {
		if r.developerIDs[field.DeveloperDataIndex] {
			row["developer_fields"] = true
			break
		}
	}
	r.add(key, row)
}

func (r *messageRows) recordComponents(m proto.Message, row map[string]any) {
	if altitude, ok := row["altitude"].(float64); ok {
		row["enhanced_altitude"] = altitude
	}
	if speed, ok := row["speed"].(float64); ok {
		row["enhanced_speed"] = speed
	}
	if distance := m.FieldByNum(5); distance != nil && distance.Value.Valid(distance.BaseType) {
		if distance.Value.Type() == proto.TypeSliceUint32 {
			for _, raw := range distance.Value.SliceUint32() {
				if raw == math.MaxUint32 {
					r.invalid = true
					return
				}
				r.packedDistance = uint64(raw)
			}
		} else {
			r.packedDistance = uint64(distance.Value.Uint32())
		}
	}
	packed := m.FieldByNum(8)
	if packed == nil || !packed.Value.Valid(packed.BaseType) {
		return
	}
	b := packed.Value.SliceUint8()
	if len(b) < 3 {
		return
	}
	rawSpeed := uint16(b[0]) | uint16(b[1]&15)<<8
	rawDistance := uint64(b[1]>>4) | uint64(b[2])<<4
	r.packedDistance += (rawDistance - r.packedDistance) & 0xfff
	speed := float64(rawSpeed) / 100
	row["distance"] = float64(r.packedDistance) / 16
	if _, explicitSpeed := row["speed"]; !explicitSpeed {
		row["enhanced_speed"] = math.Trunc(speed*1000) / 1000
	}
	row["speed"] = speed
}

func fieldValue(f proto.Field) any {
	v := reflect.ValueOf(f.Value.Any())
	if v.Kind() != reflect.Slice {
		return scalar(f, v)
	}
	values := make([]any, v.Len())
	for i := range values {
		item := v.Index(i)
		if proto.Any(item.Interface()).Valid(f.BaseType) {
			values[i] = scalar(f, item)
		}
	}
	if len(values) == 1 {
		return values[0]
	}
	return values
}

func scalar(f proto.Field, v reflect.Value) any {
	switch v.Kind() {
	case reflect.String:
		return v.String()
	case reflect.Bool:
		return v.Bool()
	}
	if !v.CanConvert(reflect.TypeFor[float64]()) {
		return nil
	}
	n := v.Convert(reflect.TypeFor[float64]()).Float()
	if math.IsInf(n, 0) || math.IsNaN(n) {
		return nil
	}
	if name := enumName(f.Type, n); name != "" && !strings.Contains(name, "(") {
		return name
	}
	return n/f.Scale - f.Offset
}

// These are the profile enumerations whose values enter the application contract.
func enumName(t profile.ProfileType, n float64) string {
	switch t {
	case profile.Manufacturer:
		return typedef.Manufacturer(n).String()
	case profile.Sport:
		return typedef.Sport(n).String()
	case profile.SubSport:
		return typedef.SubSport(n).String()
	case profile.Event:
		return typedef.Event(n).String()
	case profile.EventType:
		return typedef.EventType(n).String()
	case profile.LapTrigger:
		return typedef.LapTrigger(n).String()
	case profile.Intensity:
		return typedef.Intensity(n).String()
	case profile.WktStepDuration:
		return typedef.WktStepDuration(n).String()
	case profile.WktStepTarget:
		return typedef.WktStepTarget(n).String()
	case profile.MessageIndex:
		return typedef.MessageIndex(n).String()
	}
	return ""
}
