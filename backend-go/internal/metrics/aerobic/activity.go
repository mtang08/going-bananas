package aerobic

import (
	"context"

	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/calendarstructure"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/recording"
	"slices"
	"strings"
	"time"
)

func planClass(p *recording.Plan) string {
	if p.Recipe != nil {
		switch *p.Recipe {
		case "REC001", "REC007":
			return "easy"
		case "REC002":
			return "long"
		case "REC003", "REC004", "REC005", "REC006", "REC008":
			return "quality"
		case "REC009":
			return "benchmark"
		case "REC010":
			return "cross"
		default:
			return "unknown"
		}
	}
	text := strings.ToLower(p.Intent)
	for _, rule := range []struct {
		class string
		words []string
	}{{"benchmark", []string{"race", "benchmark", "time trial"}}, {"long", []string{"long"}}, {"quality", []string{"interval", "tempo", "threshold", "quality", "hill", "vo2", "fartlek"}}, {"easy", []string{"easy", "recovery", "shakeout"}}} {
		for _, word := range rule.words {
			if strings.Contains(text, word) {
				return rule.class
			}
		}
	}
	return "unknown"
}
func classify(ctx context.Context, tx pgx.Tx, id uuid.UUID, plan *recording.Plan) (string, string, error) {
	if plan != nil && plan.Kind == "run" {
		if len(plan.Structure) > 0 && string(plan.Structure) != "null" && string(plan.Structure) != "[]" {
			steps, ok := calendarstructure.Expand(plan.Structure)
			if !ok {
				return "", "", errors.New("invalid_structure")
			}
			n := 0
			for _, s := range steps {
				if s.Type == "work" {
					n++
				}
			}
			if n >= 2 {
				return "structured", "STRUCTURED_SESSION", nil
			}
		}
		cls := planClass(plan)
		if cls == "easy" || cls == "long" {
			return cls, "", nil
		}
		if cls != "unknown" {
			return cls, "NOT_EASY_OR_LONG", nil
		}
	}
	var label *string
	err := tx.QueryRow(ctx, `SELECT (SELECT workout_label FROM activity_annotations WHERE activity_id=$1 ORDER BY version DESC LIMIT 1)`, id).Scan(&label)
	if err != nil {
		return "", "", err
	}
	if label != nil {
		switch *label {
		case "easy", "long":
			return *label, "", nil
		case "quality", "other":
			return *label, "NOT_EASY_OR_LONG", nil
		}
	}
	steps, err := recording.Steps(ctx, tx, id)
	if err != nil {
		return "", "", err
	}
	watch, err := recording.Expand(steps)
	if err != nil {
		return "structured", "STRUCTURED_SESSION", nil
	}
	work := 0
	for _, w := range watch {
		if w.Intensity == "active" || w.Intensity == "interval" {
			work++
		}
	}
	if work >= 2 {
		return "structured", "STRUCTURED_SESSION", nil
	}
	return "unplanned", "", nil
}
func Calculate(ctx context.Context, tx pgx.Tx, id uuid.UUID) (*metrics.Result, error) {
	zone, err := db.New(tx).CalendarTimezone(ctx)
	if err != nil {
		return nil, err
	}
	r, err := metrics.LoadRun(ctx, tx, id, zone)
	if err != nil || r == nil {
		return nil, err
	}
	if !slices.Contains([]string{"running", "trail_running", "treadmill_running"}, r.Sport) {
		return nil, nil
	}
	refs, plan, err := recording.Sources(ctx, tx, r)
	if err != nil {
		return nil, err
	}
	out := early("not_applicable", "ACTIVITY_EXCLUDED")
	if r.Eligible {
		cls, reason, err := classify(ctx, tx, id, plan)
		if err != nil {
			return nil, err
		}
		if reason != "" {
			out = early("not_applicable", reason)
		} else {
			s, err := recording.LoadStream(ctx, tx, id)
			if err != nil {
				return nil, err
			}
			out, err = calculate(s, r.Sport == "treadmill_running")
			if err != nil {
				return nil, err
			}
			if out.value != nil {
				out.value["session_class"] = cls
				out.value["activity_id"] = id.String()
				out.value["local_date"] = r.Day
				out.value["sport"] = r.Sport
			}
		}
	}
	return &metrics.Result{MetricID: ID, MethodVersion: Version, SubjectType: "activity", SubjectKey: id.String(), WindowStart: &r.Start, WindowEnd: r.End, WindowLabel: r.Day, Status: out.status, QualityStatus: out.quality, Value: out.value, ReasonCodes: out.reasons, QualityFlags: out.flags, Unit: "m_per_beat", Timezone: zone, SourceRefs: refs, Config: Config}, nil
}

func Refresh(ctx context.Context, tx pgx.Tx, id uuid.UUID, now time.Time) (uuid.UUID, error) {
	r, err := Calculate(ctx, tx, id)
	if err != nil || r == nil {
		return uuid.Nil, err
	}
	return metrics.StoreResult(ctx, tx, *r, now)
}
