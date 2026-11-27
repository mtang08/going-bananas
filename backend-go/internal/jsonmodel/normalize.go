// Package jsonmodel validates and normalizes wire documents with ordered model descriptors.
package jsonmodel

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
)

type shape struct {
	AdditionalProperties                     json.RawMessage
	Type, Format, Ref, Pattern               string
	Const                                    string
	Enum                                     []string
	AnyOf                                    []shape
	Items                                    *shape
	Minimum, Maximum, ExclusiveMinimum       *float64
	MinItems, MaxItems, MinLength, MaxLength *int
}
type fieldSchema struct {
	Name    string
	Shape   shape
	Default json.RawMessage
}

type Issue struct {
	Code    string `json:"code"`
	Path    string `json:"path"`
	Message string `json:"message"`
}
type Models struct {
	fields map[string][]fieldSchema
	check  func(string, []byte) string
}

func Load(raw []byte, check func(string, []byte) string) Models {
	var m Models
	if err := json.Unmarshal(raw, &m.fields); err != nil {
		panic(err)
	}
	m.check = check
	return m
}
func (m Models) Parse(name, path string, raw json.RawMessage) (full, authored json.RawMessage, issues []Issue) {
	n := m.normalizeModel(name, path, raw)
	return n.full, n.authored, n.issues
}

type normalized struct {
	full, authored json.RawMessage
	issues         []Issue
}

func invalid(path, msg string) normalized {
	return normalized{issues: []Issue{{"V1.schema", path, msg}}}
}
func scalar(raw json.RawMessage) normalized { return normalized{full: raw, authored: raw} }
func scalarValue(v any) normalized          { b, _ := json.Marshal(v); return scalar(b) }
func loc(path, key string) string {
	if path == "" {
		return key
	}
	return path + "." + key
}

type object struct {
	keys   []string
	fields map[string]json.RawMessage
}

func orderedObject(raw json.RawMessage) (object, bool) {
	o := object{fields: map[string]json.RawMessage{}}
	dec := json.NewDecoder(bytes.NewReader(raw))
	t, err := dec.Token()
	if err != nil || t != json.Delim('{') {
		return o, false
	}
	for dec.More() {
		t, err := dec.Token()
		if err != nil {
			return o, false
		}
		k := t.(string)
		var v json.RawMessage
		if dec.Decode(&v) != nil {
			return o, false
		}
		if _, ok := o.fields[k]; !ok {
			o.keys = append(o.keys, k)
		}
		o.fields[k] = v
	}
	return o, true
}
func objectField(buf *bytes.Buffer, key string, v json.RawMessage) {
	if buf.Len() > 1 {
		buf.WriteByte(',')
	}
	k, _ := json.Marshal(key)
	buf.Write(k)
	buf.WriteByte(':')
	buf.Write(v)
}
func (m Models) normalizeModel(name, path string, raw json.RawMessage) normalized {
	o, ok := orderedObject(raw)
	if !ok {
		return invalid(path, fmt.Sprintf("Input should be a valid dictionary or instance of %s", name))
	}
	known := map[string]bool{}
	var full, partial bytes.Buffer
	full.WriteByte('{')
	partial.WriteByte('{')
	var issues []Issue
	for _, f := range m.fields[name] {
		known[f.Name] = true
		v, present := o.fields[f.Name]
		fieldPath := loc(path, f.Name)
		if !present {
			if f.Default == nil {
				issues = append(issues, invalid(fieldPath, "Field required").issues...)
			} else {
				objectField(&full, f.Name, f.Default)
			}
			continue
		}
		n := m.normalize(f.Shape, fieldPath, v)
		if len(n.issues) > 0 {
			issues = append(issues, n.issues...)
			continue
		}
		objectField(&full, f.Name, n.full)
		objectField(&partial, f.Name, n.authored)
	}
	for _, k := range o.keys {
		if !known[k] {
			issues = append(issues, invalid(loc(path, k), "Extra inputs are not permitted").issues...)
		}
	}
	full.WriteByte('}')
	partial.WriteByte('}')
	if len(issues) > 0 {
		return normalized{issues: issues}
	}
	if m.check != nil {
		if msg := m.check(name, partial.Bytes()); msg != "" {
			return invalid(path, "Value error, "+msg)
		}
	}
	return normalized{full: full.Bytes(), authored: partial.Bytes()}
}

