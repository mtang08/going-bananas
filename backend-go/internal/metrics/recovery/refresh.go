package recovery

import (
	"context"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
	"time"
)

var config = map[string]any{
	"baseline_days": 60, "min_nights": 14, "established_nights": 28, "stale_days": 14, "stale_min_nights": 7, "robust_factor": 0.6745, "adverse_z": 1.5, "subjective_fatigue": 7, "hrv_transform": "ln",
	"statistics":     map[string]string{"sleep": "main_sleep_duration", "hrv": "last_night_average", "resting_hr": "daily_resting"},
	"valid_ranges":   map[string]any{"sleep": map[string]int{"low_exclusive": 0, "high": 86400}, "hrv": map[string]int{"low_exclusive": 0}, "resting_hr": map[string]int{"low": 30, "high": 230}},
	"partition_rule": "source_definition_device.v1",
}

func Refresh(ctx context.Context, tx pgx.Tx, key string, now time.Time) (uuid.UUID, error) {
	r, err := compute(ctx, tx, key)
	if err != nil {
		return uuid.Nil, err
	}
	out := r.Outcome
	var quality string
	if out.quality != nil {
		quality = *out.quality
	}
	return metrics.StoreResult(ctx, tx, metrics.Result{MetricID: MetricID, MethodVersion: MethodVersion, SubjectType: r.SubjectType, SubjectKey: key, WindowStart: &r.Start, WindowEnd: &r.End, WindowLabel: key, Status: out.status, QualityStatus: quality, Timezone: r.Zone, Value: out.value, ReasonCodes: out.reasons, QualityFlags: out.flags, SourceRefs: r.Refs, Config: config}, now)
}
