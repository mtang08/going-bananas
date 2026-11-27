package httpapi

import (
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/httpinput"
	"io"
	"strings"
	"unicode"
)

func positiveInteger(v any) (int, string) { return httpinput.Integer(v, 1) }
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
	values, order, errors := httpinput.Object(r)
	if len(errors) > 0 {
		return patch, errors
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
