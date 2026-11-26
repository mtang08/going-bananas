package coachdashboard

import (
	"bytes"
	"encoding/json"
	"math"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
)

func integer(value any) (int, bool) {
	switch v := value.(type) {
	case int:
		return v, true
	case float64:
		n := int(v)
		return n, !math.IsInf(v, 0) && float64(n) == v
	case json.Number:
		n, err := strconv.Atoi(string(v))
		return n, err == nil
	default:
		return 0, false
	}
}

func validateQuery(args Object) error {
	name := field(args, "name")
	for k, v := range args {
		if k == "name" {
			continue
		}
		switch k {
		case "activity_id", "result_id", "start", "end", "from_version", "to_version":
		default:
			return invalidArgs()
		}
		if v == nil {
			continue
		}
		switch name {
		case "activity_execution":
			if k != "activity_id" {
				return invalidArgs()
			}
		case "explain_metric":
			if k != "result_id" {
				return invalidArgs()
			}
		case "long_run_history", "recovery_nights":
			if k != "start" && k != "end" {
				return invalidArgs()
			}
		case "calendar_diff":
			if k != "from_version" && k != "to_version" {
				return invalidArgs()
			}
		}
	}
	switch name {
	case "activity_execution", "explain_metric":
		k := "activity_id"
		if name == "explain_metric" {
			k = "result_id"
		}
		if _, err := uuid.Parse(field(args, k)); err != nil {
			return invalidArgs()
		}
	case "long_run_history", "recovery_nights":
		a, err := time.Parse(time.DateOnly, field(args, "start"))
		if err != nil {
			return invalidArgs()
		}
		b, err := time.Parse(time.DateOnly, field(args, "end"))
		if err != nil {
			return invalidArgs()
		}
		if b.Before(a) || !b.Before(a.AddDate(0, 0, 92)) {
			return toolFailure("invalid_date_window", "Choose a date window of at most 92 days.")
		}
	case "calendar_diff":
		for _, k := range []string{"from_version", "to_version"} {
			n, ok := integer(args[k])
			if !ok || n < 0 {
				return invalidArgs()
			}
		}
	default:
		return invalidArgs()
	}
	return nil
}

func pendingArgs(args Object) (PendingRequest, error) {
	req := PendingRequest{Document: object(args["document"])}
	if req.Document == nil {
		return req, invalidArgs()
	}
	for k := range args {
		switch k {
		case "document", "proposal_id", "expected_revision", "reason":
		default:
			return req, invalidArgs()
		}
	}
	if args["proposal_id"] == nil && args["expected_revision"] == nil && args["reason"] == nil {
		return req, nil
	}
	var err error
	req.ProposalID, err = uuid.Parse(field(args, "proposal_id"))
	req.ExpectedRevision, _ = integer(args["expected_revision"])
	req.Reason = field(args, "reason")
	if err != nil || req.ProposalID == uuid.Nil || req.ExpectedRevision < 1 || req.Reason == "" || utf8.RuneCountInString(req.Reason) > 500 {
		return req, invalidArgs()
	}
	return req, nil
}

func filteredObject(data Object) (Object, error) {
	encoded, err := json.Marshal(data)
	if err != nil {
		return nil, err
	}
	dec := json.NewDecoder(bytes.NewReader(encoded))
	dec.UseNumber()
	var result Object
	if err := dec.Decode(&result); err != nil {
		return nil, err
	}
	stripPrivate(result)
	return result, nil
}
func stripPrivate(value any) {
	switch v := value.(type) {
	case Object:
		for key, item := range v {
			for _, term := range []string{"note", "latitude", "longitude", "gps", "coordinate", "stream", "access_token", "refresh_token", "password", "secret", "vo2max", "training_status", "body_battery", "readiness"} {
				if strings.Contains(strings.ToLower(key), term) {
					delete(v, key)
					break
				}
			}
			stripPrivate(item)
		}
	case []any:
		for _, item := range v {
			stripPrivate(item)
		}
	}
}
