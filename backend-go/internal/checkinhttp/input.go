package checkinhttp

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/mtang08/going-bananas/backend-go/internal/checkins"
)

type fieldError struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}
type validation struct{ fields []fieldError }

func (v *validation) add(loc, msg string) { v.fields = append(v.fields, fieldError{loc, msg}) }
func (v *validation) object(r *http.Request) map[string]any {
	d := json.NewDecoder(r.Body)
	d.UseNumber()
	var obj any
	if err := d.Decode(&obj); errors.Is(err, io.EOF) {
		v.add("body", "Field required")
		return nil
	} else if err != nil {
		v.add("body", "JSON decode error")
		return nil
	}
	if !errors.Is(d.Decode(new(any)), io.EOF) {
		v.add("body", "JSON decode error")
		return nil
	}
	m, ok := obj.(map[string]any)
	if !ok {
		v.add("body", "Input should be a valid dictionary or object to extract fields from")
		return nil
	}
	return m
}
func (v *validation) shape(obj map[string]any, loc string, allowed, required []string) {
	for _, key := range required {
		if _, ok := obj[key]; !ok {
			v.add(loc+"."+key, "Field required")
		}
	}
	var extra []string
	for key := range obj {
		if !slices.Contains(allowed, key) {
			extra = append(extra, key)
		}
	}
	slices.Sort(extra)
	for _, key := range extra {
		v.add(loc+"."+key, "Extra inputs are not permitted")
	}
}
func (v *validation) choice(x any, loc string, values ...string) string {
	s, _ := x.(string)
	if slices.Contains(values, s) {
		return s
	}
	labels := make([]string, len(values))
	for i, s := range values {
		labels[i] = "'" + s + "'"
	}
	v.add(loc, "Input should be "+strings.Join(labels[:len(labels)-1], ", ")+" or "+labels[len(labels)-1])
	return ""
}

var numericTime = regexp.MustCompile(`^[+-]?[0-9]+(?:\.[0-9]+)?$`)
var integerString = regexp.MustCompile(`^[+-]?[0-9](?:_?[0-9])*(?:\.0+)?$`)

func unixInstant(s string) (time.Time, bool) {
	f, err := strconv.ParseFloat(s, 64)
	if err != nil || math.IsNaN(f) || math.IsInf(f, 0) {
		return time.Time{}, false
	}
	if math.Abs(f) > 2e10 {
		f /= 1000
	}
	if f < -62135596800 || f >= 253402300800 {
		return time.Time{}, false
	}
	sec, fr := math.Modf(f)
	return time.Unix(int64(sec), int64(math.Round(fr*1e6))*1000).UTC(), true
}

func isoInstant(s string) (time.Time, bool) {
	if len(s) > 10 && strings.ContainsRune("t_ ", rune(s[10])) {
		s = s[:10] + "T" + s[11:]
	}
	if strings.HasSuffix(s, "z") {
		s = s[:len(s)-1] + "Z"
	}
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04Z07:00", "2006-01-02T15:04:05Z0700", "2006-01-02T15:04Z0700"} {
		if t, e := time.Parse(layout, s); e == nil {
			_, off := t.Zone()
			if off <= -24*3600 || off >= 24*3600 {
				return time.Time{}, false
			}
			return t.Truncate(time.Microsecond), true
		}
	}
	return time.Time{}, false
}

func (v *validation) instant(x any, loc string, phone bool) time.Time {
	if n, ok := x.(json.Number); ok {
		if t, ok := unixInstant(n.String()); ok {
			return t
		}
	}
	if s, ok := x.(string); ok {
		if numericTime.MatchString(s) {
			if t, ok := unixInstant(s); ok {
				return t
			}
		}
		if t, ok := isoInstant(s); ok {
			return t.UTC()
		}
		for _, layout := range []string{"2006-01-02T15:04:05", "2006-01-02T15:04", time.DateOnly} {
			if _, e := time.Parse(layout, strings.Replace(s, " ", "T", 1)); e == nil {
				if phone {
					v.add(loc, "Input should have timezone info")
				} else {
					v.add(loc, "Value error, observed_at must include offset")
				}
				return time.Time{}
			}
		}
		if len(s) < 10 {
			v.add(loc, "Input should be a valid datetime or date, input is too short")
			return time.Time{}
		}
	}
	v.add(loc, "Input should be a valid datetime")
	return time.Time{}
}
func (v *validation) version(x any) int {
	const loc = "body.expected_version"
	var n float64
	switch val := x.(type) {
	case bool:
		if val {
			return 1
		}
	case json.Number:
		n, _ = val.Float64()
	case string:
		s := strings.TrimSpace(val)
		if !integerString.MatchString(s) {
			v.add(loc, "Input should be a valid integer, unable to parse string as an integer")
			return 0
		}
		n, _ = strconv.ParseFloat(strings.ReplaceAll(s, "_", ""), 64)
	default:
		v.add(loc, "Input should be a valid integer")
		return 0
	}
	if n != math.Trunc(n) {
		v.add(loc, "Input should be a valid integer, got a number with a fractional part")
		return 0
	}
	if n < 1 {
		v.add(loc, "Input should be greater than or equal to 1")
		return 0
	}
	if n >= math.MaxInt {
		return math.MaxInt
	}
	return int(n)
}
func (v *validation) measure(x any, loc string) float64 {
	var s string
	switch n := x.(type) {
	case json.Number:
		s = n.String()
		if strings.ContainsAny(s, ".eE") {
			if f, e := n.Float64(); e == nil {
				s = strconv.FormatFloat(f, 'f', -1, 64)
			}
		}
	case string:
		s = strings.TrimSpace(n)
	}
	f, e := strconv.ParseFloat(s, 64)
	if e != nil {
		v.add(loc, "Value error, measurement must be numeric")
		return 0
	}
	mantissa, expt, _ := strings.Cut(strings.ToLower(s), "e")
	exp, _ := strconv.Atoi(expt)
	_, frac, _ := strings.Cut(mantissa, ".")
	if math.IsNaN(f) || math.IsInf(f, 0) || f < 0 || f > 10 || len(frac)-exp > 1 {
		v.add(loc, "Value error, measurement must be 0–10 with at most one decimal place")
	}
	return f
}
func (v *validation) symptoms(x any) []checkins.Symptom {
	list, ok := x.([]any)
	if !ok {
		v.add("body.symptoms", "Input should be a valid list")
		return nil
	}
	out := make([]checkins.Symptom, 0, len(list))
	for i, x := range list {
		loc := fmt.Sprintf("body.symptoms.%d", i)
		row, ok := x.(map[string]any)
		if !ok {
			v.add(loc, "Input should be a valid dictionary or object to extract fields from")
			continue
		}
		keys := []string{"site", "side", "severity", "timing"}
		v.shape(row, loc, keys, keys)
		var s checkins.Symptom
		if x, ok := row["site"]; ok {
			site, ok := x.(string)
			if !ok {
				v.add(loc+".site", "Input should be a valid string")
			} else {
				s.Site = strings.TrimSpace(site)
				if n := utf8.RuneCountInString(s.Site); n < 1 || n > 60 {
					v.add(loc+".site", "Value error, site must be 1–60 characters")
				}
			}
		}
		if x, ok := row["side"]; ok {
			s.Side = v.choice(x, loc+".side", "left", "right", "both", "na")
		}
		if x, ok := row["severity"]; ok {
			s.Severity = v.measure(x, loc+".severity")
		}
		if x, ok := row["timing"]; ok {
			s.Timing = v.choice(x, loc+".timing", "during", "immediately_after", "next_morning", "hours_24_48", "later", "unknown")
		}
		out = append(out, s)
	}
	return out
}

