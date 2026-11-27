package travelhttp

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/mtang08/going-bananas/backend-go/internal/pydantic"
	"github.com/mtang08/going-bananas/backend-go/internal/travel"
)

type editRequest struct {
	trip     travel.TripEdit
	category *string
}
type orderedObject struct {
	keys   []string
	fields map[string]json.RawMessage
}

func readObject(raw json.RawMessage) orderedObject {
	d := json.NewDecoder(bytes.NewReader(raw))
	_, _ = d.Token()
	o := orderedObject{fields: map[string]json.RawMessage{}}
	for d.More() {
		key, _ := d.Token()
		k := key.(string)
		if _, ok := o.fields[k]; !ok {
			o.keys = append(o.keys, k)
		}
		var val json.RawMessage
		_ = d.Decode(&val)
		o.fields[k] = val
	}
	return o
}

var integerText = regexp.MustCompile(`^[+-]?[0-9](_?[0-9])*(\.0+)?$`)

func versionValue(v any) (int, string) {
	var s string
	switch n := v.(type) {
	case json.Number:
		s = n.String()
	case string:
		s = strings.TrimSpace(n)
		if !integerText.MatchString(s) {
			return 0, "Input should be a valid integer, unable to parse string as an integer"
		}
		s = strings.ReplaceAll(s, "_", "")
	case bool:
		if n {
			return 1, ""
		}
		s = "0"
	default:
		return 0, "Input should be a valid integer"
	}
	if n, err := strconv.Atoi(s); err == nil {
		if n < 1 {
			return 0, "Input should be greater than or equal to 1"
		}
		return n, ""
	}
	n, _ := strconv.ParseFloat(s, 64)
	if n != math.Trunc(n) {
		return 0, "Input should be a valid integer, got a number with a fractional part"
	}
	if n < 1 {
		return 0, "Input should be greater than or equal to 1"
	}
	if n >= math.MaxInt {
		return math.MaxInt, ""
	}
	return int(n), ""
}

func inputBool(v any) (bool, string) {
	switch x := v.(type) {
	case bool:
		return x, ""
	case string:
		switch strings.ToLower(x) {
		case "1", "on", "t", "true", "y", "yes":
			return true, ""
		case "0", "off", "f", "false", "n", "no":
			return false, ""
		}
	case json.Number:
		n, _ := x.Float64()
		if n == 0 || n == 1 {
			return n == 1, ""
		}
	default:
		return false, "Input should be a valid boolean"
	}
	return false, "Input should be a valid boolean, unable to interpret input"
}

func decodeValue(raw json.RawMessage) any {
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	var v any
	_ = d.Decode(&v)
	return v
}

func readDays(raw json.RawMessage, fields *[]Field) *[]travel.Availability {
	const key = "body.day_availability"
	if raw[0] != '[' {
		*fields = append(*fields, Field{key, "Input should be a valid list"})
		return nil
	}
	var entries []json.RawMessage
	_ = json.Unmarshal(raw, &entries)
	days := make([]travel.Availability, 0, len(entries))
	for i, entry := range entries {
		prefix := fmt.Sprintf("%s.%d", key, i)
		if entry[0] != '{' {
			*fields = append(*fields, Field{prefix, "Input should be a valid dictionary or object to extract fields from"})
			continue
		}
		o := readObject(entry)
		var day travel.Availability
		for _, name := range []string{"date", "availability"} {
			value, ok := o.fields[name]
			msg := ""
			if !ok {
				msg = "Field required"
			} else if name == "date" {
				day.Date, msg = pydantic.Date(decodeValue(value))
			} else {
				var valid bool
				day.Availability, valid = decodeValue(value).(string)
				if !valid {
					msg = "Input should be a valid string"
				} else if !slices.Contains([]string{"normal", "reduced", "unavailable"}, day.Availability) {
					msg = "Value error, Unknown availability"
				}
			}
			if msg != "" {
				*fields = append(*fields, Field{prefix + "." + name, msg})
			}
		}
		for _, k := range o.keys {
			if k != "date" && k != "availability" {
				*fields = append(*fields, Field{prefix + "." + k, "Extra inputs are not permitted"})
			}
		}
		days = append(days, day)
	}
	return &days
}

