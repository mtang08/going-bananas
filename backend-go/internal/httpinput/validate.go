// Package httpinput implements the input coercion shared by local FastAPI-compatible routes.
package httpinput

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/mtang08/going-bananas/backend-go/api"
)

func UUIDMessage(id string) string {
	const prefix = "Input should be a valid UUID, "
	core := strings.TrimPrefix(id, "urn:uuid:")
	if strings.HasPrefix(core, "{") && strings.HasSuffix(core, "}") {
		core = core[1 : len(core)-1]
	}
	offset := strings.Index(id, core)
	for i, r := range core {
		if !strings.ContainsRune("0123456789abcdefABCDEF-", r) {
			return fmt.Sprintf("%sinvalid character: found `%c` at %d", prefix, r, i+offset)
		}
	}
	groups := strings.Split(core, "-")
	if len(groups) == 1 && core == id && len(id) != 36 {
		return fmt.Sprintf("%sinvalid length: found %d", prefix, len(id))
	}
	if len(groups) != 5 {
		return fmt.Sprintf("%sinvalid group count: expected 5, found %d", prefix, len(groups))
	}
	for i, v := range []int{8, 4, 4, 4, 12} {
		if len(groups[i]) != v {
			return fmt.Sprintf("%sinvalid group length in group %d: expected %d, found %d", prefix, i, v, len(groups[i]))
		}
	}
	return prefix + "invalid UUID"
}

var integerString = regexp.MustCompile(`^[+-]?[0-9](_?[0-9])*(\.0+)?$`)

func Integer(value any, min int) (int, string) {
	var number string
	switch v := value.(type) {
	case json.Number:
		number = v.String()
	case string:
		number = strings.TrimSpace(v)
		if !integerString.MatchString(number) {
			return 0, "Input should be a valid integer, unable to parse string as an integer"
		}
		number = strings.ReplaceAll(number, "_", "")
	case bool:
		if v {
			return 1, ""
		}
		if min == 0 {
			return 0, ""
		}
		return 0, fmt.Sprintf("Input should be greater than or equal to %d", min)
	default:
		return 0, "Input should be a valid integer"
	}
	if i, err := strconv.ParseInt(number, 10, 64); err == nil {
		if i < int64(min) {
			return 0, fmt.Sprintf("Input should be greater than or equal to %d", min)
		}
		return int(i), ""
	}
	f, _ := strconv.ParseFloat(number, 64)
	if f != math.Trunc(f) {
		return 0, "Input should be a valid integer, got a number with a fractional part"
	}
	if f < float64(min) {
		return 0, fmt.Sprintf("Input should be greater than or equal to %d", min)
	}
	// PostgreSQL uses int4. A larger version cannot match, and an
	// overflowing priority must reach the database error path.
	if f >= float64(math.MaxInt) {
		return math.MaxInt, ""
	}
	return int(f), ""
}

func Object(r io.Reader) (map[string]any, []string, []api.ValidationField) {
	var fields []api.ValidationField
	add := func(field, message string) {
		fields = append(fields, api.ValidationField{Field: field, Message: message})
	}
	body, err := io.ReadAll(r)
	if err != nil || len(body) == 0 {
		add("body", "Field required")
		return nil, nil, fields
	}
	var raw json.RawMessage
	if err := json.Unmarshal(body, &raw); err != nil {
		pos := int64(len(body))
		var syntax *json.SyntaxError
		if errors.As(err, &syntax) && syntax.Offset > 0 && syntax.Error() != "unexpected end of JSON input" {
			pos = syntax.Offset - 1
		}
		add("body."+strconv.Itoa(utf8.RuneCount(body[:pos])), "JSON decode error")
		return nil, nil, fields
	}
	if raw[0] != '{' {
		add("body", "Input should be a valid dictionary or object to extract fields from")
		return nil, nil, fields
	}
	// Keep unknown fields in input order and report known fields in model
	// order, matching FastAPI's accumulated validation errors.
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	_, _ = dec.Token()
	values := map[string]any{}
	var order []string
	for dec.More() {
		token, _ := dec.Token()
		key := token.(string)
		if _, ok := values[key]; !ok {
			order = append(order, key)
		}
		var v any
		_ = dec.Decode(&v)
		values[key] = v
	}
	return values, order, nil
}

func UUID(value any) (*uuid.UUID, string) {
	s, ok := value.(string)
	if !ok {
		return nil, "UUID input should be a string, bytes or UUID object"
	}
	raw := strings.TrimPrefix(s, "urn:uuid:")
	if strings.HasPrefix(raw, "{") && strings.HasSuffix(raw, "}") {
		raw = raw[1 : len(raw)-1]
	}
	if len(raw) != 32 && len(raw) != 36 {
		return nil, UUIDMessage(s)
	}
	id, err := uuid.Parse(raw)
	if err != nil {
		return nil, UUIDMessage(s)
	}
	return &id, ""
}