var checkinFields = []string{"kind", "observed_at", "fatigue", "illness", "pain_reported", "gait_change", "context_tags", "activity_id", "prompt_id", "note", "symptoms"}

func (v *validation) input(obj map[string]any, patch bool) (checkins.Input, int, map[string]json.RawMessage) {
	var input checkins.Input
	key := "idempotency_key"
	required := []string{key, "kind", "observed_at"}
	if patch {
		key = "expected_version"
		required = []string{key}
	}
	v.shape(obj, "body", append([]string{key}, checkinFields...), required)
	version := 0
	if x, ok := obj[key]; ok {
		if patch {
			version = v.version(x)
		} else {
			val, ok := x.(string)
			if !ok {
				v.add("body."+key, "Input should be a valid string")
			} else if val == "" {
				v.add("body."+key, "String should have at least 1 character")
			} else if utf8.RuneCountInString(val) > 100 {
				v.add("body."+key, "String should have at most 100 characters")
			}
			input.IdempotencyKey = val
		}
	}
	changes := map[string]json.RawMessage{}
	for _, k := range checkinFields {
		x, set := obj[k]
		if !set {
			continue
		}
		loc := "body." + k
		var normalized any
		if x != nil || !patch && slices.Contains([]string{"kind", "observed_at", "context_tags", "symptoms"}, k) {
			switch k {
			case "kind":
				input.Kind = v.choice(x, loc, "exception", "post_run", "delayed_followup")
				normalized = input.Kind
			case "observed_at":
				input.ObservedAt = v.instant(x, loc, false)
				normalized = input.ObservedAt
			case "fatigue":
				f := v.measure(x, loc)
				input.Fatigue = &f
				normalized = f
			case "illness":
				s := v.choice(x, loc, "none", "possible", "present")
				input.Illness = &s
				normalized = s
			case "gait_change":
				s := v.choice(x, loc, "yes", "no", "unsure")
				input.GaitChange = &s
				normalized = s
			case "pain_reported":
				b, ok := x.(bool)
				if !ok {
					v.add(loc, "Input should be a valid boolean")
				}
				input.PainReported = &b
				normalized = b
			case "note":
				s, ok := x.(string)
				if !ok {
					v.add(loc, "Input should be a valid string")
				}
				input.Note = &s
				normalized = s
			case "activity_id", "prompt_id":
				s, _ := x.(string)
				id, e := uuid.Parse(s)
				if e != nil {
					v.add(loc, "Input should be a valid UUID")
				}
				if k == "activity_id" {
					input.ActivityID = &id
				} else {
					input.PromptID = &id
				}
				normalized = id
			case "symptoms":
				input.Symptoms = v.symptoms(x)
				normalized = input.Symptoms
			case "context_tags":
				tags, ok := x.([]any)
				if !ok {
					v.add(loc, "Input should be a valid list")
					break
				}
				values := make([]string, 0, len(tags))
				bad := false
				for i, item := range tags {
					tag, ok := item.(string)
					if !ok {
						v.add(fmt.Sprintf("%s.%d", loc, i), "Input should be a valid string")
						continue
					}
					if !slices.Contains([]string{"heat", "travel", "poor_sleep", "unusual_surface", "equipment"}, tag) || slices.Contains(values, tag) {
						bad = true
					}
					values = append(values, tag)
				}
				if bad {
					v.add(loc, "Value error, invalid context tags")
				}
				input.ContextTags = values
				normalized = values
			}
		}
		changes[k], _ = json.Marshal(normalized)
	}
	return input, version, changes
}
