package snapshotreads

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/mtang08/going-bananas/backend-go/internal/athletefacts"
	"math"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"
)

type Profile struct {
	Version int `json:"profile_version"`
	ProfileMetadata
	hasInterruption bool
}

type ProfileMetadata struct {
	Timezone            string              `json:"timezone"`
	CycleAnchor         *string             `json:"cycle_anchor"`
	AnchorConfirmed     bool                `json:"anchor_confirmed"`
	ClinicalRestriction *string             `json:"clinical_restriction"`
	RunningRestriction  *RunningRestriction `json:"running_restriction"`
	CalendarVersion     int                 `json:"calendar_version"`
	DataRevision        int                 `json:"data_revision"`
}

type RunningRestriction struct {
	StartsOn          string  `json:"starts_on"`
	EndsOn            *string `json:"ends_on"`
	ReviewOn          *string `json:"review_on"`
	PauseRunning      bool    `json:"pause_running"`
	NoQuality         bool    `json:"no_quality"`
	MaxDistanceM      *int    `json:"max_distance_m"`
	MaxDurationS      *int    `json:"max_duration_s"`
	Source            string  `json:"source"`
	Wording           *string `json:"wording"`
	NeedsConfirmation bool    `json:"needs_confirmation"`
}

func LoadProfile(ctx context.Context, tx pgx.Tx, asOf string) (Profile, error) {
	var p Profile
	var clinical, legacy *string
	var legacyFlag, limit json.RawMessage
	err := tx.QueryRow(ctx, `SELECT coalesce(p.version,0),coalesce(nullif(p.timezone,''),'America/New_York'),
		to_char(p.cycle_anchor,'YYYY-MM-DD'),coalesce(p.anchor_confirmed,false),
		CASE WHEN jsonb_typeof(p.facts->'clinical_restriction')='string' THEN p.facts->>'clinical_restriction' END,
		CASE WHEN jsonb_typeof(p.facts->'clinician_restriction')='string' THEN p.facts->>'clinician_restriction' END,
		p.facts->'clinical_restriction_active',p.facts->'running_restriction',
		coalesce(p.facts->'running_interruption' <> 'null'::jsonb,false),
		coalesce(s.calendar_head_version,0),coalesce(s.data_revision,0)
		FROM (VALUES(1)) anchor(n) LEFT JOIN app_state s ON s.id=1
		LEFT JOIN (SELECT version,timezone,cycle_anchor,anchor_confirmed,facts FROM profile_versions ORDER BY version DESC LIMIT 1) p ON true`).Scan(
		&p.Version, &p.Timezone, &p.CycleAnchor, &p.AnchorConfirmed, &clinical, &legacy, &legacyFlag, &limit, &p.hasInterruption, &p.CalendarVersion, &p.DataRevision)
	if err != nil {
		return p, err
	}
	if p.Timezone == "Local" {
		return p, errors.New("invalid athlete timezone")
	}
	if _, err := time.LoadLocation(p.Timezone); err != nil {
		return p, err
	}
	p.ClinicalRestriction = athletefacts.ClinicalRestriction(clinical, legacy, legacyFlag)
	p.RunningRestriction, err = parseRestriction(limit, asOf)
	return p, err
}

var errRestriction = errors.New("invalid recorded running restriction")

func restrictionBool(raw json.RawMessage) (bool, error) {
	if raw == nil {
		return false, nil
	}
	var v any
	if err := json.Unmarshal(raw, &v); err != nil {
		return false, errRestriction
	}
	switch x := v.(type) {
	case bool:
		return x, nil
	case float64:
		if x == 1 || x == 0 {
			return x == 1, nil
		}
	case string:
		switch strings.ToLower(x) {
		case "1", "true", "t", "yes", "y", "on":
			return true, nil
		case "0", "false", "f", "no", "n", "off":
			return false, nil
		}
	}
	return false, errRestriction
}