var tripEnums = map[string][]string{
	"running_access": {"normal", "limited", "none"},
	"gym_access":     {"full", "limited", "none"},
	"category":       {"flight", "lodging", "ground_travel", "reservation", "out_of_office", "appointment", "work", "social", "other"},
	"status":         {"confirmed", "dismissed", "pending"},
}
var enumErrors = map[string]string{"running_access": "Unknown running access", "gym_access": "Unknown gym access", "category": "Unknown category", "status": "Status must be confirmed, dismissed, or pending"}

func (req *editRequest) field(name string, raw json.RawMessage, manual bool, fields *[]Field) string {
	e := &req.trip
	v := decodeValue(raw)
	switch name {
	case "expected_version":
		var msg string
		e.ExpectedVersion, msg = versionValue(v)
		return msg
	case "accept_detected":
		var msg string
		e.AcceptDetected, msg = inputBool(v)
		return msg
	case "day_availability":
		e.Days.Set = true
		if v != nil || manual {
			e.Days.Value = readDays(raw, fields)
		}
		return ""
	}

	dst := map[string]*travel.Optional[string]{"start_date": &e.Start, "end_date": &e.End, "destination_label": &e.Label, "destination_tz": &e.Zone, "gym_access": &e.Gym, "running_access": &e.Running, "status": &e.Status}
	target := dst[name]
	if target != nil {
		target.Set = true
	}
	required := manual && (name == "start_date" || name == "end_date" || name == "destination_tz")
	if v == nil && !required {
		return ""
	}
	var val, msg string
	if name == "start_date" || name == "end_date" {
		val, msg = pydantic.Date(v)
		if msg != "" {
			return msg
		}
	} else {
		var ok bool
		val, ok = v.(string)
		if !ok {
			return "Input should be a valid string"
		}
	}
	switch name {
	case "destination_tz":
		if _, err := time.LoadLocation(val); err != nil || val == "" || val == "Local" {
			return "Value error, Unknown timezone"
		}
	case "destination_label":
		if utf8.RuneCountInString(val) > 120 {
			return "String should have at most 120 characters"
		}
	default:
		if opts := tripEnums[name]; opts != nil && !slices.Contains(opts, val) {
			return "Value error, " + enumErrors[name]
		}
	}
	if target != nil {
		target.Value = &val
	} else {
		req.category = &val
	}
	return ""
}

func readEdit(body io.Reader, operation string) (editRequest, []Field) {
	var req editRequest
	b, err := io.ReadAll(body)
	if err != nil || len(b) == 0 || string(bytes.TrimSpace(b)) == "null" {
		return req, []Field{{"body", "Field required"}}
	}
	var raw json.RawMessage
	if err := json.Unmarshal(b, &raw); err != nil {
		pos := len(b)
		var syntax *json.SyntaxError
		if errors.As(err, &syntax) && syntax.Offset > 0 && syntax.Error() != "unexpected end of JSON input" {
			pos = int(syntax.Offset) - 1
		}
		return req, []Field{{fmt.Sprintf("body.%d", utf8.RuneCount(b[:pos])), "JSON decode error"}}
	}
	if raw[0] != '{' {
		return req, []Field{{"body", "Input should be a valid dictionary or object to extract fields from"}}
	}
	o := readObject(raw)
	order := []string{"start_date", "end_date", "destination_tz", "destination_label", "running_access", "gym_access", "day_availability"}
	required := order[:3]
	switch operation {
	case "patchTrip":
		order = []string{"expected_version", "status", "accept_detected", "start_date", "end_date", "destination_label", "destination_tz", "running_access", "gym_access", "day_availability"}
		required = order[:1]
	case "patchEvent":
		order = []string{"expected_version", "category"}
		required = order
	}
	var fields []Field
	for _, k := range order {
		v, exists := o.fields[k]
		msg := ""
		if exists {
			msg = req.field(k, v, operation == "createTrip", &fields)
		} else if slices.Contains(required, k) {
			msg = "Field required"
		}
		if msg != "" {
			fields = append(fields, Field{"body." + k, msg})
		}
	}
	for _, k := range o.keys {
		if !slices.Contains(order, k) {
			fields = append(fields, Field{"body." + k, "Extra inputs are not permitted"})
		}
	}
	return req, fields
}
