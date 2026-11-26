package trainingwindows

import (
	"context"
	"fmt"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
	"time"
)

func ConfigHash(metricID string) (string, error) {
	var config object
	switch metricID {
	case "symptom_response_timeline":
		config = symptomConfig
	case "session_rpe_load":
		config = rpeConfig
	case "long_run_exposure":
		config = longConfig
	default:
		return "", fmt.Errorf("unknown activity metric %q", metricID)
	}
	return metrics.Digest(config)
}

// CalculateActivity produces an unstored result for the selected recording, using read-only queries.
func CalculateActivity(ctx context.Context, tx pgx.Tx, metricID string, id uuid.UUID, zone string) (*metrics.Result, error) {
	r, err := metrics.LoadRun(ctx, tx, id, zone)
	if err != nil || r == nil {
		return nil, err
	}
	if !isRunning(r.Sport) {
		return nil, nil
	}
	if metricID == "session_rpe_load" {
		facts, err := rpeRuns(ctx, tx, []*metrics.Run{r})
		if err != nil {
			return nil, err
		}
		f := facts[0]
		f.excluded = !r.Eligible
		f.refs["activity_id"] = id
		out := rpeResult(f, zone)
		return &out, nil
	}
	facts, err := linkedCheckins(ctx, tx, id, zone)
	if err != nil {
		return nil, err
	}
	switch metricID {
	case "symptom_response_timeline":
		return symptomActivity(ctx, tx, r, facts, zone)
	case "long_run_exposure":
		loc, err := time.LoadLocation(zone)
		if err != nil {
			return nil, err
		}
		return longActivity(ctx, tx, r, facts, loc)
	default:
		return nil, fmt.Errorf("unknown activity metric %q", metricID)
	}
}

func Configs() map[string]map[string]any {
	return map[string]map[string]any{"run_volume_frequency": volumeConfig, "long_run_exposure": longConfig, "session_rpe_load": rpeConfig, "symptom_response_timeline": symptomConfig}
}
