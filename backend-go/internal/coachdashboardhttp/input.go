package coachdashboardhttp

import (
	"encoding/json"
	"errors"
	"io"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/mtang08/going-bananas/backend-go/internal/coachdashboard"
)

type input struct {
	guard                  coachdashboard.Guard
	clientID, text, intent string
}

func parseInput(body io.Reader, message bool) (input, []field) {
	var result input
	var value any
	dec := json.NewDecoder(body)
	dec.UseNumber()
	err := dec.Decode(&value)
	if errors.Is(err, io.EOF) {
		return result, []field{{"body", "Field required"}}
	}
	if err == nil {
		var extra any
		if tail := dec.Decode(&extra); !errors.Is(tail, io.EOF) {
			err = errors.New("trailing JSON")
		}
	}
	if err != nil {
		pos := dec.InputOffset()
		var syntax *json.SyntaxError
		if errors.As(err, &syntax) {
			pos = syntax.Offset - 1
		}
		return result, []field{{"body." + strconv.FormatInt(pos, 10), "JSON decode error"}}
	}
	if value == nil {
		return result, []field{{"body", "Field required"}}
	}
	object, ok := value.(map[string]any)
	if !ok {
		return result, []field{{"body", "Input should be a valid dictionary or object to extract fields from"}}
	}
	var fields []field
	add := func(name, msg string) { fields = append(fields, field{"body." + name, msg}) }
	readUUID := func(name string, v any) string {
		s, isString := v.(string)
		if !isString {
			add(name, "UUID input should be a string, bytes or UUID object")
			return ""
		}
		if len(s) == 38 && (!strings.HasPrefix(s, "{") || !strings.HasSuffix(s, "}")) {
			add(name, "Input should be a valid UUID")
			return ""
		}
		id, err := uuid.Parse(s)
		if err != nil {
			add(name, "Input should be a valid UUID")
			return ""
		}
		return id.String()
	}
	if v, exists := object["thread_id"]; exists {
		result.guard.Set = true
		if v != nil {
			result.guard.ID = readUUID("thread_id", v)
		}
		delete(object, "thread_id")
	}
	if message {
		v, exists := object["text"]
		s, ok := v.(string)
		result.text = strings.TrimSpace(s)
		switch {
		case !exists:
			add("text", "Field required")
		case !ok:
			add("text", "Input should be a valid string")
		case result.text == "":
			add("text", "String should have at least 1 character")
		case utf8.RuneCountInString(result.text) > 8000:
			add("text", "String should have at most 8000 characters")
		}
		if id, ok := object["client_message_id"]; ok {
			result.clientID = readUUID("client_message_id", id)
		} else {
			add("client_message_id", "Field required")
		}
		if v := object["intent"]; v != nil {
			result.intent, _ = v.(string)
			if result.intent != "sunday_review" && result.intent != "today_run" {
				add("intent", "Input should be 'sunday_review' or 'today_run'")
			}
		}
		delete(object, "text")
		delete(object, "intent")
		delete(object, "client_message_id")
	}
	keys := make([]string, 0, len(object))
	for k := range object {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		add(k, "Extra inputs are not permitted")
	}
	return result, fields
}