func (m Models) normalize(s shape, path string, raw json.RawMessage) normalized {
	if s.Ref != "" {
		return m.normalizeModel(s.Ref, path, raw)
	}
	if len(s.AnyOf) > 0 {
		if len(s.AnyOf) == 2 && s.AnyOf[1].Type == "null" {
			if string(raw) == "null" {
				return scalar(raw)
			}
			return m.normalize(s.AnyOf[0], path, raw)
		}
		var issues []Issue
		for _, branch := range s.AnyOf {
			n := m.normalize(branch, loc(path, branch.Ref), raw)
			if len(n.issues) == 0 {
				return n
			}
			issues = append(issues, n.issues...)
		}
		return normalized{issues: issues}
	}
	if s.Const != "" || len(s.Enum) > 0 {
		choices := s.Enum
		if s.Const != "" {
			choices = []string{s.Const}
		}
		var v string
		_ = json.Unmarshal(raw, &v)
		quoted := make([]string, len(choices))
		for i, c := range choices {
			if v == c {
				return scalar(raw)
			}
			quoted[i] = "'" + c + "'"
		}
		options := quoted[0]
		if len(quoted) > 1 {
			options = strings.Join(quoted[:len(quoted)-1], ", ") + " or " + quoted[len(quoted)-1]
		}
		return invalid(path, "Input should be "+options)
	}
	switch s.Type {
	case "object":
		o, ok := orderedObject(raw)
		if !ok {
			return invalid(path, "Input should be a valid dictionary")
		}
		if len(s.AdditionalProperties) == 0 || s.AdditionalProperties[0] != '{' {
			return scalar(raw)
		}
		var child shape
		if err := json.Unmarshal(s.AdditionalProperties, &child); err != nil {
			return invalid(path, "Invalid dictionary schema")
		}
		var object bytes.Buffer
		object.WriteByte('{')
		var problems []Issue
		for _, key := range o.keys {
			v := m.normalize(child, loc(path, key), o.fields[key])
			if v.issues != nil {
				problems = append(problems, v.issues...)
			} else {
				objectField(&object, key, v.full)
			}
		}
		if len(problems) > 0 {
			return normalized{issues: problems}
		}
		object.WriteByte('}')
		return scalar(object.Bytes())
	case "array":
		var items []json.RawMessage
		if err := json.Unmarshal(raw, &items); err != nil || items == nil {
			return invalid(path, "Input should be a valid list")
		}
		var issues []Issue
		full, partial := []json.RawMessage{}, []json.RawMessage{}
		for i, v := range items {
			n := m.normalize(*s.Items, loc(path, strconv.Itoa(i)), v)
			if len(n.issues) > 0 {
				issues = append(issues, n.issues...)
			} else {
				full = append(full, n.full)
				partial = append(partial, n.authored)
			}
		}
		if s.MaxItems != nil && len(items) > *s.MaxItems {
			return invalid(path, fmt.Sprintf("List should have at most %d items after validation, not %d", *s.MaxItems, len(items)))
		}
		if s.MinItems != nil && len(full) < *s.MinItems && len(issues) == 0 {
			return invalid(path, fmt.Sprintf("List should have at least %d item%s after validation, not %d", *s.MinItems, plural(*s.MinItems), len(full)))
		}
		f, _ := json.Marshal(full)
		p, _ := json.Marshal(partial)
		return normalized{f, p, issues}
	case "string":
		return normalizeString(s, path, raw)
	case "integer", "number":
		return normalizeNumber(s, path, raw)
	case "boolean":
		text := string(raw)
		var v string
		if raw[0] == '"' {
			_ = json.Unmarshal(raw, &v)
			text = strings.ToLower(v)
		}
		switch text {
		case "true", "1", "1.0", "on", "yes", "y", "t":
			return scalarValue(true)
		case "false", "0", "0.0", "off", "no", "n", "f":
			return scalarValue(false)
		}
		msg := "Input should be a valid boolean"
		if raw[0] == '"' || raw[0] >= '0' && raw[0] <= '9' {
			msg += ", unable to interpret input"
		}
		return invalid(path, msg)
	}
	return invalid(path, "Invalid schema type")
}
func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

var integerText = regexp.MustCompile(`^[+-]?[0-9](_?[0-9])*(\.0+)?$`)

func normalizeNumber(s shape, path string, raw json.RawMessage) normalized {
	text := string(raw)
	kind := "number"
	if s.Type == "integer" {
		kind = "integer"
	}
	switch {
	case raw[0] == '"':
		var v string
		_ = json.Unmarshal(raw, &v)
		text = strings.TrimSpace(v)
		if kind == "integer" && !integerText.MatchString(text) {
			return invalid(path, "Input should be a valid integer, unable to parse string as an integer")
		}
		text = strings.ReplaceAll(text, "_", "")
	case text == "true":
		text = "1"
	case text == "false":
		text = "0"
	case text == "null" || raw[0] == '{' || raw[0] == '[':
		msg := "Input should be a valid number"
		if kind == "integer" {
			msg = "Input should be a valid integer"
		}
		return invalid(path, msg)
	}
	f, err := strconv.ParseFloat(text, 64)
	if err != nil {
		return invalid(path, "Input should be a valid "+kind+", unable to parse string as "+map[string]string{"integer": "an integer", "number": "a number"}[kind])
	}
	if math.IsNaN(f) || math.IsInf(f, 0) {
		return invalid(path, "Input should be a finite number")
	}
	var number json.RawMessage
	if kind == "integer" {
		r, ok := new(big.Rat).SetString(text)
		if !ok || !r.IsInt() {
			return invalid(path, "Input should be a valid integer, got a number with a fractional part")
		}
		number = []byte(r.Num().String())
	} else {
		t := strconv.FormatFloat(f, 'g', -1, 64)
		if !strings.ContainsAny(t, ".eE") {
			t += ".0"
		}
		number = []byte(t)
	}
	for _, check := range []struct {
		bound   *float64
		invalid func(float64) bool
		label   string
	}{{s.Minimum, func(v float64) bool { return f < v }, "greater than or equal to"}, {s.Maximum, func(v float64) bool { return f > v }, "less than or equal to"}, {s.ExclusiveMinimum, func(v float64) bool { return f <= v }, "greater than"}} {
		if check.bound != nil && check.invalid(*check.bound) {
			return invalid(path, fmt.Sprintf("Input should be %s %g", check.label, *check.bound))
		}
	}
	return scalar(number)
}

