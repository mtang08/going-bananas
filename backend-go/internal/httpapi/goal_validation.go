package httpapi

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
	"unicode"
	"unicode/utf8"

	"github.com/mtang08/going-bananas/backend-go/api"
)

func uuidMessage(id string) string {
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

func positiveInteger(value any) (int, string) {
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
		return 0, "Input should be greater than or equal to 1"
	default:
		return 0, "Input should be a valid integer"
	}
	if i, err := strconv.ParseInt(number, 10, 64); err == nil {
		if i < 1 {
			return 0, "Input should be greater than or equal to 1"
		}
		return int(i), ""
	}
	f, _ := strconv.ParseFloat(number, 64)
	if f != math.Trunc(f) {
		return 0, "Input should be a valid integer, got a number with a fractional part"
	}
	if f < 1 {
		return 0, "Input should be greater than or equal to 1"
	}
	// PostgreSQL uses int4. A larger version cannot match, and an
	// overflowing priority must reach the database error path.
	if f >= float64(math.MaxInt) {
		return math.MaxInt, ""
	}
	return int(f), ""
}

func goalField(p *api.GoalPatch, key string, value any) string {
	switch key {
	case "expected_version", "priority":
		if key == "priority" && value == nil {
			p.Priority.SetNull()
			return ""
		}
		i, message := positiveInteger(value)
		if key == "expected_version" {
			p.ExpectedVersion = i
		} else {
			p.Priority.Set(i)
		}
		return message
	case "text":
		if value == nil {
			p.Text.SetNull()
			return ""
		}
		v, ok := value.(string)
		if !ok {
			return "Input should be a valid string"
		}
		v = strings.TrimFunc(v, func(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) })
		if v == "" {
			return "Value error, Goal text must be nonblank"
		}
		p.Text.Set(v)
	case "horizon":
		if value == nil {
			p.Horizon.SetNull()
			return ""
		}
		v, _ := value.(string)
		h := api.GoalHorizon(v)
		if !h.Valid() {
			return "Input should be '3_6_months', 'season' or 'long_term'"
		}
		p.Horizon.Set(h)
	case "status":
		if value == nil {
			p.Status.SetNull()
			return ""
		}
		v, _ := value.(string)
		status := api.GoalStatus(v)
		if !status.Valid() {
			return "Input should be 'active', 'paused', 'done' or 'dropped'"
		}
		p.Status.Set(status)
	}
	return ""
}

func decodeGoalInput(r io.Reader, create bool) (api.GoalPatch, []api.ValidationField) {
	var patch api.GoalPatch
	var fields []api.ValidationField
	add := func(field, message string) {
		fields = append(fields, api.ValidationField{Field: field, Message: message})
	}
	values, order, fields := decodeInputObject(r)
	if len(fields) > 0 {
		return patch, fields
	}
	keys := []string{"expected_version", "text", "horizon", "priority", "status"}
	if create {
		keys = []string{"text", "horizon", "priority"}
	}
	for _, key := range keys {
		v, ok := values[key]
		delete(values, key)
		if !ok {
			if create || key == "expected_version" {
				add("body."+key, "Field required")
			}
			continue
		}
		if create && v == nil {
			messages := map[string]string{"priority": "Input should be a valid integer", "text": "Input should be a valid string", "horizon": "Input should be '3_6_months', 'season' or 'long_term'"}
			add("body."+key, messages[key])
			continue
		}
		if message := goalField(&patch, key, v); message != "" {
			add("body."+key, message)
		}
	}
	for _, key := range order {
		if _, ok := values[key]; ok {
			add("body."+key, "Extra inputs are not permitted")
		}
	}
	return patch, fields
}

func decodeInputObject(r io.Reader) (map[string]any, []string, []api.ValidationField) {
	var fields []api.ValidationField
	add := func(field, message string) {
		fields = append(fields, api.ValidationField{Field: field, Message: message})
	}
	body, err := io.ReadAll(r)
	if err != nil || len(body) == 0 || string(bytes.TrimSpace(body)) == "null" {
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
