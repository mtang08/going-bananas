package trainingwindows

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
)

// Calculate reads the source evidence for all registered widths of one window metric.
func Calculate(ctx context.Context, tx pgx.Tx, metric string, asOf time.Time) (map[string]metrics.Result, error) {
	calculators := map[string]func(context.Context, pgx.Tx, time.Time, func(metrics.Result) error) error{
		"run_volume_frequency": calculateVolume, "session_rpe_load": calculateRPE, "aerobic_efficiency": calculateAerobic,
		"long_run_exposure": calculateLong, "symptom_response_timeline": calculateSymptoms, "intensity_time_distribution": calculateIntensity,
	}
	calculate, ok := calculators[metric]
	if !ok {
		return nil, fmt.Errorf("unknown training window metric %q", metric)
	}
	rows := map[string]metrics.Result{}
	err := calculate(ctx, tx, asOf, func(r metrics.Result) error { rows[r.SubjectKey] = r; return nil })
	return rows, err
}
