package intervals

import (
	"encoding/json"
	"fmt"
	"github.com/mtang08/going-bananas/backend-go/internal/calendarstructure"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/recording"
	"os"
	"reflect"
	"testing"
)

func TestPythonScoring(t *testing.T) {
	path := os.Getenv("INTERVAL_SCORING")
	if path == "" {
		t.Skip("run check_interval_scoring.py")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Steps []calendarstructure.Step
		Fit   []recording.FitStep
		Laps  []struct {
			Index     int      `json:"lap_index"`
			Ref       *int     `json:"wkt_step_index"`
			Start     float64  `json:"start_offset_s"`
			End       *float64 `json:"end_offset_s"`
			Elapsed   *float64 `json:"elapsed_s"`
			Timer     *float64 `json:"timer_s"`
			Distance  *float64 `json:"distance_m"`
			Speed     *float64 `json:"avg_speed_mps"`
			Intensity *string  `json:"intensity"`
			Pace      *float64 `json:"confirmed_pace_s_per_mile"`
		}
		Stream    *recording.Stream
		Treadmill bool
		Expected  obj
	}
	if err = json.Unmarshal(raw, &cases); err != nil || len(cases) == 0 {
		t.Fatal(err)
	}
	for i, c := range cases {
		t.Run(fmt.Sprint(i), func(t *testing.T) {
			var laps []lap
			for _, l := range c.Laps {
				laps = append(laps, lap{l.Index, l.Ref, l.Start, l.End, l.Elapsed, l.Timer, l.Distance, l.Speed, l.Intensity, l.Pace})
			}
			o, err := execute(c.Steps, c.Fit, laps, c.Stream, c.Treadmill)
			if err != nil {
				t.Fatal(err)
			}
			var quality any
			if o.quality != "" {
				quality = o.quality
			}
			payload, _ := json.Marshal(obj{"status": o.status, "quality_status": quality, "quality_flags": o.flags, "reason_codes": o.reasons, "value": o.value})
			var got obj
			if err = json.Unmarshal(payload, &got); err != nil {
				t.Fatal(err)
			}
			for k, v := range got {
				if !reflect.DeepEqual(v, c.Expected[k]) {
					t.Fatalf("%s: got %v want %v", k, v, c.Expected[k])
				}
			}
		})
	}
}
