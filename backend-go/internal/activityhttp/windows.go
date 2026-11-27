package activityhttp

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/httpinput"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
)

func (h Handler) windows(ctx context.Context, tx pgx.Tx, r *http.Request, now time.Time, loc *time.Location) (any, error) {
	day := now.In(loc).Format(time.DateOnly)
	if s, ok := parameter(r.URL.Query(), "as_of"); ok {
		parsed, msg := httpinput.Date(s)
		if msg != "" {
			return nil, invalid("query.as_of", msg)
		}
		day = parsed
	}
	asOf, err := time.ParseInLocation(time.DateOnly, day, loc)
	if err != nil {
		return nil, err
	}
	width := []int{7, 14, 28, 56}
	keys := func(n int) string { return fmt.Sprintf("w%d:%s", n, day) }
	rows := map[string]map[string]map[string]any{}
	for _, m := range []struct {
		id     string
		widths []int
	}{{"run_volume_frequency", width}, {"long_run_exposure", width}, {"intensity_time_distribution", width}, {"session_rpe_load", width}, {"hard_session_spacing", []int{14}}, {"aerobic_efficiency", []int{28, 84}}, {"symptom_response_timeline", []int{28}}} {
		var subjects []string
		for _, n := range m.widths {
			key := keys(n)
			if m.id == "session_rpe_load" {
				subjects = append(subjects, key+":run", key+":strength")
			} else {
				subjects = append(subjects, key)
			}
		}
		records, err := refresh.ReadWindows(ctx, tx, m.id, subjects, asOf, now)
		if err != nil {
			return nil, err
		}
		for _, row := range records {
			timestamps(row, "window_start", "window_end", "calculated_at")
		}
		rows[m.id] = records
	}
	windows := []object{}
	for _, n := range width {
		key := keys(n)
		windows = append(windows, object{"days": n, "volume": rows["run_volume_frequency"][key], "long_run": rows["long_run_exposure"][key], "intensity": rows["intensity_time_distribution"][key], "srpe": rows["session_rpe_load"][key+":run"], "srpe_strength": rows["session_rpe_load"][key+":strength"]})
	}
	return object{"as_of": day, "windows": windows, "spacing": rows["hard_session_spacing"][keys(14)], "aerobic": object{"w28": rows["aerobic_efficiency"][keys(28)], "w84": rows["aerobic_efficiency"][keys(84)]}, "symptoms": rows["symptom_response_timeline"][keys(28)]}, nil
}
