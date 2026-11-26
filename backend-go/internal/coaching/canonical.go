// Package coaching computes identities for coaching decision evidence.
package coaching

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"reflect"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
)

// CanonicalJSON returns the UTF-8 bytes used by Python's coaching canonical_json.
// Supply calendar dates as ISO date strings. UUIDs may be uuid.UUID values
// or lowercase hyphenated strings.
// Use json.Decoder.UseNumber when reading evidence from JSON.
func CanonicalJSON(value any) ([]byte, error) {
	var buf bytes.Buffer
	if err := writeValue(&buf, reflect.ValueOf(value), 0); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func writeValue(buf *bytes.Buffer, value reflect.Value, depth int) error {
	if !value.IsValid() {
		buf.WriteString("null")
		return nil
	}
	// Bound recursion for cyclic maps/slices, which cannot be JSON evidence.
	if depth > 1000 {
		return fmt.Errorf("coaching evidence exceeds maximum nesting depth")
	}
	switch v := value.Interface().(type) {
	case uuid.UUID:
		return writeString(buf, v.String())
	case time.Time:
		utc := v.UTC()
		if utc.Year() < 1 || utc.Year() > 9999 || utc.Nanosecond()%1000 != 0 {
			return fmt.Errorf("instant outside Python datetime range or precision")
		}
		layout := "2006-01-02T15:04:05"
		if utc.Nanosecond() != 0 {
			layout += ".000000"
		}
		return writeString(buf, utc.Format(layout)+"+00:00")
	case json.Number:
		return writeNumber(buf, v.String())
	}
	switch value.Kind() {
	case reflect.Interface:
		return writeValue(buf, value.Elem(), depth)
	case reflect.String:
		return writeString(buf, value.String())
	case reflect.Bool:
		buf.WriteString(strconv.FormatBool(value.Bool()))
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
		buf.WriteString(strconv.FormatInt(value.Int(), 10))
	case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
		buf.WriteString(strconv.FormatUint(value.Uint(), 10))
	case reflect.Float32, reflect.Float64:
		return writeFloat(buf, value.Float())
	case reflect.Map:
		if value.Type().Key().Kind() != reflect.String {
			return fmt.Errorf("coaching evidence requires string object keys")
		}
		if value.IsNil() {
			buf.WriteString("null")
			return nil
		}
		keys := value.MapKeys()
		sort.Slice(keys, func(i, j int) bool { return keys[i].String() < keys[j].String() })
		buf.WriteByte('{')
		for i, key := range keys {
			if i > 0 {
				buf.WriteByte(',')
			}
			if err := writeString(buf, key.String()); err != nil {
				return err
			}
			buf.WriteByte(':')
			if err := writeValue(buf, value.MapIndex(key), depth+1); err != nil {
				return err
			}
		}
		buf.WriteByte('}')
	case reflect.Array, reflect.Slice:
		if value.Kind() == reflect.Slice && value.IsNil() {
			buf.WriteString("null")
			return nil
		}
		buf.WriteByte('[')
		for i := 0; i < value.Len(); i++ {
			if i > 0 {
				buf.WriteByte(',')
			}
			if err := writeValue(buf, value.Index(i), depth+1); err != nil {
				return err
			}
		}
		buf.WriteByte(']')
	default:
		return fmt.Errorf("unsupported coaching evidence type %s", value.Type())
	}
	return nil
}

var jsonNumberSyntax = regexp.MustCompile(`^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$`)

func writeNumber(buf *bytes.Buffer, number string) error {
	if !jsonNumberSyntax.MatchString(number) {
		return fmt.Errorf("invalid JSON number")
	}
	if !strings.ContainsAny(number, ".Ee") {
		if number == "-0" {
			number = "0"
		}
		buf.WriteString(number)
		return nil
	}
	value, err := strconv.ParseFloat(number, 64)
	if err != nil {
		return err
	}
	return writeFloat(buf, value)
}

func writeFloat(buf *bytes.Buffer, value float64) error {
	if math.IsNaN(value) || math.IsInf(value, 0) {
		return fmt.Errorf("non-finite coaching evidence")
	}
	// Python switches to exponent notation outside [1e-4, 1e16) for nonzero floats.
	magnitude := math.Abs(value)
	if magnitude >= 1e16 || (magnitude > 0 && magnitude < 1e-4) {
		buf.WriteString(strconv.FormatFloat(value, 'e', -1, 64))
		return nil
	}
	decimal := strconv.FormatFloat(value, 'f', -1, 64)
	buf.WriteString(decimal)
	if !strings.Contains(decimal, ".") {
		buf.WriteString(".0")
	}
	return nil
}

func writeString(buf *bytes.Buffer, value string) error {
	if !utf8.ValidString(value) {
		return fmt.Errorf("coaching evidence requires valid UTF-8")
	}
	const hex = "0123456789abcdef"
	buf.WriteByte('"')
	for i := 0; i < len(value); i++ {
		ch := value[i]
		switch ch {
		case '"', '\\':
			buf.WriteByte('\\')
			buf.WriteByte(ch)
		case '\b':
			buf.WriteString(`\b`)
		case '\f':
			buf.WriteString(`\f`)
		case '\n':
			buf.WriteString(`\n`)
		case '\r':
			buf.WriteString(`\r`)
		case '\t':
			buf.WriteString(`\t`)
		default:
			if ch < 0x20 {
				buf.WriteString(`\u00`)
				buf.WriteByte(hex[ch>>4])
				buf.WriteByte(hex[ch&15])
			} else {
				buf.WriteByte(ch)
			}
		}
	}
	buf.WriteByte('"')
	return nil
}
