// Package anchors writes calibrated intensity anchors and projects their metric
// content identities consistently for the anchor API and manual proposal decisions.
package anchors

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
	"math"
	"slices"
	"strings"
	"time"
)

type Input struct {
	Kind        string     `json:"kind"`
	Low         float64    `json:"value_low"`
	High        *float64   `json:"value_high"`
	Unit        string     `json:"unit"`
	Protocol    string     `json:"protocol"`
	Confidence  string     `json:"confidence"`
	At          time.Time  `json:"calibrated_at"`
	ValidFrom   string     `json:"valid_from"`
	ReviewAfter *string    `json:"review_after"`
	ActivityID  *uuid.UUID `json:"source_activity_id"`
	EventID     *uuid.UUID `json:"source_event_id"`
	ProposalID  *uuid.UUID `json:"proposal_id"`
	Conditions  *string    `json:"conditions"`
	Notes       *string    `json:"notes"`
	Supersedes  *string    `json:"supersedes_key"`
}
type Row struct {
	Input
	ID     uuid.UUID `json:"id"`
	Key    string    `json:"anchor_key"`
	Status string    `json:"status"`
}
type Problem struct {
	Code, Message string
	Status        int
}

func (p *Problem) Error() string { return p.Code }

var units = map[string]string{"hr_aerobic_upper": "bpm", "hr_threshold_lower": "bpm", "speed_aerobic_upper": "mps", "speed_threshold_lower": "mps", "performance_5k": "s", "performance_1mile": "s", "performance_3min": "m", "performance_20_30min": "mps"}

func validate(i Input) error {
	if unit, ok := units[i.Kind]; !ok || unit != i.Unit {
		return &Problem{"invalid_anchor_unit", "Anchor kind and unit do not match", 422}
	}
	if !slices.Contains(strings.Fields("race_5k time_trial_5k time_trial_1mile time_trial_3min time_trial_20_30min workout_derived lab_test manual"), i.Protocol) || !slices.Contains(strings.Fields("high moderate low insufficient"), i.Confidence) {
		return &Problem{"invalid_anchor_fields", "Invalid anchor protocol or confidence", 422}
	}
	if i.High != nil && *i.High < i.Low {
		return &Problem{"invalid_anchor_range", "Anchor upper value must be at least the lower value", 422}
	}
	for _, n := range []*float64{&i.Low, i.High} {
		if n == nil {
			continue
		}
		msg := ""
		switch {
		case math.IsNaN(*n) || math.IsInf(*n, 0):
			msg = "Anchor values must be finite"
		case strings.HasPrefix(i.Kind, "hr_") && (*n < 30 || *n > 230):
			msg = "Heart rate anchor must be 30 to 230 bpm"
		case strings.HasPrefix(i.Kind, "speed_") && (*n <= 0 || *n > 10):
			msg = "Speed anchor must be above zero and at most 10 m/s"
		case strings.HasPrefix(i.Kind, "performance_") && *n <= 0:
			msg = "Performance anchor must be positive"
		}
		if msg != "" {
			return &Problem{"invalid_anchor_value", msg, 422}
		}
	}
	if _, err := time.Parse(time.DateOnly, i.ValidFrom); err != nil {
		return &Problem{"invalid_anchor_date", "Invalid effective date", 422}
	}
	if i.ReviewAfter != nil {
		if _, err := time.Parse(time.DateOnly, *i.ReviewAfter); err != nil {
			return &Problem{"invalid_anchor_date", "Invalid review date", 422}
		}
	}
	return nil
}
func Create(ctx context.Context, tx pgx.Tx, i Input, zone string) (Row, error) {
	var r Row
	if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
		return r, err
	}
	if err := validate(i); err != nil {
		return r, err
	}
	tz, err := time.LoadLocation(zone)
	if err != nil {
		return r, err
	}
	if i.ReviewAfter == nil {
		date := i.At.In(tz).AddDate(0, 0, 84).Format(time.DateOnly)
		i.ReviewAfter = &date
	}
	var previous, from string
	err = tx.QueryRow(ctx, `SELECT a.anchor_key,a.valid_from::text FROM intensity_anchors a WHERE a.kind=$1 AND NOT EXISTS (SELECT 1 FROM intensity_anchors child WHERE child.kind=a.kind AND child.supersedes_key=a.anchor_key) ORDER BY a.valid_from DESC,a.calibrated_at DESC,a.anchor_key DESC LIMIT 1`, i.Kind).Scan(&previous, &from)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		if i.Supersedes != nil {
			return r, &Problem{"anchor_supersede_required", "No predecessor exists for this anchor", 409}
		}
	case err != nil:
		return r, err
	case i.Supersedes == nil:
		return r, &Problem{"anchor_supersede_required", "Specify the anchor being superseded", 409}
	case *i.Supersedes != previous:
		return r, &Problem{"anchor_superseded", "The selected predecessor has a newer successor", 409}
	case i.ValidFrom < from:
		return r, &Problem{"anchor_backdate_conflict", "Successor cannot predate its predecessor", 422}
	}
	base := i.Kind + "-" + i.ValidFrom
	key := base
	for suffix := 2; ; suffix++ {
		var exists bool
		if err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM intensity_anchors WHERE anchor_key=$1)", key).Scan(&exists); err != nil {
			return r, err
		}
		if !exists {
			break
		}
		key = fmt.Sprintf("%s-%d", base, suffix)
	}
	if len(key) > 40 {
		return r, &Problem{"invalid_anchor_key", "Anchor key exceeds storage limit", 422}
	}
	i.At = i.At.UTC()
	r = Row{Input: i, ID: uuid.New(), Key: key, Status: "active"}
	_, err = tx.Exec(ctx, `INSERT INTO intensity_anchors(id,anchor_key,kind,value_low,value_high,unit,protocol,confidence,status,calibrated_at,valid_from,review_after,source_activity_id,source_event_id,proposal_id,conditions,notes,supersedes_key) VALUES($1,$2,$3,$4,$5,$6,$7,$8,'active',$9,$10::date,$11::date,$12,$13,$14,$15,$16,$17)`, r.ID, key, i.Kind, i.Low, i.High, i.Unit, i.Protocol, i.Confidence, i.At, i.ValidFrom, i.ReviewAfter, i.ActivityID, i.EventID, i.ProposalID, i.Conditions, i.Notes, i.Supersedes)
	return r, err
}
func (r Row) Data() (map[string]any, error) {
	raw, err := json.Marshal(r.Input)
	if err != nil {
		return nil, err
	}
	var obj map[string]any
	if err := json.Unmarshal(raw, &obj); err != nil {
		return nil, err
	}
	obj["anchor_key"] = r.Key
	obj["calibrated_at"] = r.At
	hash, err := metrics.Digest(obj)
	if err != nil {
		return nil, err
	}
	obj["calibrated_at"] = api.Timestamp(r.At)
	obj["id"] = r.ID
	obj["status"] = r.Status
	obj["content_hash"] = hash
	return obj, nil
}
func List(ctx context.Context, tx pgx.Tx) ([]map[string]any, error) {
	rows, err := tx.Query(ctx, "SELECT to_jsonb(a) FROM intensity_anchors a ORDER BY kind,valid_from,calibrated_at,anchor_key")
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (map[string]any, error) {
		var r Row
		if err := row.Scan(&r); err != nil {
			return nil, err
		}
		return r.Data()
	})
}