// The typed editor stores ISO dates. Older JSON facts can represent a date as
// an exact-midnight timestamp, which the Python model also accepts.
func restrictionDate(raw json.RawMessage) (string, error) {
	var v any
	if err := json.Unmarshal(raw, &v); err != nil {
		return "", errRestriction
	}
	var seconds float64
	switch d := v.(type) {
	case float64:
		seconds = d
	case string:
		for _, layout := range []string{time.DateOnly, time.RFC3339Nano, "2006-01-02T15:04:05", "2006-01-02 15:04:05"} {
			t, err := time.Parse(layout, d)
			if err == nil && t.Year() > 0 && t.Hour() == 0 && t.Minute() == 0 && t.Second() == 0 && t.Nanosecond() == 0 {
				return t.Format(time.DateOnly), nil
			}
		}
		var err error
		seconds, err = strconv.ParseFloat(d, 64)
		if err != nil {
			return "", errRestriction
		}
	default:
		return "", errRestriction
	}
	if math.Abs(seconds) > 2e10 {
		seconds /= 1000
	}
	if math.Mod(seconds, 86400) != 0 || seconds < -62135596800 || seconds > 253402214400 {
		return "", errRestriction
	}
	return time.Unix(int64(seconds), 0).UTC().Format(time.DateOnly), nil
}

func parseRestriction(raw json.RawMessage, asOf string) (*RunningRestriction, error) {
	if len(raw) == 0 || string(raw) == "null" {
		return nil, nil
	}
	// Source profile facts can predate the typed editor. Validate the record
	// before projecting it, so malformed limits cannot silently disappear.
	var obj map[string]json.RawMessage
	if err := json.Unmarshal(raw, &obj); err != nil || obj == nil {
		return nil, errRestriction
	}
	for k := range obj {
		switch k {
		case "starts_on", "ends_on", "review_on", "pause_running", "no_quality", "max_distance_m", "max_duration_s", "source", "wording":
		default:
			return nil, errRestriction
		}
	}
	pause, err := restrictionBool(obj["pause_running"])
	if err != nil {
		return nil, err
	}
	noQuality, err := restrictionBool(obj["no_quality"])
	if err != nil {
		return nil, err
	}
	delete(obj, "pause_running")
	delete(obj, "no_quality")
	for _, key := range []string{"starts_on", "ends_on", "review_on"} {
		value := obj[key]
		if len(value) == 0 || string(value) == "null" {
			continue
		}
		date, err := restrictionDate(value)
		if err != nil {
			return nil, err
		}
		obj[key], _ = json.Marshal(date)
	}
	remaining, err := json.Marshal(obj)
	if err != nil {
		return nil, err
	}
	r := RunningRestriction{PauseRunning: pause, NoQuality: noQuality}
	if err := json.Unmarshal(remaining, &r); err != nil {
		return nil, errRestriction
	}
	for _, d := range []*string{&r.StartsOn, r.EndsOn, r.ReviewOn} {
		if d == nil {
			continue
		}
		if *d == "" {
			return nil, errRestriction
		}
		if *d < r.StartsOn {
			return nil, errRestriction
		}
	}
	r.Source = strings.TrimSpace(r.Source)
	if r.Source == "" || utf8.RuneCountInString(r.Source) > 120 {
		return nil, errRestriction
	}
	if r.Wording != nil {
		*r.Wording = strings.TrimSpace(*r.Wording)
		if utf8.RuneCountInString(*r.Wording) > 1000 {
			return nil, errRestriction
		}
	}
	if r.MaxDistanceM != nil && *r.MaxDistanceM <= 0 || r.MaxDurationS != nil && *r.MaxDurationS <= 0 {
		return nil, errRestriction
	}
	if !r.PauseRunning && !r.NoQuality && r.MaxDistanceM == nil && r.MaxDurationS == nil {
		return nil, errRestriction
	}
	r.NeedsConfirmation = r.EndsOn == nil && r.ReviewOn != nil && asOf >= *r.ReviewOn
	return &r, nil
}
