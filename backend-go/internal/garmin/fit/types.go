package fit

import (
	"encoding/json"
	"time"
)

// DecodedFit describes a single session. Measurements use SI units where indicated.
// A nil measurement means the file could not supply an unambiguous value.
type DecodedFit struct {
	FITSHA256        string              `json:"fit_sha256"`
	ProfileVersion   string              `json:"profile_version"`
	SDKVersion       string              `json:"sdk_version"`
	Session          DecodedSession      `json:"session"`
	Laps             []DecodedLap        `json:"laps"`
	Steps            []DecodedStep       `json:"steps"`
	Stream           DecodedStream       `json:"stream"`
	MessageInventory map[string]int      `json:"message_inventory"`
	Device           map[string]any      `json:"device"`
	FieldNames       map[string][]string `json:"field_names"`
}

type DecodedSession struct {
	StartAt     time.Time `json:"start_at"`
	Sport       string    `json:"sport"`
	ElapsedS    *float64  `json:"elapsed_s"`
	TimerS      *float64  `json:"timer_s"`
	DistanceM   *float64  `json:"distance_m"`
	WorkoutRPE  *float64  `json:"workout_rpe"`
	WorkoutFeel *int      `json:"workout_feel"`
}

// EnumValue preserves codes absent from the FIT profile as JSON numbers.
type EnumValue struct {
	Name        string
	UnknownCode *int
}

func (e EnumValue) MarshalJSON() ([]byte, error) {
	if e.UnknownCode != nil {
		return json.Marshal(*e.UnknownCode)
	}
	return json.Marshal(e.Name)
}

type DecodedLap struct {
	LapIndex     int        `json:"lap_index"`
	StartAt      time.Time  `json:"start_at"`
	TimerS       *float64   `json:"timer_s"`
	ElapsedS     *float64   `json:"elapsed_s"`
	DistanceM    *float64   `json:"distance_m"`
	AvgSpeedMPS  *float64   `json:"avg_speed_mps"`
	AvgHRBPM     *float64   `json:"avg_hr_bpm"`
	MaxHRBPM     *float64   `json:"max_hr_bpm"`
	LapTrigger   *EnumValue `json:"lap_trigger"`
	WktStepIndex *int       `json:"wkt_step_index"`
	Intensity    *string    `json:"intensity"`
	EndAt        *time.Time `json:"end_at"`
}

type DecodedStep struct {
	MessageIndex  int        `json:"message_index"`
	DurationType  string     `json:"duration_type"`
	StepName      *string    `json:"step_name"`
	Intensity     *EnumValue `json:"intensity"`
	DurationValue *float64   `json:"duration_value"`
	TargetType    *EnumValue `json:"target_type"`
	TargetLow     *float64   `json:"target_low"`
	TargetHigh    *float64   `json:"target_high"`
	RepeatFrom    *int       `json:"repeat_from"`
	RepeatCount   *int       `json:"repeat_count"`
}

type DecodedStream struct {
	TS           []int      `json:"t_s"`
	HRBPM        []*int     `json:"hr_bpm"`
	SpeedMPS     []*float64 `json:"speed_mps"`
	DistanceM    []*float64 `json:"distance_m"`
	AltitudeM    []*float64 `json:"altitude_m"`
	Cadence      []*float64 `json:"cadence"`
	TimerOn      [][2]int   `json:"timer_on"`
	SampleCount  int        `json:"sample_count"`
	MaxGapS      int        `json:"max_gap_s"`
	QualityFlags []string   `json:"quality_flags"`
}
