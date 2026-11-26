package assessment

import (
	"context"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
)

type object = map[string]any

func runActivity(ctx context.Context, tx pgx.Tx, id uuid.UUID, zone string, planRef object, association any) (*Activity, object, string, error) {
	run, err := metrics.LoadRun(ctx, tx, id, zone)
	if err != nil {
		return nil, nil, "", err
	}
	if run == nil {
		return nil, object{"activity_id": id.String(), "resolution_state": nil}, "", nil
	}
	out := object{"activity": object{"id": id, "source_revision": run.SourceRevision, "source_refs": run.Refs}, "fit": run.FIT, "plan": planRef, "completion_association_hash": association}
	if !run.Eligible {
		out["activity_id"] = id
		out["resolution_state"] = run.State
		return nil, out, run.Day, nil
	}
	return &Activity{Kind: "run", Sport: run.Sport, Timer: run.Timer, Distance: run.Distance}, out, run.Day, nil
}
