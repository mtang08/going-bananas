package recovery

import (
	"context"
	"github.com/jackc/pgx/v5"
)

// NightPreview returns the recovery fields displayed by the dashboard without persisting a metric.
func NightPreview(ctx context.Context, tx pgx.Tx, key string) (map[string]any, error) {
	r, err := compute(ctx, tx, key)
	if err != nil {
		return nil, err
	}
	out := r.Outcome
	return map[string]any{"value": out.value, "status": out.status, "quality_status": out.quality, "reason_codes": out.reasons, "quality_flags": out.flags}, nil
}
