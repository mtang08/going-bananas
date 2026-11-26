package metrics

import (
	"context"
	"encoding/json"
	"errors"
	"slices"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
)

// Result contains one calculator output and the inputs that identify its immutable history.
type Result struct {
	MetricID, MethodVersion, SubjectType, SubjectKey   string
	WindowStart, WindowEnd                             *time.Time
	WindowLabel, Status, QualityStatus, Unit, Timezone string
	Value                                              any
	ReasonCodes, QualityFlags, AnchorKeys              []string
	SourceRefs, Config                                 map[string]any
	AnchorSetHash                                      *string
	CalculatorDependencyHash                           string
}

func hasProvenance(refs map[string]any) bool {
	for _, k := range []string{"input_hash", "completion_association_hash"} {
		if s, ok := refs[k].(string); ok && s != "" {
			return true
		}
	}
	for _, k := range []string{"sources", "recovery"} {
		switch v := refs[k].(type) {
		case []any:
			if len(v) > 0 {
				return true
			}
		case map[string]any:
			if len(v) > 0 {
				return true
			}
		}
	}
	for _, key := range []string{"activity", "plan", "checkin"} {
		r, ok := refs[key].(map[string]any)
		if !ok {
			continue
		}
		switch key {
		case "activity":
			if r["id"] != nil && r["source_revision"] != nil {
				return true
			}
		case "plan":
			if r["revision_id"] != nil && r["calendar_version"] != nil {
				return true
			}
		case "checkin":
			if r["id"] != nil && r["version"] != nil {
				return true
			}
		}
	}
	if records, ok := refs["source_records"].([]any); ok {
		for _, v := range records {
			if row, ok := v.(map[string]any); ok && row["payload_hash"] != nil {
				return true
			}
		}
	}
	return false
}

type prepared struct {
	Result
	cfg, dep string
	refs     []byte
}

func prepare(r Result) (prepared, error) {
	cfg, err := Digest(r.Config)
	if err != nil {
		return prepared{}, err
	}
	refs, err := canonicaljson.Metric(r.SourceRefs)
	if err != nil {
		return prepared{}, err
	}
	normalized, err := JSONValue(refs)
	if err != nil {
		return prepared{}, err
	}
	dep, err := Digest(object{"source_refs": normalized, "config_hash": cfg, "anchor_set_hash": r.AnchorSetHash, "timezone": r.Timezone, "calculator_dependency_hash": r.CalculatorDependencyHash})
	if err != nil {
		return prepared{}, err
	}
	normalizedRefs, _ := normalized.(map[string]any)
	if !hasProvenance(normalizedRefs) || r.Timezone == "" {
		r.Status = "invalid"
		r.Value = nil
		if !slices.Contains(r.ReasonCodes, "MISSING_PROVENANCE") {
			r.ReasonCodes = append(r.ReasonCodes, "MISSING_PROVENANCE")
		}
		dep, err = Digest(object{"missing_provenance": true, "computed": dep})
		if err != nil {
			return prepared{}, err
		}
	}
	r.SourceRefs = normalizedRefs
	return prepared{r, cfg, dep, refs}, nil
}

// Preview returns the transient metric row shape without accessing storage.
func Preview(r Result, now time.Time) (map[string]any, error) {
	p, err := prepare(r)
	if err != nil {
		return nil, err
	}
	nullable := func(s string) any {
		if s == "" {
			return nil
		}
		return s
	}
	return map[string]any{"id": nil, "metric_id": p.MetricID, "method_version": p.MethodVersion, "subject_type": p.SubjectType, "subject_key": p.SubjectKey,
		"window_start": p.WindowStart, "window_end": p.WindowEnd, "window_label": nullable(p.WindowLabel), "status": p.Status, "quality_status": nullable(p.QualityStatus),
		"value": p.Value, "unit": nullable(p.Unit), "reason_codes": append([]string{}, p.ReasonCodes...), "quality_flags": append([]string{}, p.QualityFlags...),
		"source_refs": p.SourceRefs, "anchor_keys": append([]string{}, p.AnchorKeys...), "config_hash": p.cfg, "anchor_set_hash": p.AnchorSetHash, "dependency_hash": p.dep,
		"calculated_at": now, "timezone": p.Timezone, "is_current": false}, nil
}

// StoreResult registers the config and selects or creates the immutable metric result on the caller's locked transaction.
func StoreResult(ctx context.Context, tx pgx.Tx, r Result, now time.Time) (uuid.UUID, error) {
	p, err := prepare(r)
	if err != nil {
		return uuid.Nil, err
	}
	r = p.Result
	cfg, dep, refs := p.cfg, p.dep, p.refs
	_, err = tx.Exec(ctx, `INSERT INTO metric_configs(id,metric_id,method_version,config,config_hash) VALUES(gen_random_uuid(),$1,$2,$3,$4) ON CONFLICT(metric_id,method_version,config_hash) DO NOTHING`, r.MetricID, r.MethodVersion, r.Config, cfg)
	if err != nil {
		return uuid.Nil, err
	}
	_, err = tx.Exec(ctx, `UPDATE metric_results SET is_current=false WHERE metric_id=$1 AND method_version=$2 AND subject_key=$3 AND is_current AND (config_hash<>$4 OR coalesce(anchor_set_hash,'')<>coalesce($5,'') OR dependency_hash<>$6)`, r.MetricID, r.MethodVersion, r.SubjectKey, cfg, r.AnchorSetHash, dep)
	if err != nil {
		return uuid.Nil, err
	}
	var id uuid.UUID
	err = tx.QueryRow(ctx, `UPDATE metric_results SET is_current=true WHERE metric_id=$1 AND method_version=$2 AND subject_key=$3 AND config_hash=$4 AND coalesce(anchor_set_hash,'')=coalesce($5,'') AND dependency_hash=$6 RETURNING id`, r.MetricID, r.MethodVersion, r.SubjectKey, cfg, r.AnchorSetHash, dep).Scan(&id)
	if !errors.Is(err, pgx.ErrNoRows) {
		return id, err
	}
	value, err := json.Marshal(r.Value)
	if err != nil {
		return uuid.Nil, err
	}
	err = tx.QueryRow(ctx, `INSERT INTO metric_results(id,metric_id,method_version,subject_type,subject_key,window_start,window_end,window_label,status,quality_status,value,unit,reason_codes,quality_flags,source_refs,anchor_keys,config_hash,anchor_set_hash,calculated_at,dependency_hash,timezone,is_current)
 VALUES(gen_random_uuid(),$1,$2,$3,$4,$5,$6,nullif($7,''),$8,nullif($9,''),$10::jsonb,nullif($11,''),coalesce($12::varchar[],'{}'),coalesce($13::varchar[],'{}'),$14::jsonb,coalesce($15::varchar[],'{}'),$16,$17,$18,$19,$20,true) RETURNING id`,
		r.MetricID, r.MethodVersion, r.SubjectType, r.SubjectKey, r.WindowStart, r.WindowEnd, r.WindowLabel, r.Status, r.QualityStatus, value, r.Unit, r.ReasonCodes, r.QualityFlags, refs, r.AnchorKeys, cfg, r.AnchorSetHash, now, dep, r.Timezone).Scan(&id)
	return id, err
}