func normalizeString(s shape, path string, raw json.RawMessage) normalized {
	var text string
	isString := len(raw) > 0 && raw[0] == '"' && json.Unmarshal(raw, &text) == nil
	if s.Format == "date" || s.Format == "date-time" {
		return normalizeDate(s.Format, path, raw, text, isString)
	}
	if s.Format == "uuid" {
		if !isString {
			return invalid(path, "UUID input should be a string, bytes or UUID object")
		}
		id, err := uuid.Parse(text)
		if err != nil {
			return invalid(path, uuidError(text))
		}
		return scalarValue(id.String())
	}
	if !isString {
		return invalid(path, "Input should be a valid string")
	}
	n := utf8.RuneCountInString(text)
	if s.MinLength != nil && n < *s.MinLength {
		return invalid(path, fmt.Sprintf("String should have at least %d character%s", *s.MinLength, plural(*s.MinLength)))
	}
	if s.MaxLength != nil && n > *s.MaxLength {
		return invalid(path, fmt.Sprintf("String should have at most %d characters", *s.MaxLength))
	}
	if s.Pattern != "" {
		if ok, _ := regexp.MatchString(s.Pattern, text); !ok {
			return invalid(path, "String should match pattern '"+s.Pattern+"'")
		}
	}
	return scalar(raw)
}

func uuidError(id string) string {
	const p = "Input should be a valid UUID, "
	core := strings.TrimPrefix(id, "urn:uuid:")
	if strings.HasPrefix(core, "{") && strings.HasSuffix(core, "}") {
		core = core[1 : len(core)-1]
	}
	for i, r := range core {
		if !strings.ContainsRune("0123456789abcdefABCDEF-", r) {
			return fmt.Sprintf("%sinvalid character: found `%c` at %d", p, r, i+strings.Index(id, core))
		}
	}
	groups := strings.Split(core, "-")
	if len(groups) == 1 && id == core {
		return fmt.Sprintf("%sinvalid length: found %d", p, len(id))
	}
	if len(groups) != 5 {
		return fmt.Sprintf("%sinvalid group count: expected 5, found %d", p, len(groups))
	}
	for i, n := range []int{8, 4, 4, 4, 12} {
		if len(groups[i]) != n {
			return fmt.Sprintf("%sinvalid group length in group %d: expected %d, found %d", p, i, n, len(groups[i]))
		}
	}
	return p + "invalid UUID"
}

func normalizeDate(format, path string, raw json.RawMessage, text string, isString bool) normalized {
	isDate := format == "date"
	if isString && isDate {
		if t, err := time.Parse(time.DateOnly, text); err == nil {
			return scalarValue(t.Format(time.DateOnly))
		}
	}
	instant, err := time.Parse(time.RFC3339Nano, strings.Replace(text, " ", "T", 1))
	if err != nil {
		// Pydantic accepts Unix seconds or milliseconds within its timestamp range.
		number := text
		if !isString {
			number = string(raw)
		}
		f, e := strconv.ParseFloat(number, 64)
		if e == nil && math.Abs(f) < 3e14 {
			if math.Abs(f) > 2e10 {
				f /= 1000
			}
			sec, frac := math.Modf(f)
			instant = time.Unix(int64(sec), int64(math.Round(frac*1e6))*1000).UTC()
			err = nil
		}
	}
	if err != nil {
		for _, layout := range []string{time.DateOnly, "2006-01-02T15:04:05.999999999", "2006-01-02T15:04"} {
			if t, e := time.Parse(layout, text); e == nil {
				if !isDate {
					return invalid(path, "Input should have timezone info")
				}
				instant = t
				err = nil
				break
			}
		}
	}
	if err != nil {
		if !isString {
			if isDate {
				return invalid(path, "Input should be a valid date")
			}
			return invalid(path, "Input should be a valid datetime")
		}
		label := "datetime"
		if isDate {
			label = "date or datetime"
		}
		cause := "input is too short"
		if len(text) >= 10 {
			cause = "invalid character in year"
		}
		return invalid(path, "Input should be a valid "+label+", "+cause)
	}
	if isDate {
		if instant.Hour() != 0 || instant.Minute() != 0 || instant.Second() != 0 || instant.Nanosecond() != 0 {
			return invalid(path, "Datetimes provided to dates should have zero time - e.g. be exact dates")
		}
		return scalarValue(instant.Format(time.DateOnly))
	}
	layout := "2006-01-02T15:04:05"
	if instant.Nanosecond()/1000 != 0 {
		layout += ".000000"
	}
	return scalarValue(instant.Format(layout + "Z07:00"))
}
