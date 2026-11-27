package completionhttp

import (
	"fmt"
	"io"
	"slices"
	"strings"

	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/calendar"
	"github.com/mtang08/going-bananas/backend-go/internal/httpinput"
)

type input struct {
	link      calendar.RecordingLink
	status    calendar.ReportStatus
	hasStatus bool
}

var statuses = []string{"skipped", "unknown", "completed_as_planned"}
var reasons = []string{"symptom_onset", "fatigue", "illness", "schedule", "weather", "equipment", "other"}

func literal(value any, choices []string) (string, string) {
	str, ok := value.(string)
	if ok && slices.Contains(choices, str) {
		return str, ""
	}
	return "", fmt.Sprintf("Input should be '%s' or '%s'", strings.Join(choices[:len(choices)-1], "', '"), choices[len(choices)-1])
}
func bind(reader io.Reader) (input, []api.ValidationField) {
	var in input
	values, order, fields := httpinput.Object(reader)
	if len(fields) > 0 {
		return in, fields
	}
	for _, key := range []string{"expected_version", "activity_id", "strong_workout_id", "manual_session_id", "status", "modification_reason", "reason_note"} {
		value, ok := values[key]
		if !ok {
			continue
		}
		delete(values, key)
		if key == "status" {
			in.hasStatus = true
		}
		if value == nil {
			continue
		}
		var message string
		switch key {
		case "expected_version":
			in.link.ExpectedVersion, message = httpinput.Integer(value, 0)
		case "activity_id":
			in.link.ActivityID, message = httpinput.UUID(value)
		case "strong_workout_id":
			in.link.StrongWorkoutID, message = httpinput.UUID(value)
		case "manual_session_id":
			in.link.ManualSessionID, message = httpinput.UUID(value)
		case "status":
			v, m := literal(value, statuses)
			message = m
			in.status = calendar.ReportStatus(v)
		case "modification_reason":
			v, m := literal(value, reasons)
			message = m
			in.link.ModificationReason = &v
		case "reason_note":
			v, ok := value.(string)
			if !ok {
				message = "Input should be a valid string"
			} else {
				in.link.ReasonNote = &v
			}
		}
		if message != "" {
			fields = append(fields, api.ValidationField{Field: "body." + key, Message: message})
		}
	}
	for _, key := range order {
		if _, ok := values[key]; ok {
			fields = append(fields, api.ValidationField{Field: "body." + key, Message: "Extra inputs are not permitted"})
		}
	}
	return in, fields
}
