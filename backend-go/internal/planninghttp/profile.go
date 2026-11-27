package planninghttp

import (
	"context"
	"encoding/json"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/planning"
)

func knownProfileFields(body json.RawMessage) json.RawMessage {
	var fields map[string]json.RawMessage
	if json.Unmarshal(body, &fields) != nil || fields == nil {
		return body
	}
	// ProfileInput follows Pydantic's default extra=ignore.
	var shape map[string]json.RawMessage
	b, _ := json.Marshal(planning.ProfileData{})
	_ = json.Unmarshal(b, &shape)
	for k := range fields {
		if _, ok := shape[k]; (!ok || k == "version") && k != "expected_version" {
			delete(fields, k)
		}
	}
	b, _ = json.Marshal(fields)
	return b
}
func checkModel(name string, body []byte) string {
	if name != "RunningInterruption" && name != "RunningRestriction" {
		return ""
	}
	var x struct {
		Start     string  `json:"starts_on"`
		End       *string `json:"ends_on"`
		Return    *string `json:"return_on"`
		Review    *string `json:"review_on"`
		Pause     bool    `json:"pause_running"`
		NoQuality bool    `json:"no_quality"`
		Distance  *int    `json:"max_distance_m"`
		Duration  *int    `json:"max_duration_s"`
	}
	_ = json.Unmarshal(body, &x)
	if name == "RunningInterruption" {
		switch {
		case (x.Return == nil) == (x.Review == nil):
			return "Give either a confirmed return date or a review date"
		case x.Return != nil && *x.Return <= x.Start:
			return "The first available day must be after the first unavailable day"
		case x.Review != nil && *x.Review < x.Start:
			return "The review cannot be before the first unavailable day"
		}
	} else {
		switch {
		case x.End != nil && *x.End < x.Start:
			return "Last restricted day cannot be before the start"
		case x.Review != nil && *x.Review < x.Start:
			return "Review date cannot be before the start"
		case !x.Pause && !x.NoQuality && x.Distance == nil && x.Duration == nil:
			return "Enter at least one running limit"
		}
	}
	return ""
}
func factInput(raw json.RawMessage) (json.RawMessage, []field) {
	var obj map[string]json.RawMessage
	if json.Unmarshal(raw, &obj) != nil || obj == nil {
		return raw, nil
	}
	for _, key := range []string{"source", "wording"} {
		var text string
		if json.Unmarshal(obj[key], &text) == nil && string(obj[key]) != "null" {
			obj[key], _ = json.Marshal(strings.TrimSpace(text))
		}
	}
	var fields []field
	for _, key := range []string{"max_distance_m", "max_duration_s"} {
		v, ok := obj[key]
		if !ok || string(v) == "null" {
			continue
		}
		var integer json.Number
		if len(v) == 0 || v[0] == '"' || json.Unmarshal(v, &integer) != nil {
			fields = append(fields, field{"body.facts." + key, "Input should be a valid integer"})
			continue
		}
		if _, err := integer.Int64(); err != nil {
			fields = append(fields, field{"body.facts." + key, "Input should be a valid integer"})
		}
	}
	out, _ := json.Marshal(obj)
	return out, fields
}
func normalizeProfile(raw json.RawMessage) (json.RawMessage, []field) {
	var p planning.ProfileData
	_ = json.Unmarshal(raw, &p)
	var issues []field
	if _, err := time.LoadLocation(p.Timezone); err != nil || p.Timezone == "Local" || p.Timezone == "" {
		issues = append(issues, field{"body.timezone", "Value error, Unknown timezone"})
	}
	for _, d := range []struct {
		name string
		days []int
	}{{"scheduled_strength_days", p.StrengthDays}, {"strength_week_a_days", p.StrengthA}, {"strength_week_b_days", p.StrengthB}, {"mobility_week_a_days", p.MobilityA}, {"mobility_week_b_days", p.MobilityB}, {"mobility_optional_days", p.MobilityOptional}} {
		seen := map[int]bool{}
		for _, n := range d.days {
			if seen[n] || n < 0 || n > 6 {
				issues = append(issues, field{"body." + d.name, "Value error, Weekdays must be unique integers 0..6"})
				break
			}
			seen[n] = true
		}
	}
	for _, f := range []struct{ key, name string }{{"running_restriction", "RunningRestriction"}, {"running_interruption", "RunningInterruption"}} {
		v, ok := p.Facts[f.key]
		if !ok || string(v) == "null" {
			continue
		}
		if f.name == "RunningRestriction" {
			var strict []field
			v, strict = factInput(v)
			if len(strict) > 0 {
				issues = append(issues, strict...)
				break
			}
		}
		normalized, _, errs := models.Parse(f.name, "body.facts", v)
		if len(errs) > 0 {
			for _, e := range errs {
				issues = append(issues, field{e.Path, e.Message})
			}
			break
		}
		p.Facts[f.key] = normalized
	}
	if len(issues) > 0 {
		return nil, issues
	}
	var message string
	if p.AnchorConfirmed && p.Anchor == nil {
		message = "Confirmed cycle anchor requires a date"
	} else if p.Schedule == "alternating" {
		if p.WeekStart != nil {
			day, _ := time.Parse(time.DateOnly, *p.WeekStart)
			if day.Weekday() != time.Monday {
				message = "Week A start must be a Monday"
			}
		}
		if message == "" && p.StrengthConfirmed && (p.WeekStart == nil || len(p.StrengthA) != 2 || len(p.StrengthB) != 2) {
			message = "Confirmed alternating strength requires a Monday Week A start and two days in each week"
		}
	}
	if message != "" {
		return nil, []field{{"body", "Value error, " + message}}
	}
	var fields map[string]json.RawMessage
	_ = json.Unmarshal(raw, &fields)
	fields["facts"], _ = json.Marshal(p.Facts)
	result, _ := json.Marshal(fields)
	return result, nil
}
func profile(ctx context.Context, tx pgx.Tx, today string, c command) (result, error) {
	if c.full == nil {
		row, e := planning.Profile(ctx, tx)
		return result{data: row}, e
	}
	var p struct {
		planning.ProfileData
		Expected int `json:"expected_version"`
	}
	if err := json.Unmarshal(c.full, &p); err != nil {
		return result{}, err
	}
	row, err := planning.SaveProfile(ctx, tx, p.ProfileData, p.Expected, c.now)
	return result{row, true}, err
}
func interruption(ctx context.Context, tx pgx.Tx, today string, c command) (result, error) {
	var p struct {
		Expected int             `json:"expected_version"`
		Value    json.RawMessage `json:"interruption"`
	}
	if err := json.Unmarshal(c.full, &p); err != nil {
		return result{}, err
	}
	data, changed, err := planning.Interruption(ctx, tx, p.Expected, p.Value, c.now)
	return result{data, changed}, err
}
