package exceptions

import "time"

type SymptomFact struct {
	ID       string  `json:"id"`
	Site     string  `json:"site"`
	Side     string  `json:"side"`
	Severity float64 `json:"severity"`
	Timing   string  `json:"timing"`
}

type CheckinFact struct {
	ID               string        `json:"id"`
	Kind             string        `json:"kind"`
	ObservedAt       time.Time     `json:"observed_at"`
	RecordedAt       time.Time     `json:"recorded_at"`
	LocalDate        string        `json:"local_date"`
	Fatigue          *float64      `json:"fatigue"`
	Illness          *string       `json:"illness"`
	GaitChange       *string       `json:"gait_change"`
	ContextTags      []string      `json:"context_tags"`
	ActivityID       *string       `json:"activity_id"`
	LinkedActivityID *string       `json:"linked_activity_id"`
	Symptoms         []SymptomFact `json:"symptoms"`
}

type RpeRun struct {
	ActivityID string     `json:"activity_id"`
	LocalDate  string     `json:"local_date"`
	StartAt    time.Time  `json:"start_at"`
	EndAt      *time.Time `json:"end_at"`
	RPE        *float64   `json:"rpe"`
	RPESource  *string    `json:"rpe_source"`
	RPEAt      *time.Time `json:"rpe_at"`
	SessionUID *string    `json:"session_uid"`
}

type SessionFact struct {
	SessionUID          string     `json:"session_uid"`
	LocalDate           string     `json:"local_date"`
	Kind                string     `json:"kind"`
	RecipeID            *string    `json:"recipe_id"`
	Intent              string     `json:"intent"`
	Certainty           string     `json:"certainty"`
	SessionClass        string     `json:"session_class"`
	ExpectedRPE         *[]float64 `json:"expected_rpe"`
	CompletionStatus    *string    `json:"completion_status"`
	ModificationReason  *string    `json:"modification_reason"`
	ActivityID          *string    `json:"activity_id"`
	PlannedAt           time.Time  `json:"planned_at"`
	CompletionUpdatedAt *time.Time `json:"completion_updated_at"`
}

type PlannedActualFact struct {
	ReasonCodes    []string `json:"reason_codes"`
	TargetCoverage *string  `json:"target_coverage"`
}

type EventFact struct {
	ID           string     `json:"id"`
	Name         string     `json:"name"`
	EventDate    string     `json:"event_date"`
	Purpose      string     `json:"purpose"`
	Status       string     `json:"status"`
	HasRunOnDate bool       `json:"has_run_on_date"`
	RunEndAt     *time.Time `json:"run_end_at"`
}

type BlockBenchmarkFact struct {
	BlockUID         string     `json:"block_uid"`
	Version          int        `json:"version"`
	VersionCreatedAt time.Time  `json:"version_created_at"`
	PlannedDate      *string    `json:"planned_date"`
	ReviewDate       string     `json:"review_date"`
	Kind             *string    `json:"kind"`
	EventID          *string    `json:"event_id"`
	Status           string     `json:"status"`
	ActivityID       *string    `json:"activity_id"`
	LocalDate        *string    `json:"local_date"`
	EvidenceAt       *time.Time `json:"evidence_at"`
	Protocol         *string    `json:"protocol"`
	MatchMethod      *string    `json:"match_method"`
	DistanceM        *int       `json:"distance_m"`
	ResultS          *int       `json:"result_s"`
	RPE              *float64   `json:"rpe"`
}

type DetectionInputs struct {
	Today                  string                       `json:"today"`
	Now                    time.Time                    `json:"now"`
	TZ                     string                       `json:"tz"`
	Checkins               []CheckinFact                `json:"checkins"`
	Runs                   []RpeRun                     `json:"runs"`
	Sessions               []SessionFact                `json:"sessions"`
	PlannedActual          map[string]PlannedActualFact `json:"planned_actual"`
	RecoveryAdverseDates   []string                     `json:"recovery_adverse_dates"`
	Events                 []EventFact                  `json:"events"`
	BlockBenchmark         *BlockBenchmarkFact          `json:"block_benchmark"`
	ClinicianRestriction   *string                      `json:"clinician_restriction"`
	ClinicianRestrictionAt *time.Time                   `json:"clinician_restriction_at"`
}
