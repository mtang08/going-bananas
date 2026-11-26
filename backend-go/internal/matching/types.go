// Package matching reconciles plans and recorded sessions without mutating either.
package matching

// Input dates are local calendar dates in YYYY-MM-DD format. Runs includes
// runs and strength subjects, in the caller's recording order.
type Input struct {
	Days        []string     `json:"days"`
	ContextDays []string     `json:"context_days"`
	Planned     []Plan       `json:"planned"`
	Runs        []Subject    `json:"runs"`
	Completions []Completion `json:"completions"`
}

type Plan struct {
	SessionUID       string   `json:"session_uid"`
	LocalDate        string   `json:"local_date"`
	Kind             string   `json:"kind"`
	Deleted          bool     `json:"deleted"`
	Skipped          bool     `json:"skipped"`
	PlannedDurationS *float64 `json:"planned_duration_s"`
	PlannedDistanceM *float64 `json:"planned_distance_m"`
	HasWorkSteps     *bool    `json:"has_work_steps"`
}

// SubjectRef accepts either a canonical subject key or the completion table's
// activity, Strong, and manual session identifiers.
type SubjectRef struct {
	SubjectKey      string `json:"subject_key"`
	ActivityID      string `json:"activity_id"`
	StrongWorkoutID string `json:"strong_workout_id"`
	ManualSessionID string `json:"manual_session_id"`
}

func (ref SubjectRef) key() string {
	switch {
	case ref.SubjectKey != "":
		return ref.SubjectKey
	case ref.ActivityID != "":
		return ref.ActivityID
	case ref.StrongWorkoutID != "":
		return "strong:" + ref.StrongWorkoutID
	case ref.ManualSessionID != "":
		return "manual:" + ref.ManualSessionID
	default:
		return ""
	}
}

type Subject struct {
	SubjectRef
	LocalDate       string   `json:"local_date"`
	Kind            string   `json:"kind"`
	Eligible        *bool    `json:"eligible"`
	ResolutionState *string  `json:"resolution_state"`
	TimerS          *float64 `json:"timer_s"`
	DistanceM       *float64 `json:"distance_m"`
	HasWorkoutSteps *bool    `json:"has_workout_steps"`
}

type Completion struct {
	SubjectRef
	SessionUID  string `json:"session_uid"`
	Status      string `json:"status"`
	MatchMethod string `json:"match_method"`
}

type Link struct {
	SessionUID  string `json:"session_uid"`
	SubjectKey  string `json:"subject_key"`
	MatchMethod string `json:"match_method"`
}

type Candidate struct {
	SubjectKey string   `json:"subject_key"`
	LocalDate  string   `json:"local_date"`
	Kind       string   `json:"kind"`
	Reason     string   `json:"reason"`
	Cost       *float64 `json:"cost,omitempty"`
}

type Result struct {
	DeleteAutoSessionUIDs  []string               `json:"delete_auto_session_uids"`
	DeleteExtraSubjectKeys []string               `json:"delete_extra_subject_keys"`
	Links                  []Link                 `json:"links"`
	Extras                 []Link                 `json:"extras"`
	Candidates             map[string][]Candidate `json:"candidates"`
}
